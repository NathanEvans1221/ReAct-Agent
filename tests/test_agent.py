import contextlib
import io
import unittest
import tempfile
import json
import os
from pathlib import Path
import httpx
from openai import APIConnectionError, OpenAI
from types import SimpleNamespace
from unittest.mock import patch

from main import MiniMaxReActAgent
import main as app


def response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def scripted_agent(*replies):
    agent = MiniMaxReActAgent.__new__(MiniMaxReActAgent)
    agent._owns_client = False
    pending = iter(replies)
    agent.calls = []
    def create(**kwargs):
        agent.calls.append([dict(message) for message in kwargs["messages"]])
        item = next(pending)
        if isinstance(item, Exception):
            raise item
        return response(item)
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    agent.model = "offline-test"
    agent.tools = {"calculator": agent.tool_calculator, "web_search": agent.tool_web_search}
    agent.close = lambda: None
    return agent


class RetryTests(unittest.TestCase):
    def test_normal_tool_execution_does_not_sleep(self):
        agent = scripted_agent("Thought: 計算\nAction: calculator\nAction Input: 1+2", "Final Answer: 3")
        with patch("time.sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
            result = agent.run("計算")
        self.assertEqual(result.answer, "3")
        sleep.assert_not_called()

    def test_sdk_timeout_and_retry_policy_over_real_http_boundary(self):
        for codes, expected_calls, expected_status in (([500, 200], 2, "success"),
                                                      ([429, 429, 429], 3, "api_error"),
                                                      ([401], 1, "api_error"),
                                                      (["timeout"] * 3, 3, "api_error")):
            with self.subTest(codes=codes):
                requests = []
                pending = iter(codes)
                def handle(request):
                    requests.append(request)
                    code = next(pending)
                    if code == "timeout":
                        raise httpx.ReadTimeout("offline", request=request)
                    if code != 200:
                        return httpx.Response(code, json={"error": {"message": "offline", "type": "test_error"}})
                    return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
                        "model": "offline-test", "choices": [{"index": 0, "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Final Answer: 成功"}}]})
                with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
                    def factory(**kwargs):
                        return OpenAI(**kwargs, http_client=http_client)
                    settings = {"MINIMAX_API_KEY": "offline", "MINIMAX_BASE_URL": "https://example.test/v1", "MINIMAX_MODEL": "offline-test"}
                    with patch("main.load_settings", return_value=settings), patch("main.OpenAI", side_effect=factory), patch("time.sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
                        agent = MiniMaxReActAgent()
                        result = agent.run("測試")
                    self.assertEqual(result.status, expected_status)
                    self.assertEqual(len(requests), expected_calls)
                    self.assertEqual(sleep.call_count, expected_calls - 1)
                    for request in requests:
                        self.assertLessEqual(request.extensions["timeout"]["read"], 30)


class ConfigTests(unittest.TestCase):
    def test_missing_settings_fail_before_client_creation(self):
        valid = {"MINIMAX_API_KEY": "test-key", "MINIMAX_BASE_URL": "https://example.test/v1", "MINIMAX_MODEL": "test-model"}
        for missing in valid:
            env = {key: value for key, value in valid.items() if key != missing}
            with self.subTest(missing=missing), patch.dict(os.environ, env, clear=True), patch("main.load_dotenv"), patch("main.OpenAI") as client:
                with self.assertRaisesRegex(ValueError, missing):
                    MiniMaxReActAgent()
                client.assert_not_called()

    def test_invalid_url_and_placeholder_key_are_rejected(self):
        for url, key in (("not-a-url", "test"), ("http://example.test/v1", "test"),
                         ("https://user:secret@example.test/v1", "test"),
                         ("https://example.test/v1", "你的_MINIMAX_API_KEY")):
            env = {"MINIMAX_API_KEY": key, "MINIMAX_BASE_URL": url, "MINIMAX_MODEL": "test"}
            with self.subTest(url=url), patch.dict(os.environ, env, clear=True), patch("main.load_dotenv"), patch("main.OpenAI"):
                with self.assertRaises(ValueError):
                    MiniMaxReActAgent()

    def test_cli_configuration_failure_is_readable(self):
        with patch.dict(os.environ, {}, clear=True), patch("main.load_dotenv"), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app.main(), 2)
        self.assertIn("MINIMAX_API_KEY", output.getvalue())


