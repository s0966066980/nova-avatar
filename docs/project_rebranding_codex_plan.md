# <NEW_PROJECT_NAME> 重新品牌化與授權合規修改規格

> 適用專案：`s0966066980/Linly-Talker-Stream`  
> 目標：將目前專案正式整理為獨立品牌專案，同時保留必要的 Apache-2.0 / MIT / 第三方授權義務，並讓 Codex 可依本文件直接執行修改。  
> 建議最終定位：**An independently maintained derivative project originally derived from Kedreamix/Linly-Talker-Stream.**

---

## 0. Codex 執行原則

Codex 在修改前必須遵守以下原則：

1. **不要使用全域取代直接刪除 `Kedreamix` / `Linly-Talker-Stream`。**
2. 先區分內容屬於：
   - 法律 attribution
   - UI / Branding
   - package metadata
   - third-party source
   - documentation / demo
3. `LICENSE` 原則上不修改。
4. `NOTICE` 必須保留 upstream attribution。
5. `MuseTalk` / `Wav2Lip` / `LiveTalking` 不可被當成自己的品牌名稱重新命名。
6. `Wav2Lip` 必須被標示為 **Research / Non-commercial**，或在商業發行版中移除。
7. 新增 `THIRD_PARTY_NOTICES.md`。
8. 對 inherited + modified source 加入 `Modified by ...`。
9. 對真正自行新增的 source 才使用自己的 copyright header。
10. 完成後執行品牌與授權 audit。

---

# 1. 修改分類

## 🔴 一定不能刪

以下內容不得因重新品牌化而移除：

- Root `LICENSE`
- Apache License 2.0 條款
- 適用的 Kedreamix attribution
- `NOTICE` 中仍適用的上游 attribution
- LiveTalking attribution（若相關 source 仍存在）
- MuseTalk MIT License notice
- MuseTalk copyright
- Wav2Lip 的 upstream 使用限制
- 既有 source 內仍適用的第三方 copyright / license notice
- 第三方模型 / 權重的 license 限制

---

## 🟢 可以刪 / 可以完全換掉

以下內容可以完全換成自己的品牌：

- GitHub Repository 名稱
- Repository description
- README 主標題
- README 專案介紹
- Logo
- UI 主品牌名稱
- Browser `<title>`
- HTML meta description
- npm package name
- Python package name
- CLI 顯示名稱
- clone URL
- README 截圖
- upstream Star History
- upstream demo 宣傳內容
- UI 內 `Linly-Talker-Stream` 字樣
- 測試 prompt 內 `Linly-Talker-Stream` 字樣
- `pyproject.toml` 中的 project author / maintainer
- `web/package.json` 中的 name / description

---

## 🟡 建議改

- `NOTICE`：改成「你的專案 + upstream attribution」
- `README.md`：改成完整獨立品牌專案說明
- `THIRD_PARTY_NOTICES.md`：新增
- inherited source header：加入 `Modified by`
- MuseTalk license：建立獨立 third-party license 檔
- Wav2Lip：標記 research-only
- `.scratch/`：移出正式 repo 或改放 `docs/benchmarks/`
- `docs/`：移除品牌耦合檔名
- GitHub fork network：最後才 detach

---

# 2. 建議最終專案結構

```text
<NEW_PROJECT_NAME>/
├── LICENSE
├── NOTICE
├── THIRD_PARTY_NOTICES.md
├── README.md
├── AGENTS.md
├── CONTEXT.md
│
├── config/
├── docs/
├── scripts/
├── src/
│   ├── asr/
│   ├── avatars/
│   │   ├── musetalk/
│   │   ├── wav2lip/
│   │   ├── ernerf/
│   │   └── talkinggaussian/
│   ├── llm/
│   ├── server/
│   ├── tts/
│   ├── utils/
│   └── vad/
│
├── tests/
└── web/
```

---

# 3. `README.md`

## 3.1 可以刪除

刪除或替換：

```text
# Linly-Talker-Stream
Linly-Talker-Stream/
git clone .../Linly-Talker-Stream.git
cd Linly-Talker-Stream
```

以及：

- 原專案 Star History
- 原專案 logo
- 原專案宣傳文字
- 原專案 demo 導向
- upstream clone URL
- 「本專案就是 Linly-Talker-Stream」類型敘述

---

## 3.2 建議新結構

```md
# <NEW_PROJECT_NAME>

Real-time full-duplex conversational digital human framework.

## Overview
## Features
## Architecture
## Supported Engines
## Quick Start
## Configuration
## Web Console
## Streaming Reply Pipeline
## Testing & Validation
## Commercial Usage
## Third-Party Components
## References and Attribution
## License
```

