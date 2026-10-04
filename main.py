import ast
import argparse
import json
import operator
import os
import re
import sys
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from typing import Dict, Any
from decimal import Decimal, DecimalException, localcontext
from openai import APIError, OpenAI
from dotenv import load_dotenv

CRASH_DIR = Path(__file__).resolve().parent / "logs" / "crashes"
DEMO_QUERY = "依據模擬資料，找出2024年5月20日就任的台灣總統，並計算他在2030年生日當天滿幾歲。"
DEFAULT_MAX_INPUT_CHARS = 60000
MAX_OBSERVATION_CHARS = 4000
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])")


def terminal_text(value: object) -> str:
    """清除終端控制序列，並將其他控制字元替換為可見字元。"""
    text = ANSI_ESCAPE.sub("", str(value))
    return "".join(
        char if char in "\n\t" or not (ord(char) < 32 or 0x7F <= ord(char) <= 0x9F)
        else "�"
        for char in text
    )


def limit_observation(value: object) -> tuple[str, bool, int]:
    """限制工具結果長度並標示截斷。"""
    text = str(value)
    if len(text) <= MAX_OBSERVATION_CHARS:
        return text, False, len(text)
    marker = f"\n…[工具輸出已截斷；原始長度 {len(text)} 字元]"
    return text[:MAX_OBSERVATION_CHARS - len(marker)] + marker, True, len(text)


@dataclass(frozen=True)
class RunResult:
    status: str
    steps: int
    answer: str | None = None
    error: str | None = None


def unexpected_error(exc: Exception, step: int) -> RunResult:
    """保存所有堆疊位置及安全快照，不記錄例外訊息、原始碼或使用者資料。"""
    report = {
        "message": "Agent 因未預期錯誤停止執行",
        "exception_type": type(exc).__name__,
        "snapshot": {"step": step},
        "traceback": [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                      for frame in traceback.extract_tb(exc.__traceback__)]
    }
    try:
        CRASH_DIR.mkdir(parents=True, exist_ok=True)
        path = CRASH_DIR / f"{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        error = f"未預期錯誤（{type(exc).__name__}）；診斷報告：{path}"
    except OSError:
        error = f"未預期錯誤（{type(exc).__name__}）；無法寫入診斷報告。"
    return RunResult("internal_error", step, error=error)


def load_settings() -> dict[str, str]:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    settings = {}
    for name in ("MINIMAX_API_KEY", "MINIMAX_BASE_URL", "MINIMAX_MODEL"):
        value = os.getenv(name, "").strip()
        if not value or value == "你的_MINIMAX_API_KEY":
            raise ValueError(f"請在 .env 或環境變數設定有效的 {name}。")
        settings[name] = value
    url = urlsplit(settings["MINIMAX_BASE_URL"])
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or any(char.isspace() for char in settings["MINIMAX_BASE_URL"])):
        raise ValueError("MINIMAX_BASE_URL 必須為不含帳密、查詢參數或片段的 HTTPS 端點。")
    return settings

# ═══════════════════════════════════════════
# 💡 概念：ReAct 代理與 MiniMax API 整合
# 說明：這是一個具備正規解析功能的實例。
# 為何使用：使用 Regex 解析 Thought/Action 是實作 ReAct 框架最核心的技術。
# ═══════════════════════════════════════════

