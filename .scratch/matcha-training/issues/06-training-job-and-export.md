<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 訓練工作與匯出
Status: ready-for-agent
Blocked by: 02, 03

依[規格](../spec.md)第 8、9 點與「信任邊界與資料位置」。

- 從 jetson-orin 帶入並調整 `tts_training_jobs.py`、`routes/tts_training.py`、`train_matcha.py`、`matcha_arch.py`、`export_matcha_onnx.py`：以 `.local/matcha-train/` 的 Python 啟動獨立子程序，同一時間只進行一件，可取消並釋放 GPU，日誌可讀取。
- 拒絕條件：有舞台連線，或剩餘顯存低於門檻（初始 8 GB，可設定）；回應要說明原因，供介面顯示。
- 只有狀態為「全部已確認」的語料才能訓練；訓練前再檢查一次。
- 匯出：寫入 `models/tts/<slug>/` 與 `voice.json`（使用限制標示依 03 計算）；Edge 語料的模型不提供匯出路由。
- 新路由全部登記 `ROUTE_ACCESS` 為 ADMIN；測試用假子程序，不載入真實模型，0 失敗、0 跳過。

## 從工單 02 帶來的注意事項

- 訓練環境用 `scripts/setup-matcha-train.sh` 建立（上游 `matcha-tts==0.0.7.2`、MIT；底模已驗證可嚴格載入，`.local/matcha-train/`、`.local/matcha-base/` 已在 `.gitignore`），請直接沿用，不要另寫安裝流程。
- 上游 `MatchaTTS.forward` 回傳 4 個值，jetson 的 `train_matcha.py` 只解 3 個，移植時要修正。
- 一批裡最短的語句少於 `out_size` 時會出形狀錯誤；訓練要把 `out_size` 縮到該批最短長度，或過濾過短語句。
- cu124 變體只做過解析，沒有在 GPU 上實測；第一次在 GPU 上跑要記錄顯存與耗時，用來校準 8 GB 阻擋門檻。
