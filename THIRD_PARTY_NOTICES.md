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

## NVIDIA TensorRT and ONNX (optional)

- TensorRT role: optional full-model MuseTalk UNet/VAE inference acceleration
- Package: `tensorrt-cu12==10.16.1.11`, downloaded into the local Python environment
- Source and license terms: <https://developer.nvidia.com/tensorrt>
- TensorRT is NVIDIA software governed by its own license, not Nova Avatar's Apache-2.0 license.
- ONNX role: build-time model export; license: Apache-2.0
- ONNX source: <https://github.com/onnx/onnx>

TensorRT binaries, model exports, and generated engines are not bundled in this
repository. Generated engines retain the applicable model and NVIDIA terms;
verify those terms before redistribution.

## Wav2Lip

- Role: formerly an optional lip-sync avatar engine; **removed on 2026-11-24**
  and no longer bundled
- Usage classification: **Research / Non-commercial**
- Permitted upstream uses: research, academic, and personal use
- Commercial use: **not permitted** for the upstream open-source code or models
- Source: <https://github.com/Rudrabha/Wav2Lip>
- Local restriction notice: [`third_party/licenses/Wav2Lip-NON-COMMERCIAL-NOTICE.txt`](third_party/licenses/Wav2Lip-NON-COMMERCIAL-NOTICE.txt)

Earlier revisions in the Git history contain the `src/avatars/wav2lip/`
integration; it and the upstream open-source weights must not be included in or
used for a commercial Nova Avatar distribution. The restriction notice is kept
for those revisions and for any copy that still carries them.

## Whisper

- Role: speech and audio feature component
- License: MIT
- Copyright: Copyright (c) 2022 OpenAI
- Source: <https://github.com/openai/whisper>

## Fun-ASR-Nano-2512 and FunASR (removed STT)

- Role: formerly an optional Chinese/English speech recognition engine
  (`funasr`); **removed on 2026-11-26** and no longer integrated. faster-whisper
  is the only STT engine.
- Earlier revisions in the Git history ran it as an owned loopback process
  (`scripts/fun_asr_nano_server.py`) in its own venv
  (`integrations/fun-asr-nano/requirements.txt`); it was never bundled here.
- Fun-ASR-Nano-2512 weights: Apache-2.0, Tongyi Lab / FunAudioLLM,
  `FunAudioLLM/Fun-ASR-Nano-2512` revision
  `272c57b82523ada6fd87095e955f8e29100979ab`. Its decoder is Qwen3-0.6B
  (Apache-2.0, Alibaba Qwen team). Those revisions fetched the weights with
  `scripts/fun_asr_nano_weights.py` and checked SHA-256.
- FunASR code: MIT, Copyright (c) 2025 FunASR, <https://github.com/modelscope/FunASR>;
  those revisions installed `funasr==1.4.15` in the service venv.

## OpenCC

- Role: Taiwan Traditional conversion (`s2twp`) of replies and voice-training
  transcripts, and Simplified conversion for Matcha-TTS tokenisation
- License: Apache-2.0
- Source: <https://github.com/BYVoid/OpenCC>

## BreezyVoice and g2pW (optional TTS)

- Role: optional local Taiwanese Mandarin voice-cloning TTS (`breezyvoice`
  engine), served by the owned CosyVoice process
- BreezyVoice code: Apache-2.0, MediaTek Research,
  <https://github.com/mtkresearch/BreezyVoice>; derived from CosyVoice
  (Apache-2.0, Alibaba).
- CosyVoice code: Apache-2.0, Alibaba / FunAudioLLM,
  <https://github.com/FunAudioLLM/CosyVoice>. The owned process imports it, with
  its bundled Matcha-TTS, from a separate checkout (`~/CosyVoice`) in the
  `cosyvoice` conda environment; it is not bundled here. [`services/tts/scripts/breezyvoice_frontend.py`](services/tts/scripts/breezyvoice_frontend.py)
  adapts its `get_bopomofo_rare` (commit `d592c9d3e8927a0f53f68616387060dcd32a05ea`)
  and carries a modification notice.
- BreezyVoice weights: Apache-2.0, `MediaTek-Research/BreezyVoice` revision
  `e33b502e0ac21c16b0ee0d00df66ac3fa737393d`. Its reading tables (`utils/word_utils.py`)
  come from the GitHub commit above.
- g2pW: Apache-2.0, Yi-Chang Chen et al., <https://github.com/GitYCC/g2pW>;
  ONNX model `YC-Chen/g2pW` revision `fb4784f7dce8466a53dd4f3552f5a4c5b657b90c`;
  Python package `g2pw==0.1.1` in the CosyVoice environment.
