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


if __name__ == "__main__":
    unittest.main()
