---
status: accepted
---

# MuseTalk 段落邊界使用純視覺嘴型連續控制

回覆語音串流的相鄰可播回覆片段之間可能出現短暫 PCM 空檔。MuseTalk idle batch 會回到原始 Avatar 影格，下一片段又切回模型生成嘴型；兩者即使使用相同底圖索引，嘴部色彩、輪廓與開口基準仍可能不同，造成單幀閃跳。

在 Avatar renderer 已選出目標影格、且配對音訊已 enqueue 後，加入純 CPU 的嘴型連續控制 seam。控制器只使用既有 MuseTalk mask 的嘴部 ROI，以固定影格數保留短空檔並完成開／閉嘴過渡；generation 變更或 `flush_talk()` 必須清除狀態。

## Considered Options

- 等完整回答或一次生成整段影片：拒絕，會失去回覆語音串流的首音優勢。
- 增加 audio buffer 或放慢音訊等待嘴型：拒絕，違反 ADR-0007 的音訊主時鐘。
- 啟用既有 wall-clock 全畫面 transition：拒絕，會受 queue 延遲影響，且把身體與背景一起混合。
- idle 時持續執行 MuseTalk silence inference：第一階段拒絕，會增加長時間 idle GPU 成本。

## Consequences

- 過渡以媒體影格數推進，不依賴 wall clock。
- 只有嘴部遮罩內像素被時間混合；遮罩外直接使用當前目標影格。
- 視覺控制器不得存取音訊 queue、等待 coroutine 或啟動推理。
- 任何控制器錯誤都回退原影格，不得阻止音訊或影像輸出。
- `model.musetalk.mouth_continuity` 可單獨停用並恢復原行為。
- 此決策改善段落邊界，不取代角色素材、臉框與遮罩品質調校。

## 待機回復過渡補充 — 2026-09-11

MuseTalk 從最後說話影格回到移動中的原始待機影格時，不得把上一個完整影格的嘴部像素直接套入目前影格的遮罩座標。控制器應保存嘴部 ROI，依前後遮罩 bounding box 的中心與尺寸做平移及等比例縮放，再於目前嘴部遮罩內混合；不得加入旋轉、剪切、光流或全畫面混合。

- 開始 closing 前，預設要求連續 2 個 idle pair；期間若 speech 恢復，立即取消 closing。這只控制視覺狀態，不得延後或緩衝音訊。
- 相鄰遮罩中心位移超過嘴寬 25%，或縮放超出 `0.85–1.15` 時，不強制對齊；改用目前索引的 neutral mouth 完成短 closing。
- 對齊與回答結束的 settling 已分別由設定控制；v1 預設啟用對齊與 12 影格 settling，使用目前移動中的待機影格作為目標，避免整張畫面凍結或跳回固定底圖。
- settling 使用 smoothstep 權重，只在嘴部 ROI 執行；720×1280 實測平均 1.596 ms、最大 3.966 ms，不增加推理或音訊等待。
- 自動驗收涵蓋移動遮罩、異常位移回退、generation reset、遮罩外像素不變與固定影格完成。
- 正常運行只保留 transition、fallback、最大位移、最大縮放及 video repeat/drop 聚合計數；逐幀資料僅在診斷開關啟用時輸出。

## 說話至待機轉場控制器補充 — 2026-09-14

`model.musetalk.avatar_transition` 啟用時，由 `AvatarTransitionController` 接手回答結束後的視覺轉場：說話結束時以待機相位匹配規劃 settling 長度與目標影格，完成 settling 後再做短暫 micro crossfade；此設定取代上節的 12 影格 settling。

- 控制器只規劃即將播放的影格，不移動 MuseTalk 的 frame cursor；相位匹配不得任意跳轉待機索引，只在 settling 長度範圍內沿 ping-pong 播放方向的前方影格，以姿態描述子加時間懲罰挑選目標。
- settling 預設 5 影格，並限制在 4–6 影格；micro crossfade 預設 2 影格，全畫面差異超過 `micro_crossfade_fullframe_max_diff` 時改為只在 MuseTalk 遮罩內混合，避免身體與背景鬼影。說話開始的 opening 預設 2 影格。
- 相位描述子淡化嘴部權重；speech 端描述子使用與目前輸出影格相同的 ROI 索引。
- 嘴型連續控制器由轉場控制器統一呼叫，不得對同一影格重複合成；generation 變更、插話與 `flush_talk()` 必須立即重置狀態，也不得修改輸入影格。
- 原任務規格已移除；參數定義見 `src/config/schema.py` 的 MuseTalk 設定，行為以 `tests/test_avatar_transition.py` 為準。