---

## 3.3 建議 References

```md
## References and Attribution

This project was originally derived from Kedreamix/Linly-Talker-Stream
and has since been substantially redesigned and independently maintained.

Relevant upstream and third-party projects include:

- Kedreamix/Linly-Talker-Stream
- LiveTalking
- MuseTalk
- Wav2Lip
- Whisper
- FunASR

See `NOTICE` and `THIRD_PARTY_NOTICES.md` for licensing details.
```

---

# 4. `LICENSE`

## 分類：🔴 一定不能刪

### Codex 指令

- 保持目前 Apache License 2.0 全文。
- 不要加入品牌文案。
- 不要把 Kedreamix copyright 直接替換成自己的名字。
- 不要將 LICENSE 改成自訂條款。

### 驗收

```bash
git diff -- LICENSE
```

預期：**無修改**。

---

# 5. `NOTICE`

## 分類：🔴 必須保留，但建議重寫

建議內容：

```text
NOTICE
======

<NEW_PROJECT_NAME>
Copyright (c) 2026 <YOUR_NAME_OR_ORGANIZATION>

This project is an independently maintained derivative work based in part on:

Linly-Talker-Stream
Copyright (c) Kedreamix
Licensed under the Apache License, Version 2.0.

Portions of the real-time avatar and WebRTC architecture are based on or
adapted from LiveTalking.
Licensed under the Apache License, Version 2.0.

This project also contains, integrates, adapts, or interfaces with third-party
software and models including MuseTalk, Wav2Lip, Whisper, FunASR and others.

See THIRD_PARTY_NOTICES.md for additional license and attribution information.
```

### 驗收

`NOTICE` 必須至少仍包含：

```text
Kedreamix
Linly-Talker-Stream
LiveTalking
Apache License
```

若 source 中仍包含這些來源。

---

# 6. 新增 `THIRD_PARTY_NOTICES.md`

## 分類：🟡 強烈建議新增

建議：

```md
# Third-Party Notices

## Linly-Talker-Stream
- Role: upstream project
- License: Apache-2.0
- Source: https://github.com/Kedreamix/Linly-Talker-Stream

## LiveTalking
- Role: real-time avatar / WebRTC architecture reference and adapted code
- License: Apache-2.0
- Source: https://github.com/lipku/LiveTalking

## MuseTalk
- Role: lip-sync avatar engine
- Code License: MIT
- Commercial use: permitted by upstream
- Source: https://github.com/TMElyralab/MuseTalk
- Note: bundled third-party models retain their own licenses.

## Wav2Lip
- Role: optional lip-sync engine
- Usage classification: research / academic / personal
- Commercial use: not permitted for the upstream open-source version
- Source: https://github.com/Rudrabha/Wav2Lip

## Whisper
- Role: speech / audio feature component
- License: MIT
- Source: https://github.com/openai/whisper

## FunASR
- Role: ASR
- License: verify the exact version and model license used by this project

## GPT-SoVITS / CosyVoice / IndexTTS2
- Role: optional TTS backends
- License: verify each exact distribution / model before commercial packaging
```

---

# 7. `pyproject.toml`

目前應修改：

```toml
name = "linly-talker-stream"
description = "Linly-Talker-Stream..."
authors = [
    { name = "Kedreamix", email = "kedreamix@gmail.com" }
]
```

改為：

```toml
[project]
name = "<new-project-slug>"
version = "1.0.0"
description = "Real-time full-duplex conversational digital human framework"
readme = "README.md"
requires-python = ">=3.10, <3.12"

license = { text = "Apache-2.0" }

authors = [
    { name = "<YOUR_NAME_OR_ORG>" }
]

maintainers = [
    { name = "<YOUR_NAME_OR_ORG>" }
]

[project.urls]
Repository = "https://github.com/s0966066980/<NEW_REPOSITORY>"
```

## 分類

- `name`：🟢 可改
- `description`：🟢 可改
- `authors`：🟢 可改
- `license`：🔴 保持 Apache-2.0

---

# 8. `web/package.json`

建議：

```json
{
  "name": "<new-project-slug>-web",
  "version": "1.0.0",
  "description": "<NEW_PROJECT_NAME> Web frontend",
  "author": "<YOUR_NAME_OR_ORG>",
  "license": "Apache-2.0"
}
```

Dependencies 不需因 rebrand 改名。

---

# 9. `web/index.html`

修改：

```html
<html lang="zh-TW">
```

```html
<meta
  name="description"
  content="<NEW_PROJECT_NAME> - 全雙工即時互動數位人系統"
/>
```