class RunTests(unittest.TestCase):
    def run_agent(self, agent, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return agent.run("測試", **kwargs)

    def test_success_returns_answer_and_steps(self):
        agent = scripted_agent("Thought: 計算\nAction: calculator\nAction Input: 2+3", "Final Answer: 5")
        result = self.run_agent(agent)
        self.assertEqual((result.status, result.answer, result.steps), ("success", "5", 2))
        self.assertEqual(agent.calls[1][-1]["content"], "Observation: 5")

    def test_step_limit_has_explicit_result(self):
        agent = scripted_agent("Thought: 計算\nAction: calculator\nAction Input: 2+3")
        result = self.run_agent(agent, max_steps=1)
        self.assertEqual((result.status, result.steps), ("step_limit", 1))
        self.assertIsNone(result.answer)

    def test_format_retries_are_bounded(self):
        agent = scripted_agent("bad", "bad", "bad", "Final Answer: 不應抵達")
        result = self.run_agent(agent)
        self.assertEqual((result.status, result.steps), ("format_error", 3))
        self.assertEqual(len(agent.calls), 3)

    def test_api_failure_does_not_leak_request_details(self):
        agent = scripted_agent(APIConnectionError(message="secret-value", request=httpx.Request("POST", "https://example.test")))
        result = self.run_agent(agent)
        self.assertEqual(result.status, "api_error")
        self.assertNotIn("secret-value", result.error)

    def test_empty_choices_has_explicit_result(self):
        agent = scripted_agent()
        agent.client.chat.completions.create = lambda **kwargs: SimpleNamespace(choices=[])
        self.assertEqual(self.run_agent(agent).status, "response_error")

    def test_unexpected_tool_failure_writes_sanitized_crash(self):
        agent = scripted_agent("Thought: 測試\nAction: broken\nAction Input: secret-input")
        def broken(value):
            raise RuntimeError("secret-value")
        agent.tools["broken"] = broken
        with tempfile.TemporaryDirectory() as directory, patch("main.CRASH_DIR", Path(directory), create=True):
            result = self.run_agent(agent)
            self.assertEqual(result.status, "internal_error")
            reports = list(Path(directory).glob("*.json"))
            self.assertEqual(len(reports), 1)
            report = reports[0].read_text()
            self.assertNotIn("secret-value", report)
            self.assertNotIn("secret-input", report)
            self.assertEqual(json.loads(report)["exception_type"], "RuntimeError")

    def test_cli_failure_returns_nonzero(self):
        entry = getattr(app, "main", None)
        self.assertIsNotNone(entry, "需要可回傳退出碼的 CLI 入口")
        agent = scripted_agent("bad", "bad", "bad")
        with patch("main.MiniMaxReActAgent", return_value=agent), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(entry(), 1)

    def test_unknown_tool_feedback_allows_recovery(self):
        agent = scripted_agent("Thought: 嘗試\nAction: unknown\nAction Input: x", "Final Answer: 無此工具")
        result = self.run_agent(agent)
        self.assertEqual(result.status, "success")
        self.assertIn("不存在", agent.calls[1][-1]["content"])

    def test_repeated_runs_do_not_share_conversation(self):
        agent = scripted_agent("Final Answer: 第一個", "Final Answer: 第二個")
        self.run_agent(agent)
        self.run_agent(agent)
        self.assertEqual(len(agent.calls[1]), 2)

    def test_invalid_run_inputs_do_not_call_model(self):
        agent = scripted_agent()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(agent.run(" ").status, "invalid_input")
            for limit in (0, -1, 51, True, 1.5):
                self.assertEqual(agent.run("test", max_steps=limit).status, "invalid_input")
        self.assertEqual(agent.calls, [])


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.agent = MiniMaxReActAgent.__new__(MiniMaxReActAgent)

    def search(self, query):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.agent.tool_web_search(query)

    def test_unrelated_queries_do_not_return_taiwan_fixture(self):
        for query in ("美國總統是誰", "誰出生於 1959 年", "美國與台灣總統比較"):
            with self.subTest(query=query):
                self.assertNotIn("賴清德", self.search(query))

    def test_demo_query_is_explicitly_historical_and_simulated(self):
        result = self.search("2024年5月20日台灣總統是誰")
        self.assertIn("模擬", result)
        self.assertIn("2024", result)
        self.assertIn("賴清德", result)

    def test_current_queries_are_not_answered_with_old_fixture(self):
        result = self.search("目前台灣總統是誰")
        self.assertNotIn("賴清德", result)
        self.assertIn("即時", result)


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.agent = MiniMaxReActAgent.__new__(MiniMaxReActAgent)

    def test_empty_or_non_text_response_is_rejected(self):
        for content in (None, "", "   ", 12):
            with self.subTest(content=content):
                self.assertIn("error", self.agent.parse_output(content))

    def test_embedded_final_marker_does_not_finish_action(self):
        parsed = self.agent.parse_output(
            "Thought: 不應在此輸出 Final Answer: 標記\nAction: calculator\nAction Input: 1+2")
        self.assertEqual(parsed.get("action"), "calculator")
        self.assertNotIn("final_answer", parsed)

    def test_multiline_input_and_thought_are_preserved(self):
        parsed = self.agent.parse_output(
            "Thought: 第一行\n第二行\nAction: web_search\nAction Input: 第一段\n第二段")
        self.assertEqual(parsed.get("thought"), "第一行\n第二行")
        self.assertEqual(parsed.get("action_input"), "第一段\n第二段")

    def test_ambiguous_or_incomplete_output_is_rejected(self):
        for content in ("Final Answer: ", "Thought: x\nAction: calculator\nAction Input: ",
                        "Thought: x\nAction: calculator\nAction Input: 1\nFinal Answer: 1",
                        "Thought: x\nAction: calculator\nAction: web_search\nAction Input: x",
                        "前言\nFinal Answer: 答案"):
            with self.subTest(content=content):
                self.assertIn("error", self.agent.parse_output(content))

    def test_multiline_final_answer_is_preserved(self):
        self.assertEqual(self.agent.parse_output("Final Answer: 第一行\n第二行"),
                         {"final_answer": "第一行\n第二行"})

    def test_invalid_format_can_be_repaired(self):
        replies = iter(["格式不正確", "Final Answer: 修正成功"])
        def create(**kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))])
        self.agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        self.agent.model = "offline-test"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.agent.run("測試")
        self.assertIn("修正成功", output.getvalue())


class CalculatorTests(unittest.TestCase):
    def setUp(self):
        self.agent = MiniMaxReActAgent.__new__(MiniMaxReActAgent)

    def calculate(self, expression):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.agent.tool_calculator(expression)

    def test_arithmetic_preserves_decimal_precision(self):
        for expression, expected in (("2030 - 1959", "71"), ("0.1 + 0.2", "0.3"),
                                     ("-(3 + 2) * 4 / 2", "-10")):
            with self.subTest(expression=expression):
                self.assertEqual(self.calculate(expression), expected)

    def test_invalid_input_is_rejected_not_rewritten(self):
        for expression in ("1e3 + 2", "2 apples + 3", "2**3", "7//2", "1/0", "", "True + 1"):
            with self.subTest(expression=expression):
                self.assertIn("錯誤", self.calculate(expression))

    def test_resource_limits(self):
        for expression in ("1" * 257, "1000000000000 * 2", "(" * 20 + "1" + ")" * 20,
                           "+".join(["1"] * 40)):
            with self.subTest(expression=expression[:30]):
                self.assertIn("錯誤", self.calculate(expression))


if __name__ == "__main__":
    unittest.main()