- Tokenizer for g2pW: `google-bert/bert-base-chinese` revision
  `8f23c25b06e129b6c986331a13d8d025a92cf0ea`, Apache-2.0 (tokenizer files only).
- [`services/tts/scripts/breezyvoice_weights.py`](services/tts/scripts/breezyvoice_weights.py) fetches all
  of the above at those revisions and checks SHA-256; none are bundled here.
- Voices: the BreezyVoice repository's example recording (`data/example.wav`)
  documents no speaker consent or recording source beyond the repository's
  Apache-2.0 grant. Use it for development only; production voices must be
  recorded by the operator or used with written permission.

## Whisper bilingual recognition weights

- Official weights: OpenAI `whisper-small`, revision `973afd24965f72e36ca33b3055d56a652f456b4d`,
  and `whisper-large-v3-turbo`, revision `41f01f3fe87f28c78e2fbf8b568835947dd65ed9`.
- Source and license: <https://github.com/openai/whisper>, MIT.
- Local FP16 CTranslate2 conversions are not bundled. Source revisions, converted
  file hashes and the retained official license are recorded in
  PC validation.

## Conversation PDF and image analysis

- pypdfium2 role: local PDF text extraction and page rendering; validated release: 5.14.0
- Binding license: Apache-2.0 OR BSD-3-Clause; documentation: CC-BY-4.0
- Source: <https://github.com/pypdfium2-team/pypdfium2>
- Bundled PDFium and native dependencies retain their own notices. The tested
  platform wheel's license bundle is preserved under
  [`third_party/licenses/pypdfium2-5.14.0/`](third_party/licenses/pypdfium2-5.14.0/).
  Other platforms/builds must retain their corresponding wheel notices.
- Vision runtime: llama.cpp / libmtmd, <https://github.com/ggml-org/llama.cpp>.
  Runtime code licensing does not determine the model-weight license.
- Tested model/projector source: Google `gemma-4-E2B-it-qat-q4_0-gguf`, revision
  `675cff42a74c774d6cb76f76d8eacb49b48c9b93`.
  The official model card declares Apache-2.0. Preserve that model card, source,
  hashes and applicable notices when distributing weights.
- Model source: <https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf/tree/675cff42a74c774d6cb76f76d8eacb49b48c9b93>.
- Local OCR: Tesseract 5.5.0 (PC validation; Jetson originally 5.3.4) with official `tessdata_fast` Traditional Chinese
  and English weights, Apache-2.0. Engine lineage is HP / Google; current
  upstream maintenance is community based. Complete training-data provenance
  was not audited and is not asserted to be exclusively from any region.
- OCR sources: <https://github.com/tesseract-ocr/tesseract> and
  <https://github.com/tesseract-ocr/tessdata_fast>.
- Tested Ubuntu package copyright/license notices and upstream license texts:
  [`third_party/licenses/tesseract/`](third_party/licenses/tesseract/).

## Console fonts

- Plus Jakarta Sans (Tokotype) and JetBrains Mono (JetBrains), bundled into the
  console build through `@fontsource/plus-jakarta-sans@5.3.0` and
  `@fontsource/jetbrains-mono@5.3.0`.
- License: SIL Open Font License 1.1 (OFL-1.1); the packaging is MIT. The OFL
  text ships in each package's `LICENSE` file under `web/node_modules/` and must
  be kept with any redistributed font files.
- Sources: <https://github.com/tokotype/PlusJakartaSans>,
  <https://github.com/JetBrains/JetBrainsMono>,
  <https://github.com/fontsource/font-files>.
- Chinese text uses the system's installed Noto Sans CJK TC; it is not bundled.

## Gemma 4 language model

- Role: main local LLM (`gemma-4-E2B_q4_0-it.gguf`) and its vision projector
  (`gemma-4-E2B-it-mmproj.gguf`), served by llama.cpp
- Source: Google `google/gemma-4-E2B-it-qat-q4_0-gguf`,
  <https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf>
- License: Apache-2.0, per the model cards of that repository,
  `google/gemma-4-E2B-it` and `google/gemma-4-E2B`, and the linked Gemma 4
  license page <https://ai.google.dev/gemma/docs/gemma_4_license> (checked
  2026-10-29)
- The Gemma Terms of Use do not apply to Gemma 4: they cover only the models
  listed in their appendix (Gemma 1 to TranslateGemma) and refer Gemma 4 to its
  own license. Commercial use carries no revenue or user threshold. Following
  the Gemma Prohibited Use Policy is still recommended.
