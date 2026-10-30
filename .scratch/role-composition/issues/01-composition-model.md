<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 組合資料模型、轉換與各自保存
Status: resolved

依[規格](../spec.md)「組合」「成員欄位一致」「各自保存」「轉場」「天氣工具」「共用服務」。

- 角色庫改為組合結構：主數位人 id、成員清單（設定檔 id、啟用、專長介紹、交接規則、交接說明 中／英、工具；天氣工具含場域預設地點）、主數位人同樣的交接欄位、轉場（預設＋個別方向覆寫）。取代 `pair`、單一 `handoff`、頂層 `weather`。
- 自動轉換既有 `config/avatar_profiles.yaml`（version 1）：pair.main → 主數位人；pair.specialist → 第一位成員並帶入 handoff 的說明／規則／交接說明與 weather 地點；return_announcement 轉為主數位人的交接說明；既有方向轉場轉為個別覆寫；轉換可重複執行、先備份。
- 驗證：啟用的專門數位人 ≤ 5；天氣工具 ≤ 1；成員與主數位人相容（取代 `compatible_pair`）；成員不重複；主數位人不能同時是專門成員。
- 各自保存：每位成員有修訂版本，儲存單一成員只檢查該成員版本；更換主數位人、加入／移出、啟用名單變動檢查組合版本。新增或調整的路由列入 `ROUTE_ACCESS`（ADMIN，ADR 0021）。
- 只改資料層與 API；執行期（03）、路由（02）、介面（04）另票，必要的暫時相容層寫在 Comments。

## Comments

### 2026-10-30 資料結構與 API 契約（02–04 依此實作）

**檔案** `config/avatar_profiles.yaml`（version 2；只存下列鍵）：

```yaml
version: 2
revision: 15            # 檔案修訂：任何儲存 +1；執行期 active_revision／草稿判斷、舊版整份儲存、greeting/apply 用它
profiles_revision: 14   # 設定檔清單修訂：只有設定檔清單變動才 +1
profiles: [...]         # 同前，但不再有 tools
composition:
  revision: 3           # 組合結構：enabled、main.profile_id、成員清單（加入／移出／順序／換設定檔）、各成員 enabled
  enabled: true         # 角色交接開關（原頂層 enabled；原型主數位人的「啟用角色交接」）
  main:                 # 主數位人：與成員同樣的交接欄位，沒有工具
    profile_id: main
    revision: 1         # 只涵蓋下面四個文字欄位；換主數位人不動它
    description: ''     # 專長介紹 ≤2000，可空
    rules: ''           # 交接規則 ≤12000，可空
    announcement: 接下來請主數位人接續回答您的問題。   # 交接說明（必填 ≤2000）
    announcement_en: Our main avatar will help with your question next.  # 可空
  members:              # 清單順序 = 顯示／席位順序；啟用 ≤5，總數 ≤29（未啟用可超過 5 位）
  - profile_id: weather
    revision: 1         # 這位的任何欄位（含 enabled、profile_id）變動 +1
    enabled: true
    description / rules / announcement / announcement_en   # 同 main
    tools: {weather: {enabled: true, county: '', town: ''}} # 場域預設地點在工具內；全組合 enabled 的天氣工具 ≤1（不論成員是否啟用）
  transitions:
    revision: 1
    default: {kind: effect, effect: fade, duration: 0.6, asset_id: ''}
    overrides: [{source, target, kind, effect, duration, asset_id}]  # source/target 為設定檔 id；可指向已移出組合的設定檔（保留但不用）
```

- 「生效中」成員＝`composition.enabled` 且 `member.enabled` 且與主數位人相容（`composition.live_members`）。相容條件同舊 `compatible_pair`：兩者 MuseTalk、同 LLM endpoint+model、同 TTS 引擎、BreezyVoice 同伺服器+模型。不相容的已啟用成員保留 `enabled: true` 但不生效（設定檔被改時不會讓檔案失效）。
- 讀取 helper（`src/profiles/composition.py`，02/03 用這些而非暫時欄位）：`main_profile_id`、`live_members`、`weather_holder`、`transition(library, source, target)`（覆寫否則預設）、`incompatibility(main, profile)`、`compatibility_report`、`referenced_media`、`profile_ids`。
- 設定檔數量下限由 2 改為 1（單一主數位人即可）。

**路由**（皆 ADMIN，已列入 `ROUTE_ACCESS`）。成功一律回 `{"code":0,"library":<讀取格式>,"runtime":<snapshot>}`；寫入在 `asyncio.to_thread`。

| 方法與路徑 | body | 檢查的修訂 |
|---|---|---|
| `GET /api/profiles` | — | 另回 `compatibility: {profile_id: [不相容原因…]}`（對已儲存的主數位人；空陣列＝相容） |
| `PUT /api/profiles` | 新：`{profiles:[…], expected_profiles_revision}`；舊（暫時）：`{library, expected_revision}` | 新：`profiles_revision`；舊：檔案 `revision` |
| `PUT /api/profiles/composition` | `{expected_revision, main?, enabled?, confirm_disable?}` | 組合 |
| `PUT /api/profiles/composition/main` | `{expected_revision, main:{description?, rules?, announcement?, announcement_en?}}` | main |
| `POST /api/profiles/composition/members` | `{expected_revision, member:{profile_id, enabled?, description?, rules?, announcement, announcement_en?, tools?}}` | 組合 |
| `PUT /api/profiles/composition/members/{profile_id}` | `{expected_revision, expected_composition_revision?, member:{…省略的欄位保留原值}}` | 該成員；`enabled` 或 `profile_id` 有變時另查組合 |
| `DELETE /api/profiles/composition/members/{profile_id}` | `{expected_revision}` | 組合（設定檔與轉場覆寫保留） |
| `PUT /api/profiles/composition/transitions` | `{expected_revision, transitions:{default?, overrides?}}` | transitions |

