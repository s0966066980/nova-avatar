# Nova Avatar 合法化、重新品牌化與專案整理計畫

> Repository: `https://github.com/s0966066980/nova-avatar`  
> Baseline commit: `38322a587f78215ce3dfcc0e4c46f47fb29a4ab9`  
> Commit message: `feat: rebrand project as Nova Avatar`  
> 文件用途：作為 Codex / 維護者後續修改、授權整理、README 重構、商用版本切分與發行驗收的執行計畫。  
> 注意：本文件屬於工程與授權整理建議，不構成法律意見。

---

# 1. 計畫目標

本計畫不是單純將 `Linly-Talker-Stream` 改名成 `Nova Avatar`，而是將目前專案整理成：

1. **獨立維護的 Nova Avatar 專案品牌**
2. **保留必要 upstream attribution**
3. **清楚區分 Nova Avatar 自有程式與第三方程式**
4. **清楚標示商用可用 / 非商用 / 尚待確認元件**
5. **讓使用者知道專案實際提供哪些功能、引擎、套件與外部軟體整合**
6. **讓 Codex 可以依階段修改，不會因全域 rebrand 破壞授權資訊**
7. **建立可測試、可發行、可商用整理的專案結構**

最終專案定位：

> **Nova Avatar is an independently maintained derivative project originally based on Kedreamix/Linly-Talker-Stream, with substantial modifications to real-time conversation orchestration, streaming replies, voice session control, runtime configuration and avatar integration.**

---

# 2. 重要原則：不需要保留特定 rebrand commit 才合法

以下 commit：

```text
38322a587f78215ce3dfcc0e4c46f47fb29a4ab9
feat: rebrand project as Nova Avatar
```

**本身不是法律上必須存在的 commit。**

Apache-2.0 不要求：

- 必須有 `rebrand` commit
- 必須保留某個 commit SHA
- 必須使用 Nova Avatar 名稱
- 必須保留完整 fork commit history 才能重新品牌
- 必須在 package metadata 將 upstream 作者設為目前作者

真正需要保留的是這個 commit 所建立的**合規結果**。

---

# 3. 目前這個 commit 中，哪些修改應保留

## 3.1 必須保留：Root LICENSE

目前 root：

```text
LICENSE
```

仍為 Apache License 2.0。

### 原則

不要因重新品牌化修改 Apache License 正文。

Apache-2.0 redistribution 主要要求包括：

- 提供 License copy
- 修改過的檔案需有明顯修改 notice
- 保留仍適用的 copyright / attribution notices
- 上游存在 NOTICE 時，衍生專案必須保留仍適用的 NOTICE attribution

### Codex 規則

```text
DO NOT rebrand LICENSE.
DO NOT remove upstream Apache-2.0 license text.
DO NOT replace upstream copyright information globally.
```

---

# 4. `NOTICE` 更新計畫

目前 `NOTICE` 已整理為 Nova Avatar 為主體，並保留：

- Nova Avatar
- HongXian0903
- Linly-Talker-Stream
- Kedreamix
- LiveTalking
- Apache-2.0
- MuseTalk
- Wav2Lip
- Whisper
- FunASR
- ER-NeRF
- TalkingGaussian

## 4.1 應保留的核心結構

```text
NOTICE
======

Nova Avatar
Copyright (c) 2026 HongXian0903

This project is an independently maintained derivative work based in part on:

Linly-Talker-Stream
Copyright (c) Kedreamix
Licensed under the Apache License, Version 2.0.

Portions of the real-time avatar and WebRTC architecture are based on or
adapted from LiveTalking.
Licensed under the Apache License, Version 2.0.
```

後面再列第三方元件及 `THIRD_PARTY_NOTICES.md`。

## 4.2 不建議做的事

不要將 NOTICE 改成：

```text
Nova Avatar
Copyright HongXian0903
All rights reserved.
```

如果專案仍包含上游來源，這種寫法會讓 attribution 不完整。

