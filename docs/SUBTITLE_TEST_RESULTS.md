# 第三階段字幕驗證紀錄

2026-10-28（Asia/Taipei）。本機Windows／Python3.12.14／Streamlit1.65.0，jieba0.42.1、fontTools4.60.1，FFmpeg7.1（既有Gyan完整版本的本專案副本）、FFprobe4.2.11、微軟正黑體粗體。

## 自動測試

```text
.venv\Scripts\python.exe -m pytest -q
223 passed in 34.53s
pip check: No broken requirements found.
```

原189項全部保留，新增34項字幕測試，沒有呼叫Gemini。真正執行FFmpeg／FFprobe，驗證直式192×320、橫式320×192的MP4字幕燒錄與無字幕輸出；從成品擷取畫面檢查白色與黃色像素，字型cmap驗證繁體字形，並核對輸出長度、畫面比例、音畫長度與原片SHA256。新增的獨立Cloud環境檢查另通過8項燒錄相關測試。

涵蓋繁體生成與詞界、不捏造長句細部時間、刪除重講字幕及後段前移、跨切點詞語保護、人工修字保留與再次確認、人工拆句／合句、剪輯版本恢復無重複、JSON相容、SRT正確時間、ASS注入防護、字型缺失／缺字／無libass、單張預覽快取、字幕開關、UI調整不呼叫AI／ASR，以及補充辨識僅處理缺時間段落、失敗保留資料。

測試媒體為合成黑底／測試圖及測試音訊，未加入正式腳本或影片資料庫。原ABC分類SHA256保持 `7A937B510636400A2C9630E52A436D84CDAFC66602E76F7BC0E4B2628B79FEF8`。測試影片、圖片、資料庫及第三方工具均在Git忽略目錄。

## Cloud相容性

新字幕邏輯只使用跨平台Python、系統FFmpeg/libass及實際字型檔。根目錄requirements提供新Python依賴；packages提供ffmpeg、fonts-noto-cjk、fontconfig。Linux使用Noto Sans CJK TC，不使用本機Windows路徑。限制編碼／濾鏡執行緒為2，預覽只有按鈕才執行，並清除暫存。

雲端實測進度另補於下方；本機通過不代表已在Cloud成功輸出。首次開啟使用者Cloud網站時為休眠，已送出正常喚醒，平台一度顯示啟動較久。