- 客戶端送的 `revision` 欄位一律忽略，伺服器依「哪個範圍內容變了」各自 +1；存成員只動該成員修訂（與檔案 `revision`），不動其他成員、main、組合。
- 設定檔清單儲存：組合中的主數位人或成員不可刪（409 `field: "profiles"`，請先移出或換主數位人）；被刪設定檔的轉場覆寫自動移除。
- 換主數位人：新主數位人不可是成員（409 `field: "main"`）；會讓已啟用成員不相容時回 409 `disable_required: [ids]`，帶 `confirm_disable: true` 重送則停用它們並回 `disabled_members: [ids]`。
- 啟用成員（加入時 `enabled: true` 或由 false 改 true、或換設定檔）若不相容：409 `field: "enabled", reasons: [...]`。

**錯誤格式**：`{"code":-1, "msg":"…", "field"?: "announcement"|"enabled"|"tools.weather.enabled"|"main"|"profile_id"|"profiles"|"expected_revision"|…, "conflict"?: {...}, "reasons"?: [...], "disable_required"?: [...]}`。
- 400：格式或欄位錯誤（例：交接說明空白 `field: "announcement"`；缺 `expected_revision`）。
- 409：與其他資料衝突：啟用 >5（`field: "enabled"`）、天氣工具 >1、重複成員、主數位人當成員、不相容、版本衝突。
- 版本衝突：`conflict: {scope: "member"|"main"|"composition"|"transitions"|"profiles"|"library", revision: <目前修訂>, profile_id?, current?: <該範圍目前已儲存內容>}`；訊息含「其他控制台」。成員已被移出時存該成員回 409 `scope: "composition"`。

**v1 → v2 轉換**（`composition.migrate_v1`）：啟動時 `ProfileStore.initialize` 先把原檔複製為 `avatar_profiles.yaml.v1-<時間>.bak`（已加入 .gitignore）再寫 v2；已是 v2 則不動，可重複執行。`load()` 讀到 v1 只在記憶體轉換。pair.main→main；pair.specialist→第一位成員（enabled true，帶 handoff 說明／規則／交接說明中英、天氣工具與 weather 地點）；return_announcement(_en)→main 的交接說明；transitions→overrides，預設 fade 0.6；revision +1；其他設定檔的天氣工具丟棄並記 log。

### 暫時相容層（請在對應票移除）

1. **A1 兩角色檢視** `composition.legacy_pair_view`：`ProfileStore` 所有讀寫回傳值都另加 `enabled`、`pair`、`handoff`、`weather`、`transitions`（=overrides）與每份設定檔 `tools`。pair.specialist＝第一位生效成員（否則第一位啟用、否則第一位；沒有成員時＝main 且 enabled false）。現有 coordinator、routing、voice_session、greetings/controller.py、routes/settings.py、routes/profiles.py 的 `greeting_profile`、`scripts/eval_llm_quality.py` 都還讀這些鍵。→ 02/03 改讀 `composition` 後移除。
2. **A2 舊整份儲存** `ProfileStore.save` + `composition.apply_legacy_view` + `PUT /api/profiles {library, expected_revision}`：舊 `AvatarProfiles.vue`、`IdleGreetingSettings.vue` 仍用；兩角色鍵映射回 main 與 pair.specialist 成員，其他成員不動。→ 04 改用 `{profiles, expected_profiles_revision}` 與組合路由後移除。
3. **A3** `store.compatible_pair`（coordinator.apply 只載兩位）。→ 03 改用 `live_members`（並處理多位素材載入）。
4. **A4** `store.RETURN_ANNOUNCEMENTS`（coordinator 交回主數位人的預設說明）。→ 03 改用目的成員的 `announcement`。
5. **A5** `ConversationRoles.edge()` 先查 A1 的 `transitions` 再用 `transition()`（已會套用預設轉場）。→ 03 只用 `transition()`。
6. **A6** `referenced_media` 也收 A1 的 `transitions`；`canonical()` 會丟掉 v2 檔中的 A1 鍵與設定檔 `tools`（舊主控台或測試把檢視寫回時）。→ 隨 A1/A2 移除。
7. **A7** `validate_profile` 接受並丟棄 `tools`（舊 `AvatarProfileEditor.vue:75` 天氣勾選）。→ 04 移除勾選後改為拒絕。

### 2026-10-30 結果

- 新增 `src/profiles/composition.py`（schema、驗證、修訂、轉換、相容、A1）、`src/profiles/validation.py`（共用欄位檢查；`ProfileError` 可帶額外 JSON 欄位）；`store.py` 改為 v2 與各範圍儲存；`routes/profiles.py` 六條新路由；`access.py` 列 ADMIN；coordinator 只改 A5 與轉場影片檢查。
- 測試：`tests/test_role_composition.py` 16 個測試函式、21 項（含依現場 `avatar_profiles.yaml` 結構〔revision 13、main+weather、無機密〕的轉換、備份與重跑、A1 重現 v1 執行期鍵值、各自保存與衝突、啟用上限、天氣工具唯一、不相容、換主數位人、HTTP 錯誤格式）；改寫 `test_avatar_profiles.py` 一項 v1 測試。
- CI：ruff、pyright 0 錯誤、check-integration 通過；pytest 1407 passed、3 skipped，2 failed 為已知 worktree 基線（缺本機素材）。未動 `web/`、`pyproject.toml`。
- 無需實機驗證；現場檔會在下次啟動時自動轉換並留備份。
