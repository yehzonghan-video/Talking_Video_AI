# Talking_Video_AI｜口播企劃室

Streamlit 口播短影音工具。第一階段提供 **選 ABC 分類 → 標題 → 逐字稿 → 對話修改 → 儲存腳本**；第二階段新增 **選已存腳本 → 上傳影片 → 聲學辨識 → 比對與粗剪建議 → 人工確認 → MP4**。所有操作介面使用繁體中文。

第二階段的安裝、架構、逐步操作與驗收流程見 **[影片粗剪使用說明](docs/VIDEO_PHASE2.md)**，驗證結果見 **[第二階段測試紀錄](docs/VIDEO_TEST_RESULTS.md)**。

## 已完成

- 動態讀取現有分類的名稱、說明與關鍵字，10 × 15 × 12 = 1,800 組。原始根目錄 `categories.json` 保持不變。
- 手動、完全隨機、固定任意維度的條件隨機。優先未使用組合，條件用盡需明確勾選重用。三個維度固定直接採用。只有正式儲存才標記使用；刪除腳本仍保留歷史使用紀錄。
- Gemini 一次評估選題合理性並產生五個不同標題。不合理時提供1至3個可選替代組合，也可繼續原選題。
- 30／45／60 秒逐字稿，預設45秒，依可調語速估算字數與時長。
- 多輪自由對話、六種快捷修改，完整新版預覽、確認套用、取消、手動編輯與版本恢復。未要求修改部分提示 AI 保留；恢復會追加版本。
- 腳本 UUID 與組合 ID 分開，同組合可存多份腳本。標題搜尋、ABC／狀態篩選、開啟、刪除確認。
- TXT、單份或全部腳本 JSON 匯出；完整驗證後合併匯入，重複 ID 保留現有資料，整批交易避免半套恢復。
- 本機 SQLite 交易儲存、跨視窗腳本衝突檢查、草稿暫存、草稿 JSON 下載與恢復。
- 無 API 金鑰時仍可手動編輯與管理；API／格式錯誤保留現有內容，不自動重複呼叫。

## 安裝與啟動

需要 Python 3.11 以上，建議3.12。Windows 可雙擊 **`開啟系統.bat`**，首次啟動會建立環境並安裝套件。需有網路下載依賴。已安裝環境會直接啟動。

也可用 PowerShell：

```powershell
cd D:\Talking_Video_AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

開啟瀏覽器 `http://localhost:8501`。關閉啟動視窗或按 Ctrl+C 停止服務。

`requirements.txt` 固定主要套件版本；`requirements-lock.txt` 記錄本次驗證環境的完整依賴，可用 `pip install -r requirements-lock.txt` 重建相同版本。

## Gemini 設定

複製 `.streamlit/secrets.toml.example` 為 `.streamlit/secrets.toml`，填入：

```toml
GEMINI_API_KEY = "你的金鑰"
GEMINI_MODEL = "gemini-3.5-flash"
```

或在啟動 Streamlit 的 PowerShell 設定環境變數：

```powershell
$env:GEMINI_API_KEY = "你的金鑰"
$env:GEMINI_MODEL = "gemini-3.5-flash"
```

同名設定以 Secrets 優先；也支援 `GOOGLE_API_KEY`。模型可隨帳號可用模型調整。金鑰只在後端使用；不要放在分類、Prompt、Git 或匯出檔。`.streamlit/secrets.toml`、`.env`、本機資料均已忽略。

