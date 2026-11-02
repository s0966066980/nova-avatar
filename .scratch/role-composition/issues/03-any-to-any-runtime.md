<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 任意角色交接的執行期
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)。`src/profiles/coordinator.py`、`src/server/voice_session.py` 改為任意來源→目的：交接說明取目的成員的那一句；轉場取個別覆寫否則預設；主數位人開場與兜底、「返回主數位人」與訪客對話重置回主數位人；閒置招呼只在主數位人；各角色對話記憶照舊隔離。

- 素材與資源：套用組合時處理所有啟用成員的人物素材；先查明多位成員的人物素材快取對記憶體／顯存的影響（現在只載兩位），在 Comments 回報並採用不讓顯存隨成員數暴增的方式（例如按需載入或共用快取），必要時列待實機驗證。
- 取代所有寫死兩角色的地方（清單見 role-pair-map.md）。

## Comments

### 2026-10-30 結果

**執行期**（`src/profiles/coordinator.py`）
- 可到達的角色＝主數位人＋`live_members`（`roster()`）；`enabled`＝至少一位生效成員。路由結果依 02 約定的 `{"target": id | None, …天氣欄位}`（02 Comments，rc/02 @ 6b220ce）：`None` → 固定回覆 clarification；不在 roster 的 id → 固定「無法確認接手方式」並記 log，不交接。
- 交接說明＝目的角色自己的 `announcement`（en-US 用 `announcement_en`，空白時主數位人用 `MAIN_ANNOUNCEMENTS`、成員用通用英文句）。轉場只用 `composition.transition()`（覆寫否則預設）。
- 天氣只在目的是生效中的天氣工具持有者時查詢（`weather_member()`）；`speculative_plan()` 依 02 的推廣（持有者 → `{"weather": None, "context": ""}`，其他 → `ANSWER_CONTEXT`），留在非持有者角色時回傳它，讓並行回答放行（ADR 0022）。合併時 target_id／speculative_plan 這幾行以 02 版本為準。
- 「返回主數位人」與訪客重置回 `main_id`；`can_return`＝目前不是主數位人。閒置招呼只在主數位人（`voice_session.greeting_conditions`、`greetings/controller.py`、`routes/settings.py`、`routes/profiles.py` 的 `greeting_profile` 改讀主數位人 id）。各角色記憶仍以 `(sessionid, profile_id)` 隔離（測試涵蓋）。
- 執行期快照：移除 `pair`，新增 `main_profile_id`、`member_ids`（生效成員，依名單順序）。控制台未讀 `runtime.pair`。

**暫時相容層**：已移除 A3（`compatible_pair`）、A4（`RETURN_ANNOUNCEMENTS`）、A5（`edge()` 讀 A1 `transitions`）。A1 本身仍保留：執行期（coordinator、voice_session、greetings、routes）已不讀它，但 `routing.py`／`scripts/eval_llm_quality.py`（02）與舊主控台＋A2（04）還在用；A6 隨 A1/A2 移除。

**人物素材記憶體調查**（唯讀；主 checkout `data/avatars/*`）
- MuseTalk 素材載入 = `full_imgs`＋`mask` 解碼成 BGR uint8 放在主記憶體，`latents.pt` 以 `torch.load(map_location=None)` 載入；兩份檔案的 storage 標記都是 `cuda:0`，所以 latents 會進 GPU。MuseTalk 權重（UNet/VAE/Whisper）只有一份，與成員數無關。
- 實測（CPU 解碼）：`musetalk_1` 1080×1920×192 張 → 影格 1139 MiB＋遮罩 130 MiB ≈ 1.24 GiB RAM、latents 3.1 MB 顯存、解碼 3.7 s；`musetalk_angela` 720×1280×145 張 → 382＋56 MiB ≈ 0.43 GiB RAM、latents 2.4 MB 顯存、解碼 1.2 s。
- 結論：顯存每位成員只多約 2–3 MiB（6 位 < 20 MiB），會隨成員數成長的是主記憶體，最壞 6 位 1080p ≈ 7.4 GiB（主機 30 GiB，調查時可用約 18 GiB）。每個對話的 `MouthContinuityController`／`AvatarTransitionController` 以 `np.asarray` 引用影格不複製，遮罩快取有上限。
- 採用：套用時預載所有生效成員，放進以 `avatar_id` 為鍵的共用快取——同一素材的成員、主數位人沿用 `state.avatar`、重新套用都共用同一份；停用、不相容或已移出的成員不載入，舊快取隨套用釋放。未採按需載入：交接時才解碼要 1–4 s，而且會在對話中途配置顯存。主記憶體若吃緊，之後可改成在交接說明播放期間預先載入，加上 LRU。
- 測試：`tests/test_any_to_any_handoff.py` 新增 15 項（任兩位直接交接含回主數位人、中英交接說明、轉場覆寫／預設且不讀 A1、clarify、非生效 target、只有天氣持有者查天氣、返回與重置回主數位人、招呼只在主數位人、素材只載一次並釋放）；並把舊測試的路由假資料改成 02 格式（`route_to()`）。
- CI：ruff、pyright 0 錯誤、check-integration 通過；pytest 1422 passed、3 skipped（另 2 項為已知的 worktree 基線，已排除）。未改 `web/` 和 `pyproject.toml`。

### 待實機驗證（2026-10-30）

需要在已合併 02＋03 的 `role-composition` 上重啟後端並載入 GPU，所以由 orchestrator 依序執行：
1. 套用前記錄 `nvidia-smi --query-gpu=memory.used --format=csv,noheader` 與後端 RSS（`ps -o rss= -p <後端 PID>`）。
2. 以現有 weather 成員加上一位用 `musetalk_angela`、一位用 `musetalk_1` 的相容成員（`POST /api/profiles/composition/members`，`enabled: true`），然後 `POST /api/profiles/apply`。預期：顯存增加 < 50 MiB；RSS 增加約等於「新素材」解碼大小（已載過的素材為 0）；log 不會重複出現同一素材的 `reading images...`。
3. 舞台：先問天氣交給天氣助手，再問客服主題，應**直接**交給客服成員（不經主數位人），播出的是客服成員自己的交接說明，轉場用該方向的覆寫，沒有覆寫時用預設；按「返回主數位人」回到主數位人；閒置重置後回到主數位人，閒置招呼只由主數位人播出。
