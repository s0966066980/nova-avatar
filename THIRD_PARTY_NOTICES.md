# Third-Party Notices

Nova Avatar is distributed under the Apache License 2.0 as described in the
root [`LICENSE`](LICENSE). That project license does not replace the licenses or
usage restrictions of the components listed below.

## Linly-Talker-Stream

- Role: upstream project from which Nova Avatar was originally derived
- License: Apache-2.0
- Copyright: Kedreamix
- Source: <https://github.com/Kedreamix/Linly-Talker-Stream>

Modified inherited files carry a prominent `Modified by HongXian0903, 2026`
notice. See the root [`NOTICE`](NOTICE) for the retained attribution.

## LiveTalking

- Role: real-time avatar and WebRTC architecture reference and adapted code
- License: Apache-2.0
- Source: <https://github.com/lipku/LiveTalking>

Applicable source files retain their LiveTalking attribution.

## MuseTalk

- Role: lip-sync avatar engine
- Code license: MIT
- Copyright: Copyright (c) 2024 Tencent Music Entertainment Group
- Source: <https://github.com/TMElyralab/MuseTalk>
- Local license copy: [`third_party/licenses/MuseTalk-LICENSE.txt`](third_party/licenses/MuseTalk-LICENSE.txt)

The MuseTalk code license permits commercial use, but bundled models and
dependencies retain their own licenses. Verify every model and dependency used
in a distribution.

## Wav2Lip

- Role: optional lip-sync avatar engine
- Usage classification: **Research / Non-commercial**
- Permitted upstream uses: research, academic, and personal use
- Commercial use: **not permitted** for the upstream open-source code or models
- Source: <https://github.com/Rudrabha/Wav2Lip>
- Local restriction notice: [`third_party/licenses/Wav2Lip-NON-COMMERCIAL-NOTICE.txt`](third_party/licenses/Wav2Lip-NON-COMMERCIAL-NOTICE.txt)

The `src/avatars/wav2lip/` integration and its upstream open-source weights
must not be included in or used for a commercial Nova Avatar distribution.

## Whisper

- Role: speech and audio feature component
- License: MIT
- Copyright: Copyright (c) 2022 OpenAI
- Source: <https://github.com/openai/whisper>

## FunASR

- Role: optional automatic speech recognition backend
- Source: <https://github.com/modelscope/FunASR>
- License: verify the exact FunASR release and model license before redistribution

## RAGFlow and dedicated embedding service

- RAGFlow role: optional, separately deployed document retrieval service
- RAGFlow version: v0.27.2; code license: Apache-2.0
- RAGFlow source: <https://github.com/infiniflow/ragflow>
- ARM64 build: pinned upstream source, native Python API/task executor,
  DeepDoc models and Debian Chromium/ChromeDriver; upstream notices retained
- Ollama role: separate GPU embedding process; existing host installation or
  locally downloaded official ARM64 v0.35.1 and JetPack CUDA runner
- Ollama source: <https://github.com/ollama/ollama>
- BGE-M3 role: recommended multilingual embedding model
- BGE-M3 source and model card: <https://huggingface.co/BAAI/bge-m3>
- Native runtime packages retain their respective licenses; the Microsoft ODBC
  driver is distributed under Microsoft's separate EULA, not Nova's Apache-2.0

RAGFlow and model images are fetched on the host, not bundled in the Nova
repository. Check their exact image and model licenses before redistribution;
the Nova Apache-2.0 license does not relicense them.
The accompanying Elasticsearch, MySQL, MinIO-compatible, and Valkey images
also retain their respective upstream license and distribution terms.

## ER-NeRF, TalkingGaussian, and UltraLight

- Role: optional avatar engines and related rendering components
- License: verify each source distribution, bundled submodule, dataset, and model
- Commercial status: do not assume the Nova Avatar Apache-2.0 license grants
  commercial rights to these components

Some TalkingGaussian submodules in this repository carry explicit
non-commercial research/evaluation terms in their own license files. Those
terms remain controlling for those files.

## Optional TTS backends

Edge TTS, GPT-SoVITS, CosyVoice, Fun-CosyVoice, Fish TTS, XTTS, and IndexTTS2
are optional integrations. Verify the exact code, service, voice, model, and
checkpoint terms before redistribution or commercial packaging.

## Models, weights, and datasets

### Optional TAESD decoder

- Source and model: <https://huggingface.co/madebyollin/taesd>
- Upstream license: MIT, copyright (c) 2023 Ollin Boer Bohan
- License text: <https://github.com/madebyollin/taesd/blob/main/LICENSE>
- Role: explicitly selected approximate Stable Diffusion VAE decoder for the
  optional MuseTalk real-time profile. Original avatar encoding remains in use.
- The model is downloaded locally, not bundled. TAESD is approximate and changes
  face detail; it is not a numerically equivalent replacement for the full VAE.

Model weights and datasets are not relicensed by Nova Avatar. A usable code
license does not imply that associated weights, training data, voices, or
generated assets have the same permissions. Distributors are responsible for
reviewing the exact artifacts they ship.