---

# 5. `THIRD_PARTY_NOTICES.md` 計畫

目前已建立：

```text
THIRD_PARTY_NOTICES.md
```

這個檔案不是 Apache-2.0 指定一定要叫這個名字，但非常建議保留。

它的用途是將：

- upstream project
- copied source
- integrated engine
- optional software
- model / weight / dataset restriction

集中管理。

---

# 6. 第三方元件授權分類

## 6.1 Linly-Talker-Stream

角色：

```text
Nova Avatar 原始 upstream
```

處理：

- 保留 Apache-2.0
- 保留 Kedreamix attribution
- 修改過的 inherited files 加 modified notice
- README 可以明確說「originally derived from」

---

## 6.2 LiveTalking

角色：

```text
real-time avatar / WebRTC architecture reference and adapted code
```

處理：

- 若 source 仍含 LiveTalking-derived implementation，保留 attribution
- 不要因 Nova Avatar rebrand 全域刪除 `LiveTalking`
- 適用檔案可保留：

```python
# Based on LiveTalking ...
```

---

## 6.3 MuseTalk

角色：

```text
主要 Avatar / lip-sync engine
```

目前建議定位：

```text
Supported
Commercial integration path
```

需保留：

```text
Copyright (c) 2024 Tencent Music Entertainment Group
MIT License
```

建議保留本機 license：

```text
third_party/licenses/MuseTalk-LICENSE.txt
```

注意：

MuseTalk code 可以依其 license 使用，但：

```text
模型
依賴
checkpoint
其他 bundled component
```

仍需依各自條款確認。

---

## 6.4 Wav2Lip

角色：

```text
optional lip-sync backend
```

目前 Nova Avatar 必須明確標記：

```text
Research / Non-commercial
```

上游公開版：

```text
research / academic / personal use only
commercial use prohibited
```

### 商業版規則

商業發行版：

```text
不得 bundle Nova Avatar repository 中的 Wav2Lip source
不得 bundle upstream Wav2Lip open-source weights
不得在 UI 預設啟用 Wav2Lip
```

推薦 UI：

```text
Wav2Lip (Research / Non-commercial)
```

而不是：

```text
Wav2Lip
```

---

## 6.5 TalkingGaussian / ER-NeRF / UltraLight

目前定位：

```text
Optional
License audit required
```

不能只因 Nova Avatar root 為 Apache-2.0 就視為可以商用。

需檢查：

- code license
- submodule license
- pretrained models
- datasets
- assets
- evaluation-only clauses

---

# 7. Source Header 修改策略

這部分是合法化最重要的工程修改之一。

不要全部檔案使用相同 header。

應先分類。

---

## 7.1 A 類：Inherited + Modified

條件：

```text
來源是 Linly-Talker-Stream
且 Nova Avatar 已修改
```

建議：

```python
# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
```

如另含 LiveTalking：

```python
# Based on LiveTalking.
# Copyright ...
# Licensed under Apache-2.0.
```

應保留。

---

## 7.2 B 類：Nova Avatar 自行新增

只有確認是自行撰寫的檔案，才使用：

```python
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
```

注意：

```text
git status 顯示 added
```

不等於法律上一定是原創。

若 source 是從其他 repository copy 進來，仍需使用第三方 attribution。

---

## 7.3 C 類：MuseTalk-derived source

建議：

```python
# Portions derived from MuseTalk.
# Copyright (c) 2024 Tencent Music Entertainment Group.
# Licensed under the MIT License.
#
# Modified for Nova Avatar integration, 2026.
```

---

## 7.4 D 類：Wav2Lip-derived source

建議：

```python
# Contains code derived from the Wav2Lip open-source project.
# Upstream non-commercial usage restrictions apply.
# See THIRD_PARTY_NOTICES.md.
#
# Modified for Nova Avatar integration, 2026.
```

---

# 8. 目前已完成的重新品牌化修改

