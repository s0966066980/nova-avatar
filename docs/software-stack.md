<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Nova Avatar Software Stack

Updated: 2026-11-16

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
| Speech boundaries | Server-side Silero VAD (`silero-vad` 6.2.1) | Package classifier is MIT; bundled `.jit`/`.onnx` weights are not independently audited. Review upstream terms before commercial sale. |
| Web Console | Vue 3, Vite, Bootstrap, browser media APIs |
| Configuration | YAML config plus persisted runtime settings |

## Selectable engines

| Layer | Engine | Project status | Distribution boundary |
| --- | --- | --- | --- |
| STT | faster-whisper | Supported (`small` MIT in commercial profile) | Whisper weights (`openai/whisper-small`) and `faster-whisper` are MIT; retain OpenAI MIT notices. |
| STT | FunASR | Optional | Review the exact code release and model (currently un-audited). |
| LLM | llama.cpp / Ollama | Supported local OpenAI-compatible endpoints (`llamacpp` + `Gemma-4-E2B` in commercial profile) | `Gemma-4-E2B` (+ `mmproj`) declares Apache-2.0 at pinned revision. Exclude `LFM2.5` (revenue-capped) and `qwen3.5` (un-audited) from commercial baseline. |
| TTS | Edge TTS | **Internal POC only** (**Blocking** for external commercial sale) | `edge-tts` is LGPLv3 and Microsoft online service/voice terms are NOT cleared for commercial sale. Must replace before customer delivery. |
| Avatar | MuseTalk (`presentation_modes: prerecorded` in Phase A) | Supported commercial baseline container | Code is MIT; MuseTalk weights (`unet.pth`, `sd-vae`, `dwpose`, `s3fd`, `face-parse-bisent`) are un-audited. Phase A uses prerecorded video loops and MUST replace dev `musetalk_1` (`user_upload`) with owned-rights recorded assets before commercial sale. |
| Avatar | Wav2Lip | **Research / Non-commercial** | Do not include its integration (`src/avatars/wav2lip/`) or upstream weights in a commercial Nova Avatar distribution. |
| Avatar | ER-NeRF, TalkingGaussian, UltraLight | Optional, license review required | Do not infer commercial rights from the root license. |
| Scene | Server-side green-screen compositor (`src/scene/`) | Supported for MuseTalk green-screen avatars | Background images, videos, GIFs, and source footage need their own rights review. |
| Retrieval | RAGFlow `v0.27.2` with BGE-M3 via a dedicated Ollama process | Optional, disabled by default | Separate Docker Compose project; `BGE-M3` weights are un-audited in this repo and companion images retain separate licenses/EULAs. See [ragflow.md](ragflow.md). |
| Weather | CWA OpenData (`src/weather/`) | Optional external Taiwan open-data API | External service (`https://opendata.cwa.gov.tw/`), not bundled weights. Requires `交通部中央氣象署` attribution, operator-owned production API key, and OGDL/CWA terms review. |

## External runtime requirements

- Python 3.11 and `uv` for backend dependencies. The Jetson build uses 3.11;
  `pyproject.toml` accepts `>=3.10,<3.12`.
- Node.js and npm for the Vue Console.
- FFmpeg for media processing.
- A browser and HTTPS certificates where browser media permissions require a
  secure origin.
- NVIDIA driver/CUDA-compatible runtime where the selected Avatar or ML engine
  needs it. CUDA requirements differ by engine.
- An Ollama or llama.cpp endpoint when the configured LLM uses one.
- Docker with Compose only when the optional RAGFlow retrieval is enabled.

## Commercial review profile (Phase A baseline)

[`config/config_commercial.yaml`](../config/config_commercial.yaml) aligns with the
Jetson AGX Orin Phase A commercial baseline: `model.type: musetalk` with
`presentation_modes` set to `prerecorded`, `faster-whisper small` (MIT), `Silero VAD`,
and local `llamacpp` running `Gemma-4-E2B` (`gemma-4-E2B_q4_0-it`, Apache-2.0).
Revenue-capped (`LFM2.5`), unaudited (`qwen3.5`), and non-commercial (`Wav2Lip`)
components are excluded. Start it with:

```bash
bash scripts/start-all.sh config/config_commercial.yaml
```

Distinguish **內部 POC 試用 (Internal POC)** from **對外商業銷售 (External Commercial Sale)**:
- **Internal POC**: may temporarily use `Edge TTS` and test character assets for
  latency and workflow validation.
- **External Commercial Sale (Blocking)**: before customer delivery, the deployer
  **must** (1) replace `Edge TTS` with a commercially cleared TTS engine, (2) re-record
  owned-rights prerecorded avatar assets with signed portrait/voice releases instead
  of dev `musetalk_1` (`user_upload`), and (3) complete all checks in
  [docs/commercial-release-checklist.md](commercial-release-checklist.md).

See also [docs/models.md](models.md), [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md),
and the [source attribution audit](source-attribution-audit.md).