```html
<title><NEW_PROJECT_NAME></title>
```

console：

```js
console.log('✅ <NEW_PROJECT_NAME> 頁面載入完成')
```

---

# 10. `web/src/App.vue`

## 10.1 Header

不要刪 upstream attribution。

改為：

```html
<!--
Derived from Kedreamix/Linly-Talker-Stream.
Copyright [Linly-talker-stream@kedreamix].
Licensed under Apache-2.0.

Substantially modified by <YOUR_NAME_OR_ORG>, 2026.
See LICENSE and NOTICE.
-->
```

---

## 10.2 Branding

將：

```html
<span>Linly-Talker-Stream</span>
```

改為：

```html
<span><NEW_PROJECT_NAME></span>
```

---

## 10.3 測試 Prompt

將：

```js
quickSend('請整理 Linly-Talker-Stream 三大優勢並輸出看板')
```

改為：

```js
quickSend('請整理 <NEW_PROJECT_NAME> 三大核心技術優勢並輸出看板')
```

其他所有 UI / demo prompt 中的 Linly 品牌皆比照處理。

---

# 11. Locales

處理：

```text
web/src/locales/zh-TW.js
web/src/locales/zh-CN.js
web/src/locales/en-US.js
```

例如：

```js
header: {
  title: '<NEW_PROJECT_NAME>',
  subtitle: '全雙工即時互動數位人'
}
```

## 注意

以下第三方名稱不要重新品牌：

```text
MuseTalk
Wav2Lip
Whisper
FunASR
Edge TTS
CosyVoice
GPT-SoVITS
IndexTTS2
```

---

# 12. 其他 UI 檔案

掃描：

```text
web/src/components/*
web/src/composables/*
web/stage.html
web/answer-board.prototype.html
web/board-interactive-test.html
web/console-uiux-prototype.html
```

### 可改

若字串用途是：

- title
- label
- placeholder
- about
- footer
- console message
- sample prompt

則改成新品牌。

### 不可直接刪

若內容是：

- copyright
- license
- derived from
- based on

則保留並改成正確 attribution。

---

# 13. Source Header 策略

## 13.1 類型 A：由 Linly 繼承後修改

```python
# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by <YOUR_NAME_OR_ORG>, 2026.
# See LICENSE and NOTICE for details.
```

適用例：

```text
src/asr/*
src/avatars/base.py
src/avatars/audio_stream_handler.py
src/avatars/factory.py
src/server/app.py
src/server/server.py
src/server/state.py
src/server/routes/*
src/tts/base.py
src/tts/factory.py
src/tts/engines/*
src/utils/*
web/src/components/*
web/src/composables/*
```

---

## 13.2 類型 B：自行新增檔案

如果確認完全自行撰寫：

```python
# Copyright (c) 2026 <YOUR_NAME_OR_ORG>
# SPDX-License-Identifier: Apache-2.0
```

目前可能屬於這一類的檔案：

```text
src/server/reply_streaming/*
src/vad/*
src/llm/answer_board.py
src/llm/history.py
src/llm/llamacpp.py
src/llm/prompts.py
src/llm/response_protocol.py
src/llm/router.py
src/llm/rules.py
src/server/runtime_settings.py
src/server/voice_session.py
src/avatars/builder.py
src/avatars/catalog.py
src/avatars/mouth_quality.py
```

> 注意：Git status 為 `added` 不代表法律上一定原創。  
> 若檔案是從其他 repo copy 進來，仍需保留來源 license。

---

## 13.3 類型 C：第三方 source

### MuseTalk

```python
# Portions derived from MuseTalk.
# Copyright (c) 2024 Tencent Music Entertainment Group.
# Licensed under the MIT License.
#
# Modified for integration with <NEW_PROJECT_NAME>, 2026.
```

### Wav2Lip

```python
# Contains code derived from the Wav2Lip open-source project.
# Upstream non-commercial usage restrictions apply.
# See THIRD_PARTY_NOTICES.md.
#
# Modified for integration with <NEW_PROJECT_NAME>, 2026.
```

---

# 14. MuseTalk

目錄：

```text
src/avatars/musetalk/
```

## 一定保留

- MuseTalk MIT License
- Tencent Music Entertainment Group copyright
- 其他 bundled third-party license

建議新增：

```text
third_party/licenses/MuseTalk-LICENSE.txt
```

內容放 MuseTalk 官方 LICENSE。

---

# 15. `src/avatars/musetalk/pyproject.toml`

將：

```toml
name = "linly-talker-musetalk"
description = "MuseTalk avatar module for Linly-Talker-Stream"
```

改為：

