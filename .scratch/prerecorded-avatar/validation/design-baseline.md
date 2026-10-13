<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 設計文件驗證 — 2026-10-12

本輪產物為功能規格、領域術語、ADR 與七個待確認的實作工作項目。
尚未新增預錄呈現、素材製作或瀏覽器錄影程式；以下檢查針對目前
工作區基線，不代表新功能已達行為或 1080p 效能門檻。

| 檢查 | 結果 |
| --- | --- |
| `uv run python scripts/check-integration.py` | 通過，品牌／授權／依賴／商業審查設定檔契約正常 |
| `uv run pytest tests/test_branding_compliance.py -q` | 5 passed、12 subtests passed |
| `uv run pytest` | 538 passed、4 skipped、1 failed |
| `npm test`，在 `web/` | 93 passed |
| `npm run build`，在 `web/` | 通過；既有大 chunk 警告 |
| 文件靜態檢查 | 11 份 Markdown 的專案 header、相對連結與空白檢查通過 |

## 既有 Python 失敗

`tests/test_scene_background.py::test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar`
的 1080×1920 綠幕合成中位數為 36.03 ms，高於 30 ms 斷言。
同一測試在本輪設計訪談前也未通過；本輪沒有更改該測試、背景合成
或效能門檻。這項限制支持另行驗證瀏覽器呈現路徑的必要性，不能
據此聲稱瀏覽器路徑已達標。

完整輸出保留於本機 `pytest.log`、`web-tests.log` 與 `web-build.log`。

## 實作後仍需驗證

依 [功能規格](../spec.md) 完成素材與模式切換、媒體時序、五秒
完整品質製作、資源釋放、MP4 錄影，以及十分鐘 Jetson 雙畫面實測。
先取得時序對齊證據，再作高解析負載驗收。