Baseline commit 已完成的重要修改包括：

## 8.1 Project Name

由：

```text
Linly-Talker-Stream
```

改為：

```text
Nova Avatar
```

---

## 8.2 Repository / package slug

統一為：

```text
nova-avatar
```

---

## 8.3 Python project metadata

目前：

```toml
[project]
name = "nova-avatar"
version = "1.0.0"
description = "Real-time full-duplex conversational digital human framework"
requires-python = ">=3.10, <3.12"
license = { text = "Apache-2.0" }

authors = [
    { name = "HongXian0903" }
]

maintainers = [
    { name = "HongXian0903" }
]
```

---

## 8.4 Web frontend metadata

目前：

```json
{
  "name": "nova-avatar-web",
  "version": "1.0.0",
  "description": "Nova Avatar Web frontend",
  "author": "HongXian0903",
  "license": "Apache-2.0"
}
```

---

## 8.5 README

README 已改成：

```text
Nova Avatar
Real-time full-duplex conversational digital human framework
```

並說明：

```text
Nova Avatar 是獨立維護的衍生專案
最初源自 Kedreamix/Linly-Talker-Stream
```

這種寫法建議保留。

---

# 9. Nova Avatar 目前提供的主要功能

Nova Avatar 不是單一 MuseTalk wrapper。

目前架構提供的是完整：

```text
Voice Input
→ VAD
→ STT
→ LLM
→ Streaming Reply
→ TTS
→ Avatar Renderer
→ WebRTC Playback
```

---

# 10. 主要系統能力

## 10.1 WebRTC 全雙工互動

用途：

- 麥克風即時上行
- Avatar 音訊 / 影像即時下行
- 即時插話
- session lifecycle
- server-owned conversation turn
- playback commit

主要套件：

```text
aiohttp
aiortc
av
websockets
```

---

## 10.2 Server-side VAD

使用：

```text
Silero VAD
```

用途：

```text
自動偵測使用者開始說話
自動偵測使用者停止說話
避免固定錄音時間
支援免按式對話
```

安裝：

```bash
uv sync --extra vad
```

Python optional dependency：

```text
silero-vad>=5.1
```

---

# 11. STT / ASR 可使用軟體

目前 Nova Avatar 提供兩個主要 STT backend。

| 軟體 | 用途 | 狀態 |
|---|---|---|
| faster-whisper | Whisper-based local STT | Supported |
| FunASR | 中文 / 多語音辨識 backend | Supported / optional |

相關 Python：

```text
faster-whisper>=1.1
onnxruntime
transformers
torch
```

注意：

FunASR 及對應模型需依實際版本和模型 license 確認。

---

# 12. LLM 可使用軟體

目前支援：

## 12.1 Ollama

用途：

```text
Local LLM service
```

可搭配：

```text
Qwen
Llama
Gemma
其他 Ollama models
```

Nova Avatar 透過 API 與本機 Ollama 溝通。

---

## 12.2 llama.cpp

用途：

```text
本地 GGUF LLM inference
```

可使用：

```text
llama-server
OpenAI-compatible local endpoint
GGUF models
```

目前 Nova Avatar 可以：

- backend 按需啟動 llama-server
- 持有 process handle
- 正常停止時只清理由 Nova Avatar 自己啟動的 instance
- 不會依 port 猜測並殺掉其他外部 llama.cpp service

---

# 13. TTS 可使用軟體

目前 `src/tts/engines/` 實際存在：

```text
edge.py
cosyvoice.py
fish.py
indextts2.py
sovits.py
xtts.py
```

因此目前可整合：

| TTS | 用途 | 備註 |
|---|---|---|
| Edge TTS | 線上語音合成 | 目前主要穩定路徑之一 |
| GPT-SoVITS | 自訂聲音 / voice cloning 類型 TTS | optional |
| XTTS | 多語 / voice cloning TTS | optional |
| CosyVoice | 高品質中文 / 多語 TTS | optional |
| Fish TTS | TTS backend | optional |
| IndexTTS2 | TTS backend | optional |

