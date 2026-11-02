<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 設定頁介面：三分頁與角色組合
Status: resolved
Blocked by: 01

依[規格](../spec.md)與[原型](../prototype/role-composition.html)（以原型版面為準，套用正式控制台既有樣式元件）。

- 移除「返回控制台」；「訪客互動與語音辨識」移為「數位人、AI 與知識設定」的第三分頁（左側選單移除該項）。
- 角色組合與交接：主數位人選擇、已啟用 N／5、加入專門數位人；成員名單（啟用／未啟用／不相容／空位）；所選成員設定（交接欄位、啟用與相容、工具與場域預設地點、移出）；各自儲存與未儲存狀態、版本衝突只影響該成員；交接路線網狀圖；角色轉場（預設＋個別方向）。
- 交接試算區塊先放介面，串接留給 05。
- 更新版面回歸與對比測試；附 1920×1080、1280×720 深淺截圖於 Comments。

## Comments

### 2026-11-02 結果

**介面**（`web/src/components/`）
- 系統設定中心移除「返回控制台」（回控制台用頂列的檢視切換）；左側選單移除「訪客互動與語音辨識」，改為「數位人、AI 與知識設定」的第三個分頁（數位人設定檔｜角色組合與交接｜訪客互動與語音辨識，方向鍵切換、焦點跟隨）。舊的 `initialTab: 'interaction'` 仍會開到第三分頁。
- 新增 `RoleComposition.vue`（組合列：主數位人、已啟用 N／5、套用組合、加入專門數位人；成員名單含已啟用／交接已關閉／未啟用 · 保留設定／不相容＋伺服器回傳的原因／空位；所選成員編輯器；交接路線；角色轉場）、`RoleHandoffFields.vue`（每位成員含主數位人相同的專長介紹、交接規則、交接說明中英）、`RoleTopology.vue`（生效成員兩兩相連的網狀圖，節點可用鍵盤選取）、`RoleTransitions.vue`（預設＋個別方向，含轉場影片上傳／刪除）、`web/src/roleComposition.js`（每個範圍一份草稿、儲存計畫、與伺服器版本合併）。
- 主數位人、每位專門數位人、角色轉場各自儲存並各自顯示未儲存／儲存中／失敗；版本衝突只標在那一位（可「載入最新版本」或「以草稿覆寫」），其他位的草稿保留。改啟用或換設定檔才附 `expected_composition_revision`；換主數位人遇到 `disable_required` 會先確認再帶 `confirm_disable` 重送。天氣工具同時只限一位（其他位鎖定並可前往持有者），場域預設地點的「台」存檔前改「臺」。
- 「交接試算」區塊已就位但停用（`#rc-dry-run`：目前角色下拉列出生效成員、訪客問題、「試算由誰回答」按鈕，皆 disabled，標示「尚未開放」）；05 接 `POST /api/profiles/composition/dry-run` 時只需解除停用並顯示結果。
- 數位人設定檔分頁只存設定檔清單（`PUT /api/profiles {profiles, expected_profiles_revision}`），清單標示主數位人／專門 #n／未加入組合，組合中的設定檔不能直接刪除；設定檔編輯器的「聲音與工具」改名「聲音」並移除天氣勾選。閒置招呼頁也改用設定檔清單儲存。

**移除的暫時相容層**（01 Comments）
- A1 `legacy_pair_view`：`ProfileStore` 讀寫只回傳 version 2 的鍵（不再附 `enabled`／`pair`／`handoff`／`weather`／`transitions` 與設定檔 `tools`）。移除前 grep 確認 `src/`、`scripts/` 沒有讀這些鍵（`routing.py`、`eval_llm_quality.py` 已在 02 改讀 `composition`）。
- A2 `ProfileStore.save`、`composition.apply_legacy_view`、`PUT /api/profiles {library, expected_revision}`：舊格式現在回 400，檔案不變。
- A6 `canonical()` 不再丟掉 v2 檔中的兩角色鍵與設定檔 `tools`（會被驗證拒絕），`referenced_media` 只看預設與個別方向轉場。
- A7 `validate_profile` 收到 `tools` 回 400（`field: "tools"`，請改在角色組合指定）。
- 未動：v1 檔轉換（`migrate_v1`）與首次建立時用 v1 預設值轉換種子資料，這兩者是轉換而非相容層。

