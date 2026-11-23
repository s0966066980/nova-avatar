# Nova Avatar Offline TTS Distillation & Matcha-TTS Export

Distills a fast CPU-only `Matcha-TTS` ONNX voice (`RTF ~0.08`, `~250 MB` RAM,
zero live GPU contention) from `Fun-CosyVoice3-0.5B` directly on Jetson AGX Orin.

## End-to-End Pipeline

1. **Build bilingual text corpus (~1.0h / ~900 utterances)**:

```bash
uv run python tools/tts-distill/build_corpus.py --hours 1.0 --output data/tts/distill/corpus.jsonl
```

2. **Synthesize teacher audio on Orin GPU + `faster-whisper` QA filter**
   (stop `llama-server` / Avatar service first so GPU memory is free):

```bash
.local/cosyvoice3/venv/bin/python tools/tts-distill/distill_teacher.py \
  --corpus data/tts/distill/corpus.jsonl \
  --out-dir data/tts/distill \
  --prompt-wav data/tts/prompts/zh-TW-YunJheNeural.cosy24k.v2.wav \
  --prompt-txt data/tts/prompts/zh-TW-YunJheNeural.cosy24k.v2.txt \
  --resume
```

*(Optional — Research / Non-commercial only)* Or synthesize from an Edge-TTS neural voice (subject to Microsoft Read Aloud terms; never ship as commercial weights):

```bash
uv run python tools/tts-distill/distill_edge_teacher.py \
  --corpus data/tts/distill/corpus.jsonl \
  --out-dir data/tts/distill-edgetts \
  --voice zh-TW-HsiaoChenNeural \
  --resume
```

3. **Fine-tune `Matcha-TTS` (Apache-2.0 base `pytorch_model_sherpa.bin`) on Orin GPU (`bf16`)**:

```bash
.local/cosyvoice3/venv/bin/python tools/tts-distill/train_matcha.py \
  --manifest data/tts/distill/manifest.jsonl \
  --base-ckpt .local/matcha-base/pytorch_model_sherpa.bin \
  --out-dir .local/matcha-train \
  --batch-size 16 \
  --epochs 35
```

4. **Export quantized/folded `model.onnx` + bilingual `zh-TW` / `en-US` IPA lexicon**:

```bash
.local/cosyvoice3/venv/bin/python tools/tts-distill/export_matcha_onnx.py \
  --ckpt .local/matcha-train/best.pt \
  --output-dir models/tts/zh-tw-custom
```

5. **Run live runtime profile**:

```bash
uv run python app.py --config config/config_jetson_matcha.yaml
```
