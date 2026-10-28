# Talking_Video_AI｜口播企劃室

Streamlit 口播短影音工具。第一階段提供 **選 ABC 分類 → 標題 → 逐字稿 → 對話修改 → 儲存腳本**；第二階段新增 **選已存腳本 → 上傳影片 → 聲學辨識 → 比對與粗剪建議 → 人工確認 → MP4**。所有操作介面使用繁體中文。

第二階段的安裝、架構、逐步操作與驗收流程見 **[影片粗剪使用說明](docs/VIDEO_PHASE2.md)**，驗證結果見 **[第二階段測試紀錄](docs/VIDEO_TEST_RESULTS.md)**。

第三階段新增 **自動繁體字幕 → 修字與分段 → 基本／黃色重點樣式 → 剪輯後時間同步 → SRT／帶字幕MP4**。使用方法、時間映射與Cloud字型設定見 **[自動字幕使用說明](docs/SUBTITLES_PHASE3.md)**。
第三階段完整回歸 **222項通過**（含原189項及新增33項），實際字幕燒錄與測試範圍見 **[字幕測試紀錄](docs/SUBTITLE_TEST_RESULTS.md)**。

在「AI影片粗剪」完成分析並保存剪輯後，到「五、自動字幕」按「由現有辨識產生字幕」，修正文字／時間並保存，即可預覽及下載SRT。開啟字幕後輸出會燒錄；關閉仍可輸出原有無字幕影片。字幕使用實際辨識、不呼叫Gemini，修改剪輯後依原片錨點重新映射；切到人工修字或詞語時需再次確認。

Cloud部署需安裝更新後的 `requirements.txt` 與 `packages.txt`（包括 `fonts-noto-cjk`、`fontconfig`），才有繁體字型與字幕功能。本機「安裝影片功能.bat」會確認FFmpeg支援libass。字幕、影片與逐字稿不提交GitHub；請定期下載剪輯JSON、原片及成品備份。

## 已完成

