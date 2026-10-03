import contextlib
import io
import unittest

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
