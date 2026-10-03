import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import MiniMaxReActAgent


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
