# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Load an exported voice-model bundle in sherpa-onnx on the CPU and synthesise a sentence.

Run as ``python -m nova_tts.training.verify_bundle <bundle dir>`` in a subprocess of the
application's interpreter with ``CUDA_VISIBLE_DEVICES=`` (the training job does this
before it installs a bundle): a model that sherpa-onnx cannot load, or that yields no
16 kHz audio, must never reach ``models/tts/``. Prints ``OK <seconds>`` and exits 0, or
exits 1 with the reason on stderr.
"""

from __future__ import annotations

import sys
from pathlib import Path

VERIFY_TEXT = "你好，今天天氣很好。"
RULE_FSTS = ("phone-zh.fst", "date-zh.fst", "number-zh.fst")


def verify(bundle: Path) -> float:
    """Seconds of audio synthesised from ``VERIFY_TEXT``; raises when the bundle does not work."""
    import sherpa_onnx

    fsts = ",".join(str(bundle / name) for name in RULE_FSTS if (bundle / name).is_file())
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=str(bundle / "model.onnx"),
                vocoder=str(bundle / "vocos-16khz-univ.onnx"),
                lexicon=str(bundle / "lexicon.txt"),
                tokens=str(bundle / "tokens.txt"),
            ),
            num_threads=2,
            provider="cpu",
            debug=False,
        ),
        rule_fsts=fsts,
    )
    audio = sherpa_onnx.OfflineTts(config).generate(VERIFY_TEXT, sid=0, speed=1.0)
    if audio.sample_rate != 16000 or len(audio.samples) < 1600:
        raise RuntimeError(f"unexpected audio: {len(audio.samples)} samples at {audio.sample_rate} Hz")
    return len(audio.samples) / audio.sample_rate


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m nova_tts.training.verify_bundle <bundle dir>", file=sys.stderr)
        return 2
    try:
        seconds = verify(Path(argv[0]))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"OK {seconds:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