- 動態讀取現有分類的名稱、說明與關鍵字，10 × 15 × 12 = 1,800 組。原始根目錄 `categories.json` 保持不變。
- 手動、完全隨機、固定任意維度的條件隨機。優先未使用組合，條件用盡需明確勾選重用。三個維度固定直接採用。只有正式儲存才標記使用；刪除腳本仍保留歷史使用紀錄。
- Gemini 先探索生活情境、使用需求與知識價值，將組合分成「適合／可延伸／不建議」。前兩種產生1至5個不同具體選題的標題，每個標題附切入點說明，不強制湊滿五個。只有找不到可信且有價值的切入點時才不建議，並提供1至3個替代組合；仍可手動填寫標題繼續。
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
GEMINI_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
GEMINI_MAX_RETRIES = 2
```

或在啟動 Streamlit 的 PowerShell 設定環境變數：

```powershell
$env:GEMINI_API_KEY = "你的金鑰"
$env:GEMINI_MODELS = '["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]'
$env:GEMINI_MAX_RETRIES = '2'
```

同名設定以 Secrets 優先；也支援 `GOOGLE_API_KEY`。`GEMINI_MODELS` 的順序就是完整的管理者允許清單，支援TOML陣列、環境變數JSON或逗號分隔，最多5個且重複名稱只保留第一次。設定此清單後不會再附加任何模型；未設定時沿用 `GEMINI_MODEL` 作為主要模型（預設3.6 Flash），備用預設為3.5 Flash-Lite與3.1 Flash-Lite。不會自動探索清單外或另行切換至未允許的付費模型，也不會變更帳號計費設定。

金鑰只在後端使用；不要放在分類、Prompt、Git 或匯出檔。`.streamlit/secrets.toml`、`.env`、本機資料均已忽略。模型及額度是否可用，仍依帳號權限與計費方案決定。

AI 使用 Google 官方 `google-genai` SDK、JSON Schema 與 Pydantic 雙層格式驗證。503會先在同模型有限次數指數退避，再切換清單中的下一模型；格式錯誤不會視為成功，也不在同模型重複湊答案，只嘗試下一個允許模型。切換時Prompt、ABC、原稿、最新修改要求與歷史對話完全沿用，只有實際模型及剩餘請求時限改變。

429採保守規則：以QuotaFailure、RetryInfo、錯誤原因及Retry-After區分；明確短期速率限制只在同模型有限重試，耗盡後停止，不切換模型。明確每日／帳戶額度耗盡或無法辨識的429立即停止，不輪流消耗其他模型。400／401／403等設定、驗證與權限錯誤立即停止；404不重試原模型，可嘗試下一個已允許模型。

已檢查本機SDK 2.29.0：`retry_args(None)`不重試，而啟用未指定attempts的`HttpRetryOptions`會預設最多5次嘗試。Provider明確將SDK內層設為`attempts=1`，重試只由本專案控制，並以真實SDK加模擬HTTP驗證實際請求次數。

可選參數（Secrets或環境變數）：`GEMINI_MAX_RETRIES=2`（每模型額外重試0～3次）、`GEMINI_RETRY_INITIAL_DELAY=1.0`、`GEMINI_RETRY_MAX_DELAY=8.0`（上限30秒）、`GEMINI_REQUEST_TIMEOUT=60.0`（1～60秒）、`GEMINI_MAX_ELAPSED=180.0`（整次1～300秒）。退避包含少量隨機延遲；服務要求等待時間若超過自動等待上限，會停止並提示稍後重試。預設3模型遇到持續503最多9次API請求，仍受整次時限限制。

成功後側欄顯示最近一次實際使用的模型。只按生成／修改／分析按鈕時呼叫API，顯示模型資訊與一般頁面重跑不會自動重新生成，也不在Provider內儲存或覆蓋腳本。

側欄「AI 模型」預設為「自動備援（預設）」，維持管理者設定的順序。也可手動選擇允許清單中的任一模型優先使用，其餘備援仍按原設定順序排列；取消「失敗時切換其他備援模型」便只使用指定模型。畫面會顯示本次順序。選擇只套用於本次瀏覽，不改動全域設定、原稿或對話；重新整理後回到預設自動模式，切換本身不發送API請求。

呼叫紀錄保存於目前資料庫同層的 `logs/gemini_calls.jsonl`，每份約1 MB、保留3份輪替備份。只記錄時間、隨機請求識別碼、允許模型名稱、嘗試次序、成功／失敗、固定錯誤類型、HTTP狀態及耗時；不記錄金鑰、Prompt、ABC內容、稿件、對話、回應全文或原始例外。不要開啟第三方SDK／HTTP的敏感內容除錯日誌。

參考：[Google Gen AI SDK](https://googleapis.github.io/python-genai/)、[API錯誤說明](https://ai.google.dev/gemini-api/docs/api-errors)、[模型目錄](https://ai.google.dev/gemini-api/docs/models)。

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

Gemini備援、手動選擇及影片400修正後實測：**189 項全部通過，其中70項為模型備援、配額、設定、UI及語意請求整合測試**（2026-10-27）。涵蓋503退避及兩層備援、全部失敗、429分鐘／每日／不明配額、權限與設定錯誤、格式驗證、上下文保留、頁面重跑不重送、單一腳本保存、手動優先／固定模型、允許清單變更回復預設、雲端更新仍快取舊設定／Provider時啟動與切換、400分類與敏感資訊遮蔽，以及安全輪替日誌。另以真實SDK搭配模擬HTTP確認不會疊加隱藏重試。影片語意比對400的根因與驗證見 [診斷紀錄](docs/VIDEO_400_DIAGNOSIS.md)。

ABC標題測試同時涵蓋「適合／可延伸」各1～5個標題、不建議與替代組合、重複選題及矛盾回應拒絕、重新生成保留ABC與手改標題、舊草稿相容，以及1個標題也能完成逐字稿／對話／儲存流程。

第一階段原始驗證紀錄見 `TEST_RESULTS.md`。已在實際瀏覽器確認桌面頁面、缺金鑰提示、手動編輯與重新整理恢復，並檢查390px手機版畫面。另以不含專案資料的固定訊息確認 Gemini 3.5 Flash 連線成功；此次選題規則以模擬回應驗證，實際生成品質仍待人工驗收。

## 擴充範圍

第二階段已加入影片上傳、本機辨識、粗剪與MP4輸出。後續應先以總監實拍影片驗收辨識及剪輯點，再規劃登入、持久儲存與工作排程。**目前未實作提詞器、直接錄影、字幕、音樂、特效或 B-roll。**