AI 使用 Google 官方 `google-genai` SDK、JSON Schema 與 Pydantic 雙層格式驗證，60秒請求逾時。格式錯誤不自動重試，讓使用者決定是否再生成，避免意外消耗額度。參考：[Google Gen AI SDK](https://googleapis.github.io/python-genai/)、[模型目錄](https://ai.google.dev/gemini-api/docs/models)。

## 日常操作

1. 「AI 選題」選擇／抽取並按「採用這個選題」。生成標題，選擇後按「採用標題」。
2. 「腳本編輯」可改標題，選時長後生成逐字稿。也可直接填入手寫稿。
3. 用聊天或快捷按鈕提出修改。確認完整新版後套用；取消時原稿維持。若提案後手動改稿，系統拒絕套用過期提案，請取消後重新修改。
4. 按「儲存腳本」才成為正式腳本並記錄選題已使用。狀態調整後也需要儲存。
5. 「腳本資料庫」可開啟舊腳本，再切到編輯頁。最近20份草稿可在側欄取回。
6. 定期下載全部 JSON 備份。換機或重新部署後在資料庫頁上傳、查看驗證摘要並確認恢復。

欄位離開焦點／按其他按鈕時會把草稿同步到目前主機。重新整理會根據網址中的草稿識別碼恢復；在失焦前重新整理仍可能遺失尚未送出的輸入。暫存不會標記組合已使用。開啟其他腳本與新建選題會保留舊草稿；未儲存草稿需另外下載草稿 JSON，恢復時會建立獨立腳本以免覆蓋原腳本。

## 儲存與部署限制

- 預設 `data/talking_video.db`，可用 `DATA_PATH` 指定位置。SQLite 讓正式腳本與使用紀錄在同一交易更新，並以 revision 防止兩個視窗覆寫正式腳本。請勿在程式執行時直接修改資料庫。
- **Streamlit Community Cloud 本機磁碟不保證永久保存。** 重啟／重新部署可能遺失，介面已持續顯示提示；JSON 下載到使用者自己的裝置才是可攜備份。
- 第一階段為可信任的單人／內部環境，未提供登入、租戶隔離。草稿網址不是身分驗證；不要公開服務或分享草稿網址。多人同時編輯同一草稿網址的暫存採最後寫入，正式腳本有衝突檢查。
- JSON 包含標題、全文、版本與對話，可能含公司資訊，請自行妥善保存。
- 尚未串接 Supabase 或進行雲端部署。未設定金鑰時不會產生真實 AI 內容。
- AI 格式驗證不能保證事實／工程內容正確，需總監確認；秒數為估算。
- 匯入限制20 MB，已存在的腳本 ID 一律略過，不以舊備份覆蓋新版。欲恢復被刪除腳本可從先前完整備份匯入。

## 目錄與模組介面

```text
Talking_Video_AI/
├── app.py                         # 啟動、導覽、錯誤提示
├── ui/                            # Streamlit 頁面、設定與畫面狀態
│   ├── topics.py / editor.py / library.py
│   └── state.py / settings.py
├── core/
│   ├── topics/                    # Catalog、有效組合、隨機選取
│   ├── ai/                        # Provider、標題、初稿與對話
│   ├── storage/                   # 資料模型、Repository、SQLite、備份
│   └── workflow.py                # 提案／確認／取消／恢復，純邏輯
├── industries/interior_design/
│   └── prompt_config.json         # 產業、口吻、語速與內容限制
├── categories.json                # 使用者原始分類，唯讀
├── data/                          # 本機資料，禁止提交
├── tests/                         # 模擬 AI、交易與 Streamlit 流程測試
├── .streamlit/                    # 主題與 Secrets 範例
├── requirements.txt / requirements-dev.txt
├── Start.ps1 / 開啟系統.bat
└── README.md
```

- `Catalog(path)` → `validate(selection)`、`context(selection)`、`combo_id(selection)`。分類結構使用原檔的 `business_categories`、`target_audiences`、`problem_angles`。
- `choose(catalog, used_ids, fixed, allow_reuse)` → 有效 `{a,b,c}`，耗盡拋出可顯示訊息。
- `Provider.generate(instruction, payload, schema)` → 已驗證模型。只有 `GeminiProvider` 依賴 Gemini SDK；標題／逐字稿／對話接收一般分類內容與產業設定，不依賴特定分類檔。
- `workflow.propose/accept/cancel/restore` 操作 `Draft`；版本是完整標題、稿件與時長快照，不會刪除後續版本。
- `Repository` 定義儲存契約；`SQLiteRepository` 為目前實作，日後可新增遠端實作。匯出／驗證與 UI 分離，匯入經驗證後呼叫後端的 `merge` 交易介面，替換後端不需改選題、AI 或編輯邏輯。
- `INDUSTRY_DIR` 可指定另一個產業資料夾，內含 `categories.json` 與 `prompt_config.json`。預設優先該產業目錄的分類，否則使用根目錄原檔。新增產業只需設定資料，不應改 AI 核心。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

以模擬 AI 驗證選題、時長參數、連續修改、預覽／確認／取消／恢復、版本、重複組合多稿、備份恢復、交易並行與錯誤保留。Streamlit AppTest 驗證完整操作流程、缺金鑰手動儲存、異常回應與重新整理恢復。測試使用獨立暫存資料庫，不消耗 Gemini 額度。真實 Gemini 端到端呼叫需要設定有效金鑰後另行驗收。

本次實測：**41 項通過**（2026-10-27），詳見 `TEST_RESULTS.md`。已在實際瀏覽器確認桌面頁面、缺金鑰提示、手動編輯與重新整理恢復，並檢查390px手機版畫面。另以不含專案資料的固定訊息確認 Gemini 3.5 Flash 連線成功；完整內容生成尚待人工驗收。

## 擴充範圍

第二階段已加入影片上傳、本機辨識、粗剪與MP4輸出。後續應先以總監實拍影片驗收辨識及剪輯點，再規劃登入、持久儲存與工作排程。**目前未實作提詞器、直接錄影、字幕、音樂、特效或 B-roll。**