README 另列：

```text
Fun-CosyVoice
```

若以獨立 runtime / service 使用，應在文件中與 `CosyVoice` adapter 的實際關係說明清楚。

---

# 14. Avatar 可使用軟體

目前 `src/avatars/` 提供：

```text
musetalk/
wav2lip/
ultralight/
ernerf/
talkinggaussian/
```

以及 Nova Avatar 自己的：

```text
builder.py
catalog.py
factory.py
mouth_quality.py
audio_stream_handler.py
```

---

## 14.1 MuseTalk

定位：

```text
主要推薦 Avatar backend
```

用途：

- 即時 lip-sync
- 數位人嘴型
- 音訊驅動影像
- segment transition
- mouth continuity

目前 Nova Avatar 還加入：

```text
段落邊界嘴型連續控制
回答收尾嘴型控制
ROI-based blending
```

---

## 14.2 Wav2Lip

用途：

```text
lip-sync avatar backend
```

定位：

```text
Research / Non-commercial
```

不可當作 Nova Avatar 商業版預設 backend。

---

## 14.3 ER-NeRF

用途：

```text
NeRF-based talking avatar
```

定位：

```text
Optional
License verification required
```

---

## 14.4 TalkingGaussian

用途：

```text
Gaussian-based talking avatar
```

定位：

```text
Optional
Commercial license verification required
```

---

## 14.5 UltraLight

用途：

```text
lightweight avatar / lip-sync backend
```

定位：

```text
Optional
License verification required
```

---

# 15. Nova Avatar Python 核心依賴

目前 root `pyproject.toml` 的 dependency 可依用途整理如下。

---

## 15.1 Web / API / WebRTC

```text
aiohttp
aiohttp-cors
aiortc
av
websockets==12.0
```

用途：

- HTTP API
- WebSocket
- WebRTC
- audio/video frame handling

---

## 15.2 Speech / Audio

```text
edge-tts
faster-whisper>=1.1
librosa
soundfile==0.12.1
resampy
scipy
```

用途：

- STT
- TTS
- resampling
- audio file
- audio feature processing

---

## 15.3 AI Runtime

```text
torch==2.5.0
torchvision
torchaudio
transformers==4.46.0
onnxruntime>=1.16,<1.24
openai
```

其中 `openai` 套件可用於 OpenAI-compatible endpoint client，不代表一定需要使用 OpenAI cloud API。

---

## 15.4 Image / Video

```text
opencv-python-headless<4.12
numpy<2
av
```

用途：

- frame processing
- Avatar pipeline
- image / video conversion
- WebRTC frame handling

---

## 15.5 Config / Data

```text
omegaconf
pydantic
PyYAML
opencc>=1.1.9
```

用途：

- YAML config
- runtime schema
- validation
- Chinese conversion

---

## 15.6 Utility

```text
tqdm
typing-extensions
logger
setuptools==69.5.1
```

`setuptools` 目前被固定版本，是因 mmengine / mmpose 等相容需求。

---

# 16. GPU / PyTorch 環境

目前 uv source 指向：

```text
PyTorch CUDA 12.4
```

Index：

```text
https://download.pytorch.org/whl/cu124
```

主要套件：

```text
torch==2.5.0
torchvision
torchaudio
```

建議正式文件說明：

```text
NVIDIA GPU strongly recommended
CUDA compatibility depends on selected Avatar / TTS backend
```

不要宣稱所有 engine 都只支援 CUDA 12.4，因為第三方 engine 可能有不同要求。

---

# 17. Web frontend 提供的套件

目前 `web/package.json`：

## Runtime dependencies

```text
vue ^3.4.0
bootstrap ^5.3.0
bootstrap-icons ^1.11.0
highlight.js ^11.11.1
marked ^17.0.1
```

用途：

