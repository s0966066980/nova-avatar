<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 訓練語料資料模型
Status: ready-for-agent

依[規格](../spec.md)第 2、3、5、6、7 點與 `CONTEXT.md`「訓練語料」「使用限制標示」。

- 語料資料夾 `data/tts/training/<slug>/`：音檔、逐字稿、每句的校對狀態（待確認／已確認／已排除）、來源宣告（測試用老師、自己錄的、有書面授權、開發用）。
- 使用限制標示的計算：取底模與語料來源中最嚴格者，Edge 或開發用 → Development only，其餘 → Research / Non-commercial；可單獨測試。
- 數字與日期展開成中文字的標準化器，展開不了的回報為待處理。
- 所有路徑由伺服器產生，slug 與檔名都要檢查。
- 只做資料層與純函式，不新增路由；測試使用自足的 fixture，0 失敗、0 跳過。
