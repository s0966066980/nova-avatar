<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Nova Avatar Software Stack

Updated: 2026-09-25

Nova Avatar is a real-time conversational digital-human application: browser
microphone input travels over WebRTC to server-owned turn orchestration, then
VAD, STT, LLM, TTS, Avatar rendering, and WebRTC playback. A component being
selectable does not make its code, model, voice, service, or weights part of
the root Apache-2.0 grant.

## Nova Avatar core

| Area | Current implementation |
| --- | --- |
| Transport and API | `aiohttp`, `aiortc`, `av`, WebRTC media/event channels |
| Conversation control | Server-owned active turn, interruption, generation fencing, playback commit |
| Speech boundaries | Server-side Silero VAD |
| Web Console | Vue 3, Vite, Bootstrap, browser media APIs |
| Configuration | YAML config plus persisted runtime settings |

## Selectable engines

| Layer | Engine | Project status | Distribution boundary |
| --- | --- | --- | --- |
| STT | faster-whisper | Supported | Review the selected Whisper model artifacts. |
| STT | FunASR | Optional | Review the exact code release and model. |
| LLM | Ollama / llama.cpp | Supported local OpenAI-compatible endpoints | Review the selected model and endpoint terms. |
| TTS | Edge TTS | Supported integration and default checked path | Review service and voice terms for the deployment. |
| TTS | GPT-SoVITS, CosyVoice, Fun-CosyVoice, Fish TTS, XTTS, IndexTTS2 | Optional | Review code, model, voice, and checkpoint terms individually. |
| Avatar | MuseTalk | Supported, recommended review-profile path | Code is MIT; models and dependencies retain separate terms. |
| Avatar | Wav2Lip | **Research / Non-commercial** | Do not include its integration or upstream weights in a commercial Nova Avatar distribution. |
| Avatar | ER-NeRF, TalkingGaussian, UltraLight | Optional, license review required | Do not infer commercial rights from the root license. |
| Scene | Server-side green-screen compositor (`src/scene/`) | Supported for MuseTalk green-screen avatars | Background images, videos, GIFs, and source footage need their own rights review. |
| Retrieval | RAGFlow `v0.27.2` with BGE-M3 via a dedicated Ollama process | Optional, disabled by default | Separate Docker Compose project; review RAGFlow, BGE-M3, and document rights. See [ragflow.md](ragflow.md). |

## External runtime requirements

- Python 3.10–3.11 and `uv` for backend dependencies.
- Node.js and npm for the Vue Console.
- FFmpeg for media processing.
- A browser and HTTPS certificates where browser media permissions require a
  secure origin.
- NVIDIA driver/CUDA-compatible runtime where the selected Avatar or ML engine
  needs it. CUDA requirements differ by engine.
- An Ollama or llama.cpp endpoint when the configured LLM uses one.
- Docker with Compose only when the optional RAGFlow retrieval is enabled.

## Commercial review profile

[`config/config_commercial.yaml`](../config/config_commercial.yaml) is a
complete, selectable configuration starting with MuseTalk, faster-whisper,
Silero, a local OpenAI-compatible LLM endpoint, and Edge TTS. Start it with:

```bash
bash scripts/start-all.sh config/config_commercial.yaml
```

The Console still exposes its normal runtime options. Before commercial
distribution, the deployer must verify every selected model, voice, service,
weight, dataset, and optional engine. See
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and the
[source attribution audit](source-attribution-audit.md).