class MiniMaxReActAgent:
    def __init__(self, client=None, model: str | None = None):
        self._owns_client = client is None
        if client is None:
            settings = load_settings()
        # ═══════════════════════════════════════════
        # 💡 標準用法說明：OpenAI SDK v1.x +
        # 這裡採用了現代化的 Client 實例化方式，相對於舊版的全局設定更具隔離性。
        # 由於 MiniMax 支援 OpenAI 兼容協議，我們只需替換 base_url 即可。
        # ═══════════════════════════════════════════
            self.client = OpenAI(
                api_key=settings["MINIMAX_API_KEY"],
                base_url=settings["MINIMAX_BASE_URL"],
                timeout=30.0,
                max_retries=2
            )
            self.model = settings["MINIMAX_MODEL"]
        else:
            if not isinstance(model, str) or not model.strip():
                raise ValueError("注入客戶端時必須提供非空模型名稱。")
            self.client = client
            self.model = model.strip()

        # 定義可用工具
        self.tools = {
            "web_search": self.tool_web_search,
            "calculator": self.tool_calculator
        }

    def close(self) -> None:
        """釋放 Agent 建立的客戶端；注入的客戶端由建立者管理。"""
        if self._owns_client:
            self.client.close()

    def tool_web_search(self, query: str) -> str:
        """只提供明確列出的歷史示範資料，不進行網路搜尋。"""
        knowledge = {
            "2024年5月20日台灣總統是誰": "2024年5月20日就任的台灣總統為賴清德。",
            "賴清德出生日期": "賴清德出生日期為1959年10月6日。",
            "賴清德出生年份": "賴清德出生於1959年。"
        }
        normalized = re.sub(r"\s+", "", query).rstrip("?？。")
        if normalized in knowledge:
            return f"[模擬資料，非即時搜尋] {knowledge[normalized]}"
        return "[模擬搜尋] 沒有符合的示範資料；本工具無法查詢即時資訊，請勿推測答案。"

    def tool_calculator(self, expression: str) -> str:
        """以受限 AST 計算十進位四則運算，不執行任意 Python。"""
        try:
            if not isinstance(expression, str) or not 0 < len(expression) <= 256:
                raise ValueError("算式需為 1 至 256 個字元")
            expression = expression.strip()
            if not re.fullmatch(r"[0-9+\-*/(). \t]+", expression):
                raise ValueError("只支援數字、小數、括號及四則運算")
            nesting = 0
            for char in expression:
                nesting += (char == "(") - (char == ")")
                if nesting > 16:
                    raise ValueError("括號深度超過 16 層")
            tree = ast.parse(expression, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 64:
                raise ValueError("算式過於複雜")
            operations = {ast.Add: operator.add, ast.Sub: operator.sub,
                          ast.Mult: operator.mul, ast.Div: operator.truediv}

            def evaluate(node, depth=0):
                if depth > 16:
                    raise ValueError("運算深度超過 16 層")
                if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                    value = Decimal(ast.get_source_segment(expression, node))
                elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                    value = evaluate(node.operand, depth + 1)
                    if isinstance(node.op, ast.USub):
                        value = -value
                elif isinstance(node, ast.BinOp) and type(node.op) in operations:
                    value = operations[type(node.op)](
                        evaluate(node.left, depth + 1), evaluate(node.right, depth + 1))
                else:
                    raise ValueError("不支援的運算")
                if not value.is_finite() or abs(value) > Decimal("1e12"):
                    raise ValueError("數值或中間結果超過 10^12")
                return value

            with localcontext() as context:
                context.prec = 28
                result = evaluate(tree.body)
                return "0" if result == 0 else format(result.normalize(), "f")
        except (ValueError, SyntaxError, DecimalException, OverflowError) as exc:
            return f"計算錯誤：{exc}"

    def get_system_prompt(self):
        return """你是一個聰明的 ReAct Agent。你必須嚴格遵守以下輸出格式。

你可以使用的工具有：
- web_search: 模擬搜尋，僅支援「2024年5月20日台灣總統是誰」、「賴清德出生日期」、「賴清德出生年份」。不提供即時資訊，回答時必須標示依據模擬資料。
- calculator: 用於精確的數學計算。

輸出格式如下：
Thought: [你的思考過程]
Action: [工具名稱]
Action Input: [工具輸入參數]

當你獲得足夠資訊時，直接輸出最終答案：
Final Answer: [最終總結答案]

注意：每一輪對話只能輸出一個 Thought 和一個 Action。"""

    def parse_output(self, text: str) -> Dict[str, Any]:
        """驗證欄位順序及唯一性，保留多行內容。"""
        error = {"error": "無法解析輸出格式", "raw": text}
        if not isinstance(text, str) or not text.strip():
            return error
        text = text.strip()
        if "<think>" in text:
            if not re.match(r"\A<think>.*?</think>\s*", text, re.S):
                return error
            text = re.sub(r"\A<think>.*?</think>\s*", "", text, count=1, flags=re.S)
        if "</think>" in text:
            return error
        fields = list(re.finditer(r"^(Thought|Action|Action Input|Final Answer):[ \t]*", text, re.M))
        names = [field.group(1) for field in fields]
        if not fields or fields[0].start() != 0:
            return error
        if names not in (["Final Answer"], ["Thought", "Action", "Action Input"]):
            return error
        values = [text[field.end():fields[i + 1].start() if i + 1 < len(fields) else len(text)].strip()
                  for i, field in enumerate(fields)]
        if not all(values):
            return error
        if names == ["Final Answer"]:
            return {"final_answer": values[0]}
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", values[1]):
            return error
        return dict(zip(("thought", "action", "action_input"), values))

    def run(
        self,
        user_query: str,
        max_steps: int = 5,
        verbose: bool = False,
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    ) -> RunResult:
        if not isinstance(user_query, str) or not user_query.strip():
            return RunResult("invalid_input", 0, error="任務不可為空。")
        if type(max_steps) is not int or not 1 <= max_steps <= 50:
            return RunResult("invalid_input", 0, error="最大步數需為 1 至 50 的整數。")
        if type(max_input_chars) is not int or max_input_chars < 1:
            return RunResult("invalid_input", 0, error="總輸入字元預算需為正整數。")
        if verbose:
            print(f"🚀 啟動任務: {terminal_text(user_query)}\n")
        
        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            {"role": "user", "content": user_query}
        ]

        format_errors = 0
        total_input_chars = 0
        # 格式修正也計入最大步數，避免無限重試。
        for step in range(1, max_steps + 1):
            request_chars = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))
            if total_input_chars + request_chars > max_input_chars:
                return RunResult(
                    "budget_exhausted",
                    step - 1,
                    error=(f"總輸入字元預算已耗盡（已用 {total_input_chars}/{max_input_chars} 字元；"
                           f"下一次請求需要 {request_chars} 字元）。"),
                )
            total_input_chars += request_chars
            print(f"--- 步驟 {step} ---")
            
            # 向 MiniMax API 發送請求
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1 # 設低一點讓輸出更穩定遵循格式
                )
            except APIError as exc:
                return RunResult("api_error", step, error=f"模型 API 請求失敗（{type(exc).__name__}）。請檢查連線、設定及額度。")
            except Exception as exc:
                return unexpected_error(exc, step)
            if not getattr(response, "choices", None):
                return RunResult("response_error", step, error="模型未回傳任何候選回覆。")

            response_message = response.choices[0].message
            raw_content = getattr(response_message, "content", None)
            parsed = self.parse_output(raw_content)

            if "error" in parsed:
                print("❌ 格式錯誤，要求模型修正。")
                format_errors += 1
                if format_errors > 2:
                    return RunResult("format_error", step, error="模型連續或累計三次輸出無效格式。")
                if isinstance(raw_content, str) and raw_content.strip():
                    messages.append(self._assistant_message(response_message, raw_content))
                messages.append({"role": "user", "content":
                                 "輸出格式錯誤。請僅輸出 Thought、Action、Action Input 三個非空欄位，"
                                 "或單獨輸出非空的 Final Answer；每個欄位名稱必須獨占行首且不可重複。"})
                continue

            if "final_answer" in parsed:
                answer = terminal_text(parsed["final_answer"])
                print(f"\n✅ 任務完成！\nFinal Answer: {answer}")
                return RunResult("success", step, answer=answer)

            # 解析成功，處理工具 call
            thought = parsed["thought"]
            action = parsed["action"]
            action_input = parsed["action_input"]

            if verbose:
                print(f"🤔 Thought: {terminal_text(thought)}")
                print(f"⚡ Action: {terminal_text(action)}('{terminal_text(action_input)}')")

            # 執行工具
            if action in self.tools:
                try:
                    observation = self.tools[action](action_input)
                except Exception as exc:
                    return unexpected_error(exc, step)
            else:
                observation = f"錯誤：工具 {action} 不存在。"

            observation, was_truncated, original_observation_chars = limit_observation(observation)
            if was_truncated:
                print(f"⚠️ 工具輸出已截斷（原始 {original_observation_chars} 字元，上限 {MAX_OBSERVATION_CHARS} 字元）。")
            
            if verbose:
                print(f"👁️ Observation: {terminal_text(observation)}\n")

            # 將 Observation 加回對話紀錄，進行下一輪思考
            messages.append(self._assistant_message(response_message, raw_content))
            messages.append({"role": "user", "content": f"Observation: {observation}"})
            
        return RunResult("step_limit", max_steps, error="已達最大步數，尚未取得最終答案。")

    @staticmethod
    def _assistant_message(response_message, content: str) -> dict[str, Any]:
        if hasattr(response_message, "model_dump"):
            return response_message.model_dump(exclude_none=True)
        result = {"role": "assistant", "content": content}
        reasoning = getattr(response_message, "reasoning_content", None)
        if reasoning is not None:
            result["reasoning_content"] = reasoning
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MiniMax ReAct Agent 教學範例")
    parser.add_argument("--task", default=DEMO_QUERY, help="要交給 Agent 的任務")
    parser.add_argument("--max-steps", type=int, default=5, help="模型步數上限（1 至 50，預設 5）")
    parser.add_argument("--max-input-chars", type=int, default=DEFAULT_MAX_INPUT_CHARS,
                        help=f"整次任務的模型輸入字元預算（預設 {DEFAULT_MAX_INPUT_CHARS}）")
    parser.add_argument("--verbose", action="store_true", help="顯示任務與模型執行細節")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if not 1 <= args.max_steps <= 50:
        parser.print_usage(sys.stderr)
        print("main.py: error: --max-steps 必須介於 1 至 50", file=sys.stderr)
        return 2
    if args.max_input_chars < 1:
        parser.print_usage(sys.stderr)
        print("main.py: error: --max-input-chars 必須為正整數", file=sys.stderr)
        return 2
    if not args.task.strip():
        parser.print_usage(sys.stderr)
        print("main.py: error: --task 不可為空", file=sys.stderr)
        return 2
    try:
        agent = MiniMaxReActAgent()
    except ValueError as exc:
        print(f"❌ 設定錯誤：{exc}")
        return 2
    try:
        result = agent.run(args.task, max_steps=args.max_steps, verbose=args.verbose,
                           max_input_chars=args.max_input_chars)
        if result.status != "success":
            print(f"❌ {result.status}: {result.error}")
            return 1
        return 0
    finally:
        agent.close()


if __name__ == "__main__":
    raise SystemExit(main())