| Package | 用途 |
|---|---|
| Vue 3 | Web Console UI |
| Bootstrap | UI layout / components |
| Bootstrap Icons | Icon |
| highlight.js | 程式碼 syntax highlight |
| marked | Markdown rendering |

---

## Development dependencies

```text
vite ^5.0.0
@vitejs/plugin-vue ^5.0.0
js-yaml ^4.1.0
```

用途：

- frontend dev server
- Vue build
- YAML processing
- production bundle

---

# 18. 使用者需要安裝的外部軟體

Nova Avatar 不只是 pip install package。

正式使用至少要考慮：

| 軟體 | 必要性 | 用途 |
|---|---|---|
| Linux | 建議 / 主要環境 | backend / AI runtime |
| Python 3.10 / 3.11 | 必要 | backend |
| uv | 建議 | Python dependency / environment |
| Node.js | 必要於 Web frontend | build / dev server |
| npm | 必要於 Web frontend | frontend dependencies |
| FFmpeg | 必要 / 高度建議 | audio/video processing |
| NVIDIA Driver | GPU 使用時必要 | CUDA runtime |
| CUDA compatible environment | AI GPU engine 使用時 | inference |
| Ollama | 選用 | local LLM |
| llama.cpp / llama-server | 選用 | local GGUF LLM |
| Browser | 必要 | Web Console |
| HTTPS certificate | 遠端麥克風環境通常必要 | secure browser media access |

---

# 19. Web Console 提供的軟體功能

Nova Avatar frontend 不只是播放器。

目前 Web Console 提供：

- Avatar 即時演播
- 文字聊天
- 麥克風輸入
- 免按對話
- 按住說話
- interrupt / barge-in
- TTS 試聽
- LLM model 設定
- Prompt 設定
- STT 設定
- VAD 設定
- TTS engine 設定
- Avatar engine / character 設定
- subtitle
- answer board / 看板
- stage mode
- `/stage.html` 獨立舞台入口
- runtime settings 持久化

---

# 20. Streaming Reply Pipeline

Nova Avatar 目前有兩條回覆路徑。

## Legacy mode

流程：

```text
LLM 完整回覆
→ TTS
→ Avatar
→ playback
```

優點：

```text
相容性高
容易 fallback
```

---

## Streaming mode

流程：

```text
LLM chunk
→ Semantic Fragment
→ bounded TTS pipeline
→ Avatar
→ playback
```

包含：

```text
turn_id
generation fence
sequence
cancel
stale-output rejection
audio master clock
playback commit
bounded media backpressure
subtitle synchronization
history commit
```

這是 Nova Avatar 相較單純 Avatar demo 更值得對外強調的核心功能。

---

# 21. 專案建議修改流程

---

## Phase 0：建立安全修改分支

建議：

```bash
git checkout -b chore/license-and-project-audit
```

不要直接一次在 main 全域取代。

---

# 22. Phase 1：Legal baseline

確認：

```text
LICENSE
NOTICE
THIRD_PARTY_NOTICES.md
third_party/licenses/
```

Checklist：

- [ ] Root LICENSE 保持 Apache-2.0
- [ ] NOTICE 保留 Kedreamix
- [ ] NOTICE 保留適用 LiveTalking attribution
- [ ] THIRD_PARTY_NOTICES.md 存在
- [ ] MuseTalk license copy 存在
- [ ] Wav2Lip non-commercial notice 存在
- [ ] models / weights 不宣稱被 Nova Avatar 重新授權

---

# 23. Phase 2：Source attribution audit

先掃：

```bash
git grep -n -I \
'Linly-Talker-Stream\|Kedreamix\|LiveTalking\|MuseTalk\|Wav2Lip'
```

每個 source 分成：

```text
A. inherited + modified
B. self-authored
C. third-party copied source
D. generated / vendor
```

然後依類別更新 header。

驗收：