**測試**
- Python：改寫原本走 A2 整份儲存的測試改用 `save_profiles`／`save_member`／`save_main`／`save_transitions`（`test_avatar_profiles.py`、`test_voice_library.py`、`test_llm_endpoints.py`、`test_tts_engine_cleanup.py`、`test_role_coordinator.py`、`test_default_voice.py`）；`test_role_composition.py` 以新測試取代 A1／A2 測試：設定檔帶 `tools` 被拒、v2 檔含兩角色鍵被拒、`referenced_media` 不讀舊鍵、HTTP 舊整份儲存回 400 而設定檔清單儲存與版本衝突正常、沒有成員時只剩主數位人。
- 前端：新增 `web/tests/role-composition.test.js` 8 項（名單狀態與伺服器不相容原因、各自儲存只送自己的修訂、衝突只影響那一位並可覆寫、主數位人交接說明必填與交接開關、天氣工具唯一與臺字、加入成員預設未啟用、轉場重複方向與修訂、交接試算停用且不呼叫路由）；`role-composition-model.test.js` 6 項；改寫 `profile-settings`、`settings-organization`（三分頁、方向鍵、無返回控制台、左側選單內容）、`idle-greeting-settings`、`defaultPromptSettings` 對應的測試。
- 版面回歸（`settings-layout.test.js`）與對比（`console-visual.test.js`）的狀態清單加入組合分頁（主數位人、成員、不相容成員、加入）與第三分頁，1920×1080／1280×720、淺色／深色皆通過。
- CI（worktree）：`ruff check .`、`pyright` 0 錯誤、`scripts/check-integration.py` 通過；`pytest` 1450 passed、3 skipped、2 failed（已知 worktree 基線：`test_real_pdf_pages_are_validated_rendered_and_released`、`test_greeting_only_profile_apply_keeps_playing_media_and_avoids_rebinding`）；`npm run lint` 通過、`npm test` 256 項全過、`npm run build` 通過。

**截圖**（headless Chrome，`tests/fixtures/settingsApi.js` 假資料：主數位人＋氣象員〔天氣〕、展覽導覽員、交通導覽〔不相容〕、客服小幫手〔未啟用〕）於 `.scratch/role-composition/screenshots/`：
  - `compose`：[1920x1080 light](../screenshots/roles-compose-1920x1080-light.png)、[1920x1080 dark](../screenshots/roles-compose-1920x1080-dark.png)、[1280x720 light](../screenshots/roles-compose-1280x720-light.png)、[1280x720 dark](../screenshots/roles-compose-1280x720-dark.png)
  - `compose-member`：[1920x1080 light](../screenshots/roles-compose-member-1920x1080-light.png)、[1920x1080 dark](../screenshots/roles-compose-member-1920x1080-dark.png)、[1280x720 light](../screenshots/roles-compose-member-1280x720-light.png)、[1280x720 dark](../screenshots/roles-compose-member-1280x720-dark.png)
  - `compose-incompatible`：[1920x1080 light](../screenshots/roles-compose-incompatible-1920x1080-light.png)、[1920x1080 dark](../screenshots/roles-compose-incompatible-1920x1080-dark.png)、[1280x720 light](../screenshots/roles-compose-incompatible-1280x720-light.png)、[1280x720 dark](../screenshots/roles-compose-incompatible-1280x720-dark.png)
  - `compose-add`：[1920x1080 light](../screenshots/roles-compose-add-1920x1080-light.png)、[1920x1080 dark](../screenshots/roles-compose-add-1920x1080-dark.png)、[1280x720 light](../screenshots/roles-compose-add-1280x720-light.png)、[1280x720 dark](../screenshots/roles-compose-add-1280x720-dark.png)
  - `interaction`：[1920x1080 light](../screenshots/roles-interaction-1920x1080-light.png)、[1920x1080 dark](../screenshots/roles-interaction-1920x1080-dark.png)、[1280x720 light](../screenshots/roles-interaction-1280x720-light.png)、[1280x720 dark](../screenshots/roles-interaction-1280x720-dark.png)

**留待實機驗證**
- 以現場 `avatar_profiles.yaml` 開啟組合分頁：各成員狀態、不相容原因與現場一致；兩個控制台同時改同一位成員，確認只有那一位顯示衝突。
- 換主數位人遇到不相容成員時的確認流程與停用結果；「套用組合」後舞台採用新組合。
- README 的「首版即時組合使用兩位…」等執行期段落仍是兩角色敘述，留給 06 的文件更新。
