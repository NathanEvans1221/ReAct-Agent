import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main as app


class CliTests(unittest.TestCase):
    def test_task_and_step_limit_are_forwarded(self):
        agent = Mock()
        agent.run.return_value = SimpleNamespace(status="success", answer="答案", error=None)
        with patch("main.MiniMaxReActAgent", return_value=agent), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(["--task", "自訂任務", "--max-steps", "7"]), 0)
        agent.run.assert_called_once_with("自訂任務", max_steps=7, verbose=False)
        agent.close.assert_called_once()

    def test_verbose_flag_enables_execution_details(self):
        agent = Mock()
        agent.run.return_value = SimpleNamespace(status="success", answer="答案", error=None)
        with patch("main.MiniMaxReActAgent", return_value=agent), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(["--task", "任務", "--verbose"]), 0)
        agent.run.assert_called_once_with("任務", max_steps=5, verbose=True)

    def test_invalid_step_limit_returns_usage_error_without_client(self):
        with patch("main.MiniMaxReActAgent") as constructor, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(app.main(["--max-steps", "0"]), 2)
        constructor.assert_not_called()

    def test_help_does_not_require_credentials(self):
        with patch("main.MiniMaxReActAgent") as constructor, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app.main(["--help"]), 0)
        constructor.assert_not_called()
        self.assertIn("--max-steps", output.getvalue())


if __name__ == "__main__":
    unittest.main()