```text
不允許因 rebrand 把 upstream attribution 全部刪除
不允許 self-authored file 誤標 Kedreamix
不允許 MuseTalk code 被宣告成只有 Apache-2.0
不允許 Wav2Lip code 被宣告成 commercial-ready
```

---

# 24. Phase 3：Rebranding cleanup

檢查：

```bash
git grep -n -I -E \
'Linly-Talker-Stream|Linly_Talker_Stream|linly-talker'
```

允許保留：

```text
NOTICE
THIRD_PARTY_NOTICES.md
README References
source legal headers
historical migration code
```

不應保留：

```text
UI product title
package name
browser title
default prompt
current project documentation title
console branding
```

---

# 25. Phase 4：Commercial profile

建議新增：

```text
config/profiles/commercial.yaml
```

或：

```text
docs/commercial-profile.md
```

商業 profile 明確：

```text
Avatar:
  MuseTalk: enabled
  Wav2Lip: disabled
  TalkingGaussian: disabled until license review
  ER-NeRF: disabled until license review
```

TTS：

```text
只開啟已完成授權確認的 TTS backend
```

STT：

```text
只搭配授權已確認的 model / weights
```

---

# 26. Phase 5：README / GitHub Project Page

README 建議順序：

```text
1. Nova Avatar
2. Demo GIF / Video
3. 一句話說明
4. Why Nova Avatar
5. Interaction Flow
6. Use Cases
7. Architecture
8. Supported Engines
9. Quick Start
10. Configuration
11. Web Console
12. Streaming Pipeline
13. Testing
14. Commercial Usage
15. Third-Party Components
16. References
17. License
```

目的：

使用者先理解：

```text
這個專案能做什麼
```

再理解：

```text
用了哪些第三方元件
```

而不是首頁先被 License 文字淹沒。

---

# 27. Phase 6：Package / Software documentation

新增建議：

```text
docs/software-stack.md
```

內容至少分：

```text
Nova Avatar Core
Python Dependencies
Frontend Dependencies
External Runtime
STT Engines
LLM Engines
TTS Engines
Avatar Engines
Commercial Status
```

避免 README 變成 package dump。

---

# 28. Phase 7：Validation

Backend：

```bash
uv run python scripts/check-integration.py
uv run pytest
```

Frontend：

```bash
cd web
npm test
npm run build
```

Voice / WebRTC：

```bash
uv run python scripts/run_voice_soak.py \
  --base-url https://localhost:8010 \
  --turns 50 \
  --output .scratch/reply-voice-streaming/real-soak-report.json
```

---

# 29. Branding Audit

```bash
git grep -n -I -E \
'Linly-Talker-Stream|Linly_Talker_Stream|linly-talker|Kedreamix|kedreamix'
```

結果分類：

## 正常

```text
NOTICE
THIRD_PARTY_NOTICES.md
README References
Inherited source attribution
```

## 要修改

```text
current UI title
package metadata
current product description
current user-facing prompt
```

---

# 30. Third-party Audit

```bash
git grep -n -I -E \
'Wav2Lip|MuseTalk|LiveTalking|Whisper|FunASR|TalkingGaussian|ER-NeRF'
```

不要追求搜尋結果為 0。

這些名稱本來就是 third-party engine / attribution 名稱。

---

# 31. Release 前驗收條件

## Legal

- [ ] LICENSE 存在
- [ ] NOTICE 存在
- [ ] Kedreamix attribution 存在
- [ ] modified inherited source 有 change notice
- [ ] MuseTalk MIT attribution 存在
- [ ] LiveTalking attribution 適用處仍存在
- [ ] Wav2Lip non-commercial restriction 明確
- [ ] third-party models 未被錯誤宣稱 Apache-2.0

---

## Branding

- [ ] 使用者看到的產品名稱都是 Nova Avatar
- [ ] package slug 為 `nova-avatar`
- [ ] frontend package 為 `nova-avatar-web`
- [ ] repository URL 正確
- [ ] old Linly branding 不出現在 current UI

---

## Runtime