- Earlier Gemma generations (1 to 3) use the Gemma Terms of Use, whose use
  restrictions flow downstream. Do not apply this Gemma 4 statement to them.
- The weights are not bundled in this repository. When distributing them,
  include the Apache-2.0 license text and keep the model card and notices.

## RAGFlow and dedicated embedding service

- RAGFlow role: optional, separately deployed document retrieval service
- RAGFlow version: v0.27.2; code license: Apache-2.0
- RAGFlow source: <https://github.com/infiniflow/ragflow>
- Embedding server: the host's llama.cpp `llama-server`, run CPU-only for BGE-M3
  (MIT; <https://github.com/ggml-org/llama.cpp>)
- Ollama role: existing host installation; fetches the pinned BGE-M3 GGUF and
  can serve RAGFlow chat models
- Ollama source: <https://github.com/ollama/ollama>
- BGE-M3 role: recommended multilingual embedding model
- BGE-M3 source and model card: <https://huggingface.co/BAAI/bge-m3>

RAGFlow and model images are fetched on the host, not bundled in the Nova
repository. Check their exact image and model licenses before redistribution;
the Nova Apache-2.0 license does not relicense them.
The accompanying Elasticsearch, MySQL, MinIO-compatible, and Valkey images
also retain their respective upstream license and distribution terms.

## ER-NeRF, TalkingGaussian, and UltraLight

These avatar engines were removed from this repository on 2026-11-24 and are
no longer bundled. Earlier revisions in the Git history still contain them
with their embedded notices; some TalkingGaussian submodules in those revisions
carry explicit non-commercial research/evaluation terms, which remain
controlling for those files.

## Optional TTS backends

The TTS engines are Edge TTS, BreezyVoice (above) and Matcha voice models.
Verify the exact
code, service, voice, model, and checkpoint terms before redistribution or
commercial packaging. The Console engine catalog shows each engine's usage
classification in its label.

### Edge TTS

- Usage classification: **Development only**
- Edge TTS calls the non-public Microsoft Edge read-aloud endpoint. No formal
  commercial license or service agreement covers that endpoint, and the venue
  cannot synthesize speech without Internet access.
- Do not use Edge TTS as the speech engine of a commercial or production
  deployment.

### Matcha voice models

- Role: optional CPU TTS engine (`matcha`); Edge TTS remains the default. Each
  voice model (聲線模型) under `models/tts/<id>/` speaks one voice for zh-TW and
  en-US. Voice models are not bundled in this repository and are never
  downloaded; they are copied by hand. Installation, the `voice.json` usage
  label and SHA-256 file lists: [docs/voice-models.md](docs/voice-models.md).
  Design: [ADR 0025](docs/adr/0025-matcha-voice-models-without-edge-distillation.md).
- No voice model is cleared for commercial use. The usage label is shown in
  the Console; the system does not block use.
- Information verified 2026-11-24.

#### sherpa-onnx

- Role: ONNX inference runtime and text frontend for voice models, pinned to
  `sherpa-onnx==2.0.1` in `uv.lock`
- License: Apache-2.0
- Source: <https://github.com/k2-fsa/sherpa-onnx> (`LICENSE`)
- Installed package metadata and license remain in the Python distribution.
  Nova Avatar ships no Matcha-TTS model code: sherpa-onnx runs the exported
  ONNX graphs.

#### Base model `dengcunqin/matcha_tts_zh_en_20251010`

- Role: Chinese/English Matcha-TTS acoustic model, lexicon and tokens; the
  starting point of every fine-tuned voice model
- Usage classification: **Research / Non-commercial**, for the base model and
  every voice model fine-tuned from it, until the training-data license is
  confirmed
- Source: <https://modelscope.cn/models/dengcunqin/matcha_tts_zh_en_20251010>
- The ModelScope metadata declares Apache License 2.0, but the model README
  names no training-data source. The upstream Baker recipe data is licensed
  for non-commercial use only and may be part of the training data. The
  declared code/weight license does not clear the data.
- The base model has no usage label (`voice.json`), so it is not listed as a
  selectable voice model.

#### Vocoder `vocos-16khz-univ.onnx`

- Role: 16 kHz vocoder shared by all voice models
- Source: sherpa-onnx `vocoder-models` release
  <https://github.com/k2-fsa/sherpa-onnx/releases/tag/vocoder-models>; an
  identical file (SHA-256 `b599142a1fb8ff03de3e84ac35ff537c619e56f4267a6fe894851a42844acf9e`)
  is in the `dengcunqin/matcha_tts_zh_en_20251010` repository
- Weights: that repository's metadata declares Apache-2.0; the weights'
  training data is unknown
- Upstream Vocos code: MIT, Copyright (c) 2023 Charactr Inc.,
  <https://github.com/gemelo-ai/vocos>
- Carries the classification of the voice model it ships with; it adds no
  commercial permission.

#### Voice model `zh-tw-hsiaochen-edge`

- Usage classification: **Development only**
- Distilled from Microsoft Edge read-aloud `zh-TW-HsiaoChenNeural` output,
  fine-tuned from the base model above.
- Microsoft Services Agreement §14(s)(iv) (effective 2026-09-30): "You may not
  use the AI services, or data from the AI services, to create, train, or
  improve (directly or indirectly) any AI technology". The clause does not
  distinguish commercial from non-commercial use. Whether the Edge read-aloud
  endpoint falls under the agreement is unconfirmed; the risk remains.
- Use it only for development on the operator's own machine. Do not use it at
  a venue, in a commercial or production deployment, or redistribute it.
- The legacy `NOTICE-NON-COMMERCIAL.txt` in its directory says Research /
  Non-commercial; the stricter `Development only` label in `voice.json`
  governs.
- Nova Avatar does not use Edge TTS as a teacher for training or distillation
  (ADR 0025).

#### Voice-model training workbench (development tooling)

- Role: the Console's 聲線訓練 page fine-tunes the base model above into new
  voice models, in a separate virtual environment under
  `.local/matcha-train/` (created by `services/tts/scripts/setup-matcha-train.sh`). It is
  development tooling for the operator's own machine and is not shipped as part
  of a deployment. Design: [ADR 0026](docs/adr/0026-edge-as-test-only-matcha-teacher.md).
- Matcha-TTS (`matcha-tts==0.0.7.2`, Shivam Mehta): MIT,
  <https://github.com/shivammehta25/Matcha-TTS>. It is installed with
  `--no-deps --require-hashes`; the packages it would pull in beyond the
  pinned set in `integrations/matcha-train/requirements.txt` (for example
  `phonemizer`, which is GPL-3.0) are deliberately not installed.
- Training dependencies: the pinned list in
  `integrations/matcha-train/requirements.txt` (PyTorch 2.5.0 and its
  permissively licensed dependencies; the transitive `certifi` and `tqdm`
  carry MPL-2.0). No GPL package is installed.
- Base checkpoint `pytorch_model_sherpa.bin` (ModelScope
  `dengcunqin/matcha_tts_zh_en_20251010`, commit
  `839c6c33693e1ac54a17a6c4d24ef44d96904674`, SHA-256
  `a7b0458c146cb1712824a355de27f3969e074b80d02787c9e852fec7006a38ab`):
  downloaded by the setup script, never committed. Classification
  **Research / Non-commercial**, for the same reason as the base model above.
- Usage classification of a trained voice model is the strictest of the base
  model and the training-corpus source, and processing never lowers it:
  - corpus synthesized by the Edge test teacher, or recordings declared
    "development, unlicensed": **Development only**
  - the operator's own recordings or recordings with written authorization:
    **Research / Non-commercial** (the base model's training data is unknown)
- The Edge test teacher synthesizes training text with the non-public Microsoft
  Edge read-aloud endpoint. The Microsoft Services Agreement §14(s)(iv) clause
  quoted above applies in the same way, and the Console requires the
  administrator to confirm the clause before the first synthesis. Fun-CosyVoice3
  is not part of this tooling.
- The Console records, but does not verify, the operator's declaration about a
  recording's speaker and authorization. Obtaining consent and written
  authorization is the operator's responsibility.
- Trained voice models stay on the machine under `models/tts/`. The Console
  offers no download route; copying a voice model elsewhere is a manual,
  operator-owned act, and the label travels with it in `voice.json`.
- Information verified 2026-11-24.

## Models, weights, and datasets

Model weights and datasets are not relicensed by Nova Avatar. A usable code
license does not imply that associated weights, training data, voices, or
generated assets have the same permissions. Distributors are responsible for
reviewing the exact artifacts they ship.

## DDGS (public web search)

- Role: optional-at-use public search for role-owned web search, pinned to `ddgs==9.14.4`
- License: MIT
- Source: <https://github.com/deedy5/ddgs>
- Installed package metadata and license remain in the Python distribution.
- Nova Avatar uses explicitly selected DuckDuckGo and Brave backends. Search queries
  leave the deployment host; search providers and retrieved websites retain their
  own terms. The package license does not grant rights over retrieved web content
  or guarantee availability of search services.
- Unsloth Studio was consulted as an architectural reference; no AGPL Studio code
  was copied into this integration.
