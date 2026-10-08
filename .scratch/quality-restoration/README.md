<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 畫質恢復對照 — 2026-10-02

本輪只改變輸出高度、VAE decoder 或 UNet 加速路徑，逐項重啟一般
Jetson 入口。音訊期限修正、CPU worker 1、暫停收音略過重採樣、
160ms 音訊接收目標、既有舞台與已保存 LLM 偏好保持相同。

- `before.yaml` 是使用者確認電子音修好後、此次測試前的正式設定。
- `baseline/`：450 高度、TAESD、TensorRT UNet。
- `native/`：僅將 max_height 改成 0，實際輸出 1080×1920。
- `fullvae/`：僅清空 tiny_vae_path，保留 TensorRT UNet 與 450 高度。
- `originalunet/`：僅清空 unet_engine_path，保留 TAESD 與 450 高度。
- `final/`：恢復 before.yaml，再執行三輪朗讀、接收 PCM 與真實 LLM 對話。

`run_profile.py` 依序執行正式前端的三輪朗讀與 PCM 擷取，即使失敗也
保存 JSON、WAV、日誌、退出碼；沒有放寬 23fps／120ms／零補音門檻。
`set_profile.py` 會修改正式 config；僅在測試維護期間、停止服務後使用，
結束時還原 before.yaml 並重啟一般入口。勿和其他活躍會話同時執行。

`build_report.py` 產生單檔 HTML，嵌入量測摘要、較早的 VAE 局部畫質
對照及修正前後試聽音訊。音訊以 MP3 壓縮供試聽，所有驗收仍依原始
WAV／WebRTC stats，沒有錄製使用者語音。

閱讀成品：`web/public/reports/avatar-smoothness-report.html`，或服務的
`https://localhost:3000/reports/avatar-smoothness-report.html`。
