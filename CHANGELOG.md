# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- 為每次 Agent 執行加入可調整的累計輸入字元預算；限制工具 Observation 為 4,000 字元並明確提示截斷。
- 預設隱藏任務、模型 Thought 與工具輸入；新增 `--verbose` 選項，所有動態終端文字先清理控制序列。
- Agent 支援注入模型客戶端、明確管理客戶端生命週期，並保留 MiniMax 推理欄位及過濾 `<think>` 標籤後解析。
- 移除每輪固定等待，明確設定 SDK 30 秒逾時及最多兩次重試；以離線 HTTP 測試確認限流、伺服器錯誤、認證失敗及逾時行為。
- 啟動前驗證金鑰、HTTPS 端點與模型；移除舊模型回退，統一官方模型拼字及 Python 版本說明。
- 主循環回傳結構化結果及步數，區分 API／格式／回應錯誤與步數耗盡；CLI 失敗回傳非零退出碼，未預期錯誤保存去敏診斷報告。
- 解析器驗證欄位順序、唯一性與非空值，保留多行內容；格式錯誤最多修正兩次且計入步數。
- 計算器以受限 AST 與 Decimal 取代 eval，拒絕變造輸入、非四則運算及超限算式。
- 模擬搜尋改為明確查詢白名單，拒絕不相關及即時查詢；提示詞與示範任務明確標示資料限制。

### Tests
- 加入搜尋、計算器、解析器、API 重試、MiniMax 回覆格式、CLI 與 Python 版本矩陣的離線回歸測試。

### Added
- 加入 `--task`、`--max-steps`、`--help` CLI 參數、鎖定版依賴、Python 3.10–3.12 離線 CI，並更新與實際工具能力一致的 README。
- 建立 `main.py`：實作串接 MiniMax 國際版 API 的 ReAct Agent 核心循環與 Regex 解析器。
- 建立 `requirements.txt`：包含 `openai`, `python-dotenv` 等必要依賴。
- 建立 `.env.example`：提供環境變數配置範例。
- 更新 `README.md`：
    - 加入 ReAct Agent 核心概念說明。
    - 加入 Mermaid 系統流程圖。
    - 加入 WSL 環境下的快速開始指南。
    - 加入常見問題（Troubleshooting）章節，記錄模型命名與虛擬環境等坑點。
    - 加入實機執行輸出範例，提升對 ReAct 流程的可理解性。
    - 加入「技術選型：OpenAI SDK 介紹」章節，說明其功能與使用方法。
- 更新 `main.py`：加入 OpenAI SDK 標準用法的教學註解。