- [ ] backend start
- [ ] frontend build
- [ ] WebRTC connection
- [ ] microphone
- [ ] VAD
- [ ] STT
- [ ] LLM
- [ ] TTS
- [ ] MuseTalk
- [ ] interrupt
- [ ] playback commit
- [ ] subtitle lifecycle
- [ ] runtime settings

---

# 32. 建議正式發行組合

若目標是「可對外展示 + 後續商業使用整理」，建議預設組合：

```text
VAD:
Silero

STT:
faster-whisper

LLM:
llama.cpp 或 Ollama

TTS:
Edge TTS
或另外已確認 license 的 local TTS

Avatar:
MuseTalk

Transport:
WebRTC

Frontend:
Vue 3 / Vite
```

---

# 33. 不建議作為商業預設的元件

目前至少：

```text
Wav2Lip
```

應保持：

```text
Research / Non-commercial
```

其他：

```text
TalkingGaussian
ER-NeRF
UltraLight
GPT-SoVITS
XTTS
CosyVoice
Fish TTS
IndexTTS2
FunASR model
```

是否可商業發行，應依：

```text
實際 code version
model checkpoint
weights
dataset
voice license
service terms
```

逐項確認。

---

# 34. 建議 Commit 拆分

不要再把所有 rebrand / legal / UI 改動塞成單一巨大 commit。

建議：

```text
docs: document Nova Avatar software stack
chore: audit inherited Apache-2.0 source notices
chore: audit third-party avatar licenses
chore: define commercial-safe engine profile
docs: clarify supported engines and commercial status
docs: improve Nova Avatar project overview
test: validate commercial default runtime path
```

---

# 35. Codex 執行規則

Codex 每次修改前：

1. 判斷檔案是：
   - Nova Avatar 自有
   - inherited
   - third-party
2. 不使用全域 rebrand 刪除 attribution
3. 不變更 root LICENSE
4. 修改 third-party source 前先看 `THIRD_PARTY_NOTICES.md`
5. Wav2Lip 永遠不能被描述成 commercial-ready
6. MuseTalk-derived source 保留 MIT attribution
7. 每個 phase 完成後先跑 targeted tests
8. 最後才跑 full test
9. 最後做 `git grep` license / branding audit

---

# 36. 最終專案對外說法

建議：

```text
Nova Avatar is a real-time full-duplex conversational digital human framework
built around WebRTC, server-side VAD, pluggable STT/LLM/TTS backends,
streaming reply orchestration and multi-avatar rendering.

The project was originally derived from Kedreamix/Linly-Talker-Stream and
has since been substantially redesigned and independently maintained.
```

不建議：

```text
100% original project
```

也不建議：

```text
All included engines are commercially licensed by Nova Avatar.
```

---

# 37. 最終目標

Nova Avatar 對外應清楚呈現兩件事：

## 第一層：產品 / 技術價值

```text
即時數位人
WebRTC
Streaming LLM
Server-side VAD
STT
TTS
Avatar
Interrupt
Playback Commit
Runtime Configuration
```

## 第二層：來源 / 授權

```text
Linly-Talker-Stream
LiveTalking
MuseTalk
Wav2Lip
Whisper
FunASR
其他第三方引擎
```

使用者可以快速理解專案用途，同時維持完整 attribution 與 third-party license 邊界。

---

# 38. Source Snapshot

本文件依 Nova Avatar `main` branch 當前內容整理，重點參考：

```text
README.md
LICENSE
NOTICE
THIRD_PARTY_NOTICES.md
pyproject.toml
web/package.json
src/asr/
src/tts/
src/tts/engines/
src/avatars/
```

Baseline rebranding commit：

```text
38322a587f78215ce3dfcc0e4c46f47fb29a4ab9
```

後續如新增或移除 engine，需同步更新：

```text
README.md
THIRD_PARTY_NOTICES.md
docs/software-stack.md
commercial profile
license audit checklist
```