```toml
name = "<new-project-slug>-musetalk"
description = "MuseTalk avatar integration for <NEW_PROJECT_NAME>"
```

不要把 MuseTalk copied source 宣告成「全部 Apache-2.0」。

---

# 16. Wav2Lip

目錄：

```text
src/avatars/wav2lip/
```

目前應視為 **Research / Non-commercial component**。

---

# 17. `src/avatars/wav2lip/pyproject.toml`

必改：

```toml
name = "linly-talker-stream-wav2lip"
license = "Apache-2.0"
authors = [{ name = "Kedreamix" }]
```

建議：

```toml
[project]
name = "<new-project-slug>-wav2lip-research"
version = "0.1.0"
description = "Research-only Wav2Lip avatar integration for <NEW_PROJECT_NAME>"

license = {
  text = "Contains Wav2Lip-derived components subject to upstream non-commercial terms; see THIRD_PARTY_NOTICES.md"
}
```

不要再讓此 module 看起來像完整 Apache-2.0 commercial-friendly package。

---

# 18. Wav2Lip UI

如果 UI 保留 Wav2Lip：

```text
Wav2Lip (Research / Non-commercial)
```

不要只顯示：

```text
Wav2Lip
```

商業版建議：

```text
MuseTalk -> Supported / Commercial
Wav2Lip -> Optional / Research-only
```

---

# 19. LiveTalking

若目前 source header 有：

```text
Based on LiveTalking
```

且相關 implementation 仍存在：

- 保留 attribution
- 保留 Apache-2.0 說明
- 不要把 LiveTalking 名稱從 NOTICE 全部刪除

---

# 20. `docs/`

以下可全面重新品牌：

```text
docs/adr/*
docs/project-overview.html
docs/project-status.md
docs/agents/*
docs/MuseTalk_seamless_transitions.md
docs/MuseTalk_seamless_transitions2.md
```

建議改：

```text
docs/Linly_Talker_Stream_Console_Prompt_Centralization_Plan.md
```

為：

```text
docs/console-prompt-centralization-plan.md
```

避免文件名稱繼續和舊品牌綁死。

---

# 21. `CONTEXT.md`

改成新專案品牌。

若此檔是你新增：

```md
<!--
Copyright (c) 2026 <YOUR_NAME_OR_ORG>
SPDX-License-Identifier: Apache-2.0
-->
```

---

# 22. `AGENTS.md`

改成：

- 新專案名稱
- Codex 修改規範
- License guardrails
- 測試流程
- 不能刪的 attribution 規則

建議額外加入：

```md
## License Guardrails

- Never remove LICENSE.
- Never remove applicable upstream copyright notices.
- Never classify Wav2Lip as commercially permitted.
- Keep MuseTalk MIT attribution.
- New files may use the project Apache-2.0 header only when independently authored.
```

---

# 23. `config/*.yaml`

處理：

```text
config/config.yaml
config/config_musetalk.yaml
config/config_wav2lip.yaml
config/config_ernerf.yaml
config/config_talkinggaussian.yaml
```

## 可改

- Linly branding
- assistant identity
- title
- prompt
- comments
- URLs

## 不要改

engine identifier：

```text
musetalk
wav2lip
ernerf
talkinggaussian
```

---

# 24. `.scratch/`

建議正式版移除：

```text
.scratch/answer-board/
.scratch/reply-voice-streaming/
```

如需保留正式 evidence，改放：

```text
docs/benchmarks/
artifacts/validation/
```

---

# 25. Repository Rebranding

最後才做：

```text
Repository rename
Description update
Topics update
Homepage update
```

建議 Topics：

```text
digital-human
virtual-avatar
webrtc
musetalk
speech-to-text
text-to-speech
llm
realtime
streaming
```

---

# 26. GitHub Fork Network

所有程式與授權修改完成、測試通過後，再考慮：

```text
Settings
→ General
→ Danger Zone
→ Leave fork network
```

注意：

> Detach fork network 不會消除原始著作權與 license 義務。

---

# 27. 最終 Audit

## 27.1 舊品牌搜尋

```bash
git grep -n -I -E \
'Linly-Talker-Stream|Linly_Talker_Stream|linly-talker|Kedreamix|kedreamix'
```

允許存在的位置：

```text
NOTICE
THIRD_PARTY_NOTICES.md
README References
inherited source headers
```

UI / package / title 不應再出現舊品牌。

---

## 27.2 Upstream URL

```bash
git grep -n -I 'github.com/Kedreamix'
```

預期主要存在：

```text
NOTICE
THIRD_PARTY_NOTICES.md
README References
source legal headers
```

---

