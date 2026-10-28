# MP4 下載與逐字稿主導字幕（2026-10-28）

此文件取代較早文件中「ASR 是字幕文字來源」的描述。

## 下載診斷與修復

目前只有使用者回報 Cloud 成品可播放、下載失敗及播放卡頓，尚未取得該次 Cloud 日誌。因此不能確認那一次是網路、記憶體或媒體失效。

已在本機真實 Streamlit 1.65.0 重現程式缺陷：`download_button(data=lambda: output.read_bytes())` 使用 deferred 機制，`execute_deferred` 產生的實際媒體 ID 沒有映射到 session coordinate。兩次 `remove_orphaned_files` 後實際媒體消失；直接資料註冊的下載媒體則不會被清掉。回歸測試直接操作 SDK 驗證此差異。

`ui/downloads.py` 統一兩種編輯介面下載。使用完成輸出的 MP4 bytes、`video/mp4` 與安全的中文檔名，`on_click='ignore'`，不觸發輸出或額外 deferred 請求。Session State 只保留輸出 key，正式 MP4 留在專案媒體目錄；暫存清理只處理 temp/preview，不刪 output。沒有 Base64、JS MP4 Blob 或把伺服器路徑交給用戶。

FFmpeg 本來就在原子發布前完整解碼、檢查長度與音畫同步；本次補上成功／失敗、return code、檔案大小、耗時及參照保存日誌。下載前再次檢查存在、非空與完整讀取；缺失、讀取或記憶體錯誤顯示可理解訊息。成品快取只重用非空檔。

這仍使用 Streamlit 記憶體媒體庫，並非磁碟串流或永久物件儲存。讀取時有短暫資料副本，無法保證任意大型影片在共享 Cloud 都可下載；200 MB 以上提示耗時與本機替代方式。Cloud 主機重建仍可能遺失正式檔，需定期備份。

伺服器日誌搜尋 `video_delivery`：`ffmpeg_finished`、`output_validated`、`output_reference_saved`、`download_registered`、`download_failed`、`download_unavailable`、`media_tool_failed`。內容只有 return code、size、exists、elapsed、Session 參照狀態、例外類型／OS 原因與遮蔽後錯誤分類；不記錄路徑、命令、API key 或稿件。未知 FFmpeg stderr 不直接傾印，避免回顯稿件或客戶檔名。

若 Cloud 再失敗，請提供點擊前後上述日誌，以及瀏覽器 Network 中下載請求的狀態碼（例如 404/500）與錯誤描述，不包含 Cookie、Token、Secret 或逐字稿。沒有這些資料，不能把本機重現直接當作 Cloud 個案已定案。

## 逐字稿 → 聲學對齊 → 字幕

文字權威為剪輯專案建立時保存的 `script_snapshot`（畫面顯示版本）；不會在背景讀取第一階段之後的新版本覆寫此專案。字幕編輯器人工修字優先。ASR 全文保留作為時間參考，絕不將「三層」改回「三成」。既有 ASR 字幕初次開啟時遷移，人工修字、樣式及關閉偏好保留。

`script_alignment.py` 先從現行保留區間篩選語音，將逐字稿與 ASR 字詞序列對齊；同音替換沿用鄰近真實字詞時間，不按字數平均計時。稿件依原標點與換行分句，長句只在稿內詞界且有分離的真實詞語時間時拆分。只有整句時間時保留聲學範圍、標示低信心；不能區分多句時列為無法對齊。缺句不硬塞，稿外語音不加字幕。這是文字輔助對齊，不是新增聲學 forced-alignment 模型；大量改講仍可能需要手動時間。

字幕來源 `spans/atoms` 內的文字全部出自逐字稿，現行時間軸映射成輸出座標。人工修改後仍用來源錨點保存。JavaScript 預覽取得相同 sources 與 Python layout hints；輸出先保存當下快照，SRT 與 FFmpeg 使用相同 `delivery_cues`，不再執行 ASR 校正文案。失敗對齊的句子可選擇不顯示或指定剪輯後時間，不增加強制確認。

## 驗證與部署

Python 回歸 263 項通過（46.67 秒），JavaScript 11 項通過；包含同音字、原標點／句界、缺句、額外語音、重講時間映射、舊 ASR 字幕遷移、人工修字保留、真實 SDK 媒體清理與直接下載資料。既有 FFmpeg 測試實際生成 MP4、解碼檢查白字／黃字畫面及無字幕差異；新增下載資料與完成 MP4 bytes 相等檢查。不消耗 Gemini 額度。

實際本機瀏覽器已輸出並點擊下載「合成編輯器測試_粗剪.mp4」。下載檔 53,793 bytes，解碼確認 2.00 秒、H.264／AAC。編輯器顯示逐字稿句末句號，ASR 原文未有該標點。此為合成素材驗收，不代表 Cloud 實拍與大型檔案驗收。

沒有新增依賴。同步 GitHub main 並 Reboot app，啟動標記為 `app_release=2026.10.28-script-download-r3`。Cloud 下載仍需部署後由實際使用者重測；本機測試不代表 Cloud 已驗收。
