<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Nova Avatar Software Stack

Updated: 2026-10-30

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
| STT | faster-whisper | Supported, default: `small`; voice turns auto-detect between Chinese and English only, beam 1, in-memory audio | Review the selected Whisper model artifacts. |
| STT | FunASR | Optional, Mandarin only (English turns need Whisper) | Review the exact code release and model. |
| LLM | llama.cpp | Supported, default: Gemma 4 E2B (`gemma-4-E2B_q4_0-it`, with its mmproj for attachments), all layers on the GPU; Qwen3.5-9B optional | Gemma 4 is Apache-2.0 (see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)); review any other selected model. |
| LLM | Ollama | Optional local OpenAI-compatible endpoint; not needed by default | Review the selected model and endpoint terms. |
| TTS | Edge TTS | **Development only** | Still the checked-in runtime default for development. Non-public Microsoft endpoint with no formal commercial license; needs Internet access. Do not use it in a commercial deployment. |
| TTS | BreezyVoice (MediaTek Research) with g2pW | Optional, local Taiwanese Mandarin; whole-fragment synthesis in the owned CosyVoice process (upstream CosyVoice v1 code from `~/CosyVoice`, Apache-2.0). On an RTX 4090 shared with MuseTalk and the LLM, the first fragment takes about 2.5 s (P50), so it is not the default yet | Code and weights Apache-2.0 (pinned in `scripts/breezyvoice_weights.py`); the reference voice needs its own consent. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). |
| Avatar | MuseTalk | Supported, recommended review-profile path | Code is MIT; models and dependencies retain separate terms. |
| Avatar | Wav2Lip | **Research / Non-commercial** | Do not include its integration or upstream weights in a commercial Nova Avatar distribution. |
| Avatar | ER-NeRF, TalkingGaussian, UltraLight | Optional, license review required | Do not infer commercial rights from the root license. |
| Scene | Server-side green-screen compositor (`src/scene/`) | Supported for MuseTalk green-screen avatars | Background images, videos, GIFs, and source footage need their own rights review. |
| Retrieval | RAGFlow `v0.27.2` with BGE-M3 via a dedicated Ollama process | Optional, disabled by default | Separate Docker Compose project; review RAGFlow, BGE-M3, and document rights. See [ragflow.md](ragflow.md). |

Qwen3-TTS was evaluated and removed on 2026-10-30 (voice cloning produced
runaway audio); it is neither supported nor bundled.

Measured first-audio latency for this stack (Edge TTS, 2026-10-30): general
voice turns P50 2.00 s, P95 2.22 s, from the end of speech to the first audible
WebRTC reply frame sent. See [project-status.md](project-status.md) for the
definitions, the stage breakdown, and the remaining bottlenecks.

## External runtime requirements

- Python 3.10–3.11 and `uv` for backend dependencies.
- Node.js and npm for the Vue Console.
- FFmpeg for media processing.
- A browser and HTTPS certificates where browser media permissions require a
  secure origin.
- NVIDIA driver/CUDA-compatible runtime where the selected Avatar or ML engine
  needs it. CUDA requirements differ by engine.
- llama.cpp (`llama-server` with CUDA) for the default LLM; the backend starts
  it and fails with an explanation when the model does not fit fully on the GPU.
  Ollama only when an Ollama endpoint is selected.
- Docker with Compose only when the optional RAGFlow retrieval is enabled.

## Commercial review profile

[`config/config_commercial.yaml`](../config/config_commercial.yaml) is a
complete, selectable configuration starting with MuseTalk, faster-whisper,
Silero, a local OpenAI-compatible LLM endpoint, and Edge TTS. Edge TTS is
development only; replace it before a commercial deployment. Start it with:

```bash
bash scripts/start-all.sh config/config_commercial.yaml
```

The Console still exposes its normal runtime options. Before commercial
distribution, the deployer must verify every selected model, voice, service,
weight, dataset, and optional engine. See
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and the
[source attribution audit](source-attribution-audit.md).
