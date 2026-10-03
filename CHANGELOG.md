# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- 啟動前驗證金鑰、HTTPS 端點與模型；移除舊模型回退，統一官方模型拼字及 Python 版本說明。
- 主循環回傳結構化結果及步數，區分 API／格式／回應錯誤與步數耗盡；CLI 失敗回傳非零退出碼，未預期錯誤保存去敏診斷報告。
- 解析器驗證欄位順序、唯一性與非空值，保留多行內容；格式錯誤最多修正兩次且計入步數。
- 計算器以受限 AST 與 Decimal 取代 eval，拒絕變造輸入、非四則運算及超限算式。
- 模擬搜尋改為明確查詢白名單，拒絕不相關及即時查詢；提示詞與示範任務明確標示資料限制。

### Tests
- 新增離線搜尋回歸測試與 `bash scripts/verify.sh` 驗證入口。

### Added
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


