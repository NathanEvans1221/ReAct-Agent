import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from main import MiniMaxReActAgent


class IntegrationTests(unittest.TestCase):
    def test_injected_sdk_preserves_minimax_reasoning_and_observation(self):
        raw = "<think>私有推理\nFinal Answer: 不可採用\n</think>\nThought: 計算\nAction: calculator\nAction Input: 2+3"
        requests = []
        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            content = raw if len(requests) == 1 else "<think>完成</think>\nFinal Answer: 5"
            return httpx.Response(200, json={
                "id": "offline", "object": "chat.completion", "created": 0, "model": "offline",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": content, "reasoning_content": "separate-reasoning"}}]})
        with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
            with OpenAI(api_key="offline", base_url="https://example.test/v1", http_client=transport) as client:
                with patch("main.load_settings", side_effect=AssertionError("不應讀取設定")):
                    agent = MiniMaxReActAgent(client=client, model="offline")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = agent.run("算出 2+3")
                self.assertEqual((result.status, result.answer, result.steps), ("success", "5", 2))
                self.assertEqual(requests[1]["messages"][-2]["content"], raw)
                self.assertEqual(requests[1]["messages"][-2]["reasoning_content"], "separate-reasoning")
                self.assertEqual(requests[1]["messages"][-1]["content"], "Observation: 5")
                self.assertNotIn("私有推理", output.getvalue())
                agent.close()
                self.assertFalse(client.is_closed(), "注入的客戶端由呼叫端管理")

    def test_owned_client_is_closed(self):
        client = Mock()
        settings = {"MINIMAX_API_KEY": "test", "MINIMAX_BASE_URL": "https://example.test/v1", "MINIMAX_MODEL": "test"}
        with patch("main.load_settings", return_value=settings), patch("main.OpenAI", return_value=client):
            agent = MiniMaxReActAgent()
            agent.close()
        client.close.assert_called_once()

    def test_injected_client_requires_model(self):
        with self.assertRaises(ValueError):
            MiniMaxReActAgent(client=Mock(), model=" ")

    def test_unclosed_think_block_is_rejected(self):
        agent = MiniMaxReActAgent.__new__(MiniMaxReActAgent)
        self.assertIn("error", agent.parse_output("<think>Final Answer: 非答案"))


if __name__ == "__main__":
    unittest.main()
