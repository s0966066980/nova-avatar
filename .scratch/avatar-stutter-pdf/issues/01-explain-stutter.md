<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 製作原因與修復說明 PDF

Status: resolved
Type: task

## 工作

核對實測與程式，製作時間預算及管線圖，整理修復與限制，產生 PDF 並檢查文字與頁面效果。

## Comments

本次文件整理使用先前實測；不執行新的 GPU 壓力測試或變更正在執行的服務。

## Answer

完成 8 頁繁體中文 PDF：`docs/reports/Nova-Avatar-Stutter-Causes-and-Fixes.pdf`。
包含管線圖、40 ms 輸出預算圖、原 VAE／TAESD 畫面對照、排程修正、控制台解析度使用方式、歷史前後數值、目前保存設定及剩餘限制。

- PDF 共 8 頁，中文可搜尋，主要數值及各頁頁碼檢查通過。
- 八頁均實際渲染並目視確認，沒有溢出、空白頁或截斷。
- 24 份引用來源 SHA-256 核對沒有變更；記錄於 `evidence-manifest.json`。
- 本次整合／品牌／授權稽核通過；前端 93 通過；build 通過。
- Python 530 通過、4 略過、1 既有全尺寸背景合成效能失敗：36.76 ms，門檻 <30 ms。已於 PDF 如實揭露，未修改程式或門檻。
- PDF SHA-256：`020e32f78276b68a7a037df403553890f75efe665a9bc57d11919cf167f2e842`。

文件製作來源、量測引用與檢查結果保留於本資料夾；没有重新建立使用者已刪除的完整移植報告、網站或音檔封裝。
