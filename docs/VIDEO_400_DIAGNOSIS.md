# 第二階段語意比對 HTTP 400 診斷

日期：2026-10-27。

## 根因與請求路徑

`ui/video.py → core/video/service.py:analyze → core/editing/edit_planner.py:semantic_plan → core/ai/provider.py:GeminiProvider.generate → client.models.generate_content`。

400 發生在可選的 Gemini 文字語意比對，不是影片上傳或本機語音辨識。原本 `SemanticPlan` 的 JSON Schema 含 suggestions 最多150筆、每筆 segment_ids 最多30筆、matches 最多300筆的巢狀陣列限制，會讓結構化輸出的約束文法過於複雜。

用已設定測試金鑰、同一個 `gemini-3.6-flash`、相同公開示範句做 API 對照，未傳送使用者影片、音訊或逐字稿：

| 請求 | 結果 |
|---|---|
| 原始 SemanticPlan Schema | 兩次 HTTP 400，`INVALID_ARGUMENT / Request contains an invalid argument.` |
| 僅移除陣列 minItems／maxItems 的 Schema | 一次503服務忙碌，後續對照成功且通過原始 Pydantic 驗證 |

模型、Prompt、示範輸入及其餘參數維持相同；不以換模型或增加重試掩蓋問題。Google 官方也說明，大型巢狀陣列上限可能造成400，建議降低或移除這類限制：[Structured outputs limitations](https://ai.google.dev/gemini-api/docs/structured-output#limitations)。

## 音訊及 API 格式

- FFmpeg 將真實音軌轉為 WAV／PCM signed16 little-endian、16 kHz、單聲道，對齊原片時間。
- Faster-Whisper 的 `small`／CPU INT8 接收正規化 float32 NumPy 聲波，不經 Gemini 音訊 API。程式驗證 WAV 參數，測試實際解碼8秒影片並驗證格式及音檔大小。
- 16 kHz單聲道16-bit音訊約32,000 bytes／秒；15分鐘原始PCM約28.8 MB加WAV標頭。暫存 WAV 使用後刪除。
- Gemini只收到 JSON文字中的 `script_sentences` 與 `segments[{id,text}]`。SDK的 HTTP Content-Type 是 `application/json`；回覆 MIME 是 `application/json`。沒有 `inline_data`、`file_data`、音訊 MIME、音訊上傳或由AI猜測的時間。原始影片大小不會進入這次文字請求。
- `response_json_schema` 是 SDK 支援的參數。只對 SemanticPlan 啟用精簡的網路 Schema；原始150／300／30筆限制、非空、ID有效性、連續片段及時間範圍仍在本機驗證，不因簡化網路格式而接受不合法輸出。

## 日誌及錯誤顯示

- `data/logs/gemini_calls.jsonl`（或自訂DATA_PATH旁的logs）及伺服器 stderr 記錄同一份安全 JSON。Community Cloud的伺服器日誌可直接看到。
- 記錄診斷編號、操作 `video_semantic_alignment`、模型、HTTP狀態、分類、固定的具體原因摘要、允許的API欄位名、Schema雜湊、輸入byte數及耗時。
- 原始伺服器錯誤只在記憶體分類；以固定摘要與欄位白名單遮蔽，不寫入原始錯誤本文。避免API回音洩漏金鑰、網址、Prompt、音訊或私人逐字稿。未知錯誤明確標示原因未提供，不猜測。
- 分開顯示模型能力不支援、音訊格式、Schema、參數、輸入過大及其他API問題；400不重試，也不自動切換模型。
- 前端標示「AI文字語意比對未完成」及診斷編號，不再讓使用者誤以為本機語音辨識或影片已損壞。

## 資料與驗證

189項測試通過；新增15項涵蓋精簡Schema、原始限制仍生效、400各種原因、日誌去敏、真實SDK的HTTP序列化，以及API失敗後資料保留與可重新嘗試。媒體測試真的執行FFmpeg／FFprobe。

失敗會保留：原片SHA256、已完成的聲學逐字稿、本機停頓／重講／比對、人工保存時間軸歷史及既有輸出。後續重試沿用已完成的同模型ASR，不重複辨識。不修改第一階段腳本、對話、ABC分類或資料表。

修正需部署到雲端後才生效，沒有新增套件、系統路徑或Windows專用依賴。GitHub更新後先等自動部署，重新載入粗剪頁再按「開始分析」。不需重新上傳同一支影片；本次未成功的語意分析不會被當作成功快取。