## 27.3 第三方元件

```bash
git grep -n -I -E \
'Wav2Lip|MuseTalk|LiveTalking|Whisper|FunASR'
```

這些不應追求清零。

它們必須保留在：

- engine selection
- docs
- license notices
- third-party notices
- relevant source headers

---

# 28. 測試

至少執行：

```bash
uv run python scripts/check-integration.py
```

```bash
uv run pytest
```

```bash
cd web
npm test
npm run build
```

若目前專案測試命令不同，Codex 應依現有 `README.md` / `package.json` / CI 調整。

---

# 29. Codex 任務拆分

建議不要一次修改全部。

## Phase 1 — Legal / Metadata

- [ ] 保留 LICENSE
- [ ] 重寫 NOTICE
- [ ] 新增 THIRD_PARTY_NOTICES.md
- [ ] 新增 `third_party/licenses/MuseTalk-LICENSE.txt`
- [ ] 修正 root pyproject metadata
- [ ] 修正 MuseTalk pyproject metadata
- [ ] 修正 Wav2Lip pyproject metadata

---

## Phase 2 — Branding

- [ ] README
- [ ] web/package.json
- [ ] web/index.html
- [ ] App.vue
- [ ] locales
- [ ] components
- [ ] config prompts
- [ ] CONTEXT.md
- [ ] AGENTS.md

---

## Phase 3 — Source Attribution

- [ ] inherited files 加 Modified by
- [ ] self-authored files 加 project SPDX header
- [ ] MuseTalk derived files 加 MIT attribution
- [ ] Wav2Lip derived files加 non-commercial notice

---

## Phase 4 — Cleanup

- [ ] docs rename
- [ ] 移除 `.scratch/`
- [ ] 清除舊品牌 UI 字串
- [ ] 清除 upstream promotional copy
- [ ] 更新 clone URL

---

## Phase 5 — Validation

- [ ] git grep old branding
- [ ] git grep upstream references
- [ ] license audit
- [ ] pytest
- [ ] web tests
- [ ] production build
- [ ] smoke test
- [ ] diff review

---

# 30. Codex 驗收條件

完成後必須同時滿足：

### Branding

- [ ] UI 不再顯示 `Linly-Talker-Stream`
- [ ] Browser title 不再顯示舊品牌
- [ ] README 主標題為 `<NEW_PROJECT_NAME>`
- [ ] npm / Python package metadata 為新品牌
- [ ] 測試 prompt 不再硬編碼舊品牌

### License

- [ ] LICENSE 仍存在
- [ ] NOTICE 仍有 Kedreamix attribution
- [ ] MuseTalk MIT attribution 存在
- [ ] Wav2Lip 非商業限制存在
- [ ] LiveTalking attribution 在仍相關時存在

### Commercial

- [ ] MuseTalk 標記為 supported / commercial-capable
- [ ] Wav2Lip 標記為 research / non-commercial
- [ ] 商業 build 不 bundle Wav2Lip，或至少明確禁止其商業使用

### Engineering

- [ ] Python tests pass
- [ ] Web tests pass
- [ ] Web production build pass
- [ ] existing runtime behavior 不因 rebrand 破壞

---

# 31. 建議 Git Commit 分組

```text
chore: establish legal attribution and third-party notices
chore: rebrand project metadata
feat: rebrand web console and localization
docs: rewrite project readme for independent branding
docs: add commercial and third-party licensing guidance
chore: add source modification notices
chore: classify wav2lip as research-only
chore: clean legacy branding and scratch artifacts
```

---

# 32. 建議最終 README 專案定位

推薦：

```text
<NEW_PROJECT_NAME> is an independently maintained real-time digital human
framework for full-duplex voice interaction, streaming LLM responses,
multi-avatar rendering, and WebRTC delivery.

The project was originally derived from Kedreamix/Linly-Talker-Stream and has
since undergone substantial architectural and implementation changes.
```

不要寫：

```text
This project is completely original.
```

也不要寫：

```text
All code is owned exclusively by <YOUR_NAME>.
```

目前專案仍包含 upstream 與 third-party source。

---

# 33. 最終目標

最終使用者應看到：

```text
GitHub repo
README
Web UI
Browser title
Package metadata
Documentation
```

全部是：

```text
<NEW_PROJECT_NAME>
```

只有在：

```text
NOTICE
THIRD_PARTY_NOTICES.md
References
Inherited source headers
Third-party modules
```

才會看到：

```text
Linly-Talker-Stream
Kedreamix
LiveTalking
MuseTalk
Wav2Lip
```

這是目前此專案最合理的重新品牌化與授權合規結構。
