<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 來源歸屬稽核

更新日期：2026-11-28

這是 Nova Avatar 各原始碼根目錄的分類紀錄。它不會對程式碼、模型、權重、聲音、資料集或服務重新授權；
適用時，仍以根目錄的 [LICENSE](../../LICENSE)、[NOTICE](../../NOTICE) 與
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) 為準。

## 分類

| 原始碼根目錄 | 分類 | 必要處理 | 目前動作 |
| --- | --- | --- | --- |
| `core/nova_core/server/`、`core/nova_core/config/`、`services/llm/nova_llm/`、`services/tts/nova_tts/`、`core/nova_core/vad/`、`services/stt/nova_stt/`、`web/`、`scripts/` | 繼承並大幅修改的 Nova Avatar 應用程式碼 | 保留適用的 Linly-Talker-Stream／LiveTalking 歸屬，並加上明確的修改聲明。 | 逐檔稽核檔頭後才能修改；不得整批取代。 |
| `avatar/nova_render/musetalk/` | 衍生自 MuseTalk 的整合，加上 Nova Avatar 編排 | 衍生程式碼保留 Tencent Music Entertainment Group 版權與 MIT 歸屬。模型與依賴套件需另行審查。 | 已保留本機的 MuseTalk 授權副本。逐檔來源審查仍未完成。 |
| `third_party/licenses/` | 第三方授權聲明 | 保持原樣，不改名。 | 已有 MuseTalk MIT 聲明，以及 Wav2Lip 非商用限制紀錄（針對已移除的整合）。 |
| `avatar/nova_render/scene/`、`services/llm/nova_llm/ragflow/`、`integrations/ragflow/` | Nova Avatar 自行撰寫的整合程式碼 | 使用 Nova Avatar Apache-2.0 SPDX 檔頭；RAGFlow 本身是外部服務，不是隨附的原始碼。 | 檔案皆帶有 Nova Avatar 檔頭。 |
| `docs/`、`tests/`、各層的 `tests/` 與 `scripts/`、各層的 `pyproject.toml` 與 `README.md`，以及新增的 Nova Avatar 專屬檔案 | Nova Avatar 自行撰寫，除非檔案標明其他來源 | 確認沒有複製第三方原始碼後，才使用 Nova Avatar Apache-2.0 SPDX 檔頭。搬移或修改過的繼承檔案保留上游聲明。 | 新增的稽核、流程、軟體組合、設定檔、各層清單與 README 檔案皆使用 Nova Avatar 歸屬。 |

## 處理層資料夾

2026-11-27（處理層拆分工單 09），原本的 `src/` 以 `git mv` 搬移、不更動檔頭，分成每個處理層一個資料夾
（[ADR 0027](../adr/0027-split-code-by-processing-layer.md)）：

| 原路徑 | 現路徑 |
| --- | --- |
| `src/server`、`src/vad`、`src/profiles`、`src/config`、`src/greetings`、`src/utils` | `core/nova_core/` |
| `src/asr` | `services/stt/nova_stt/` |
| `src/llm`、`src/ragflow`、`src/web_search` | `services/llm/nova_llm/`（`ragflow/`、`web_search/`） |
| `src/tts` | `services/tts/nova_tts/` |
| `src/avatars`、`src/scene` | `avatar/nova_render/`（`musetalk/`、`scene/`） |

記錄在舊路徑下的分類，適用於這些檔案在新路徑的位置。

## 證據與邊界

- `NOTICE` 保留 Kedreamix、Linly-Talker-Stream 與 LiveTalking 的歸屬。
- `THIRD_PARTY_NOTICES.md` 記錄 MuseTalk 的 MIT 邊界與 Wav2Lip 的非商用限制；Wav2Lip 整合本身已於 2026-11-24 移除。
- `config/config_commercial.yaml` 使用 MuseTalk。它是部署的起點，不代表有權散布任何成品。

## 後續的來源處理

不要在第三方（vendor）目錄樹上整批加上相同檔頭。日後每個被修改的原始檔，先分類為
繼承並修改、Nova Avatar 自行撰寫、衍生自 MuseTalk、衍生自 Wav2Lip，或其他第三方／產生的程式碼，
再依分類保留或加上對應的來源聲明。

逐檔來源審查是持續進行的維護工作；這份根目錄層級的稽核並不代表它已完成。

## 2026-10-29：獨立對話

對話協調器、呈現模組、延後套用的資源設定、相關測試與領域文件，是 Nova Avatar 自行撰寫的 Apache-2.0 檔案。
繼承而來的語音／WebRTC 生命週期、伺服器狀態、LLM 服務與網頁應用程式檔案，保留原有的上游與修改聲明。
這次變更沒有修改任何隨附的第三方原始碼或授權。

待送出輸入的插話修正，保留繼承的 App 與語音工作階段聲明。共用的輸入框、回歸測試與對話文件是
Nova Avatar 自行撰寫的 Apache-2.0 檔案；沒有更動任何第三方原始碼。

角色反向交接的變更，更新了 Nova Avatar 自行撰寫的設定檔路由、協調、持久化、預設內容、設定介面與回歸測試。
繼承的語音工作階段保留原有的上游與修改聲明。沒有更動任何隨附的第三方程式碼、模型或授權聲明。

控制台閒置重置的更新，保留繼承的語音工作階段與設定面板聲明，並更新 Nova Avatar 自行撰寫的對話協調、
工作階段中繼資料、記憶介面、測試與文件。沒有更動任何第三方程式碼或授權聲明。

天氣情境容量修正，修改的是 Nova Avatar 自行撰寫的天氣提示傳輸與回歸測試。驗證用資料中的來源事實保留
CWA 來源中繼資料；沒有更動任何模型權重、第三方實作或授權聲明。

控制台版面更新，保留繼承的 App 與設定面板聲明。控制台樣式表帶有明確的修改聲明，並指向根目錄的
LICENSE 與 NOTICE。對話與語音測試面板、行為回歸測試、設計筆記與版面預覽，保留 Nova Avatar Apache-2.0 檔頭。
沒有更動任何第三方實作、模型、權重或授權；Wav2Lip 的 Research / Non-commercial 限制紀錄仍保留。
