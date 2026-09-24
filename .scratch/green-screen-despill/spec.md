# 綠幕去綠光（Despill）邊緣修正 v1 完成規格

Status: completed

## 問題

`chroma_composite()` 合成到新背景後，人物輪廓（頭髮、肩膀）邊緣仍看得到一圈綠色暈邊。

## 根因

原本的去綠光只作用在「alpha 半透明段」加上「緊貼近純背景像素的 3px 膨脹帶」內；真實綠幕素材（環境反光造成的溢色）量測寬度約 15–20px（見 `data/avatars/musetalk_1/full_imgs/00000128.png` 的頭髮/肩膀邊緣），遠寬於原本的 3px，因此大部份暈邊完全沒有被去綠光處理到。

## 已交付行為

- 去綠光強度改為依「到色鍵邊界的距離」連續衰減，衰減半徑依素材解析度自動縮放（`clip(frame_height * 0.01, 6, 40)`），貼齊邊界的 2px 維持全強度去綠光。
- alpha 轉換改用 smoothstep 取代線性內插，減少過渡處的階梯感。
- 修正 GaussianBlur 在均勻區域可能溢出至 255 以上、導致像素被無條件捨去多減 1 的浮點誤差。

## 效能回歸與修正

第一版以全畫面 float32 運算實作，在 1080×1920 的 `musetalk_1` 上每幀 47–65ms，超過 25fps 的 40ms 預算。渲染執行緒因此只跑到即時速度的 59–71%（見 `logs/start-all-backend.log` 2026-09-24 23:10 起的 `[AVSync]` 紀錄），待機時畫面劇烈抖動。現版全畫面運算改用 uint8 OpenCV，浮點運算只做在需要混色或去綠光的輪廓帶（約佔畫面 5%），每幀約 14.5ms，輸出與第一版最多差 1 個色階。`test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar` 以 30ms 門檻防止再次回歸。

## v1 驗收

- `tests/test_scene_background.py` 涵蓋：半透明邊緣、緊鄰邊緣的不透明像素、寬幅環境溢色暈邊皆會被去綠光；遠離邊緣的乾淨前景（衣物等）維持不變（bit-exact）。
- `uv run pytest`、`uv run python scripts/check-integration.py`、`web` 的 `npm test` / `npm run build` 全部通過。
- 對照圖：`preview-full.png`（整張合成對照）、`preview-shoulder-zoom.png`、`preview-hair-zoom.png`，皆用實際 `src/scene/service.py:chroma_composite` 產生（非模擬），左圖為修正前，右圖為修正後。

實作見 `src/scene/service.py` 的 `chroma_composite()`；背景見 [ADR 0014](../../docs/adr/0014-compose-green-screen-avatars-on-server.md)。
