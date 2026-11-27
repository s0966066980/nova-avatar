# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The training scripts under tools/tts-distill, tested without the matcha-tts package.

``train_matcha`` and ``matcha_arch`` run in the training venv, but everything
here uses a fake model, so only torch, torchaudio and soundfile (already in the
main environment) are needed. No GPU, no checkpoint, no network.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import torch

TOOLS = Path(__file__).resolve().parent.parent / "tools" / "tts-distill"


@pytest.fixture(scope="module")
def scripts():
    sys.path.insert(0, str(TOOLS))
    try:
        yield importlib.import_module("train_matcha"), importlib.import_module("matcha_arch")
    finally:
        sys.path.remove(str(TOOLS))
        for name in ("train_matcha", "matcha_arch"):
            sys.modules.pop(name, None)


class FakeMatcha(torch.nn.Module):
    """Stands in for upstream MatchaTTS: four return values, fails on a too-short crop."""

    def __init__(self):
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(1))
        self.calls: list[int | None] = []

    def forward(self, x, x_lengths, y, y_lengths, out_size=None):
        self.calls.append(out_size)
        if out_size is not None:
            assert int(y_lengths.min()) >= out_size, "crop longer than the shortest utterance"
        return self.w * 1.0, self.w * 0.5, self.w * 0.25, None


def write_wav(path: Path, seconds: float, rate: int = 16000) -> None:
    rng = np.random.default_rng(0)
    sf.write(str(path), (rng.standard_normal(int(rate * seconds)) * 0.1).astype("float32"), rate)


def tensors(lengths: list[int]):
    x = [torch.arange(1, 6) for _ in lengths]
    mels = [torch.zeros(80, n) for n in lengths]
    return list(zip(x, mels))


@pytest.mark.parametrize(
    ("shortest", "expected"),
    [(300, 172), (172, 172), (171, 168), (90, 88), (35, 32), (31, None), (10, None)],
)
def test_crop_shrinks_to_the_shortest_utterance_of_the_batch(scripts, shortest, expected):
    _, arch = scripts
    assert arch.batch_out_size(torch.tensor([400, shortest, 250])) == expected


def test_a_batch_with_a_short_utterance_trains_without_a_shape_error(scripts):
    train, _ = scripts
    model = FakeMatcha()
    batch = train.collate_batch(tensors([400, 90]))  # padded width 400, shortest 90 < 172
    loss, parts = train.training_step(model, batch, torch.device("cpu"), full_seq=False)
    assert model.calls == [88]
    assert float(loss) == pytest.approx(1.75)
    assert parts == pytest.approx((1.0, 0.5, 0.25))


def test_full_sequence_mode_does_not_crop(scripts):
    train, _ = scripts
    model = FakeMatcha()
    train.training_step(model, train.collate_batch(tensors([400, 90])), torch.device("cpu"), full_seq=True)
    assert model.calls == [None]


def test_collate_pads_mel_length_to_a_multiple_of_four(scripts):
    train, _ = scripts
    x, x_len, y, y_len = train.collate_batch(tensors([10, 7]))
    assert y.shape == (2, 80, 12)
    assert y_len.tolist() == [10, 7]
    assert x.shape == (2, 5) and x_len.tolist() == [5, 5]


def write_manifest(path: Path, wavs: list[Path], ids: list[list[int]]) -> None:
    rows = [{"wav": str(wav), "phoneme_ids": tokens, "text": "文字"} for wav, tokens in zip(wavs, ids)]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_dataset_yields_token_ids_and_a_normalised_mel(scripts, tmp_path):
    train, _ = scripts
    wav = tmp_path / "a.wav"
    write_wav(wav, 1.0)
    write_manifest(tmp_path / "m.jsonl", [wav], [[5, 6, 7]])
    data = train.DistilledMatchaDataset(tmp_path / "m.jsonl", mel_mean=-3.0, mel_std=5.0, n_vocab=2190)
    x, mel = data[0]
    assert x.tolist() == [5, 6, 7]
    # 1 s plus 150 ms of padding on both sides at hop 256.
    assert mel.shape[0] == 80 and mel.shape[1] == (16000 + 2 * 2400) // 256 + 1


def test_dataset_refuses_token_ids_outside_the_embedding_table(scripts, tmp_path):
    train, _ = scripts
    wav = tmp_path / "a.wav"
    write_wav(wav, 1.0)
    write_manifest(tmp_path / "m.jsonl", [wav], [[5, 2190]])
    with pytest.raises(ValueError, match="token ids"):
        train.DistilledMatchaDataset(tmp_path / "m.jsonl", mel_mean=0.0, mel_std=1.0, n_vocab=2190)


def test_dataset_refuses_audio_that_is_not_16_khz(scripts, tmp_path):
    train, _ = scripts
    wav = tmp_path / "a.wav"
    write_wav(wav, 1.0, rate=22050)
    write_manifest(tmp_path / "m.jsonl", [wav], [[5]])
    data = train.DistilledMatchaDataset(tmp_path / "m.jsonl", mel_mean=0.0, mel_std=1.0, n_vocab=2190)
    with pytest.raises(ValueError, match="16kHz"):
        data[0]


def test_run_training_reports_steps_and_writes_checkpoints(scripts, tmp_path, capsys):
    train, _ = scripts
    wavs = []
    for index, seconds in enumerate((1.0, 0.6, 1.2, 0.8)):
        wav = tmp_path / f"{index}.wav"
        write_wav(wav, seconds)
        wavs.append(wav)
    write_manifest(tmp_path / "m.jsonl", wavs, [[3, 4]] * 4)
    data = train.DistilledMatchaDataset(tmp_path / "m.jsonl", mel_mean=0.0, mel_std=1.0, n_vocab=2190)
    loader = torch.utils.data.DataLoader(data, batch_size=2, collate_fn=train.collate_batch)
    args = argparse.Namespace(
        out_dir=tmp_path / "out", epochs=2, max_steps=3, lr=1e-3, encoder_lr_scale=0.2, proj_lr_scale=-1.0,
        freeze_emb=False, freeze_encoder=False, freeze_encoder_body=False, full_seq=False, save_every=2,
    )
    model = FakeMatcha()
    assert train.run_training(model, loader, torch.device("cpu"), args) == 3
    out = capsys.readouterr().out
    assert "step=1/3" in out and "step=3/3" in out and "Training complete: steps=3" in out
    assert (tmp_path / "out" / "last.pt").is_file() and (tmp_path / "out" / "best.pt").is_file()
    state = torch.load(tmp_path / "out" / "last.pt", weights_only=True)
    assert state["step"] == 3 and "w" in state["model_state_dict"]
    assert all(size is not None and size <= 172 for size in model.calls)


# --- lexicon_utils ------------------------------------------------------------


@pytest.fixture(scope="module")
def lexicon():
    sys.path.insert(0, str(TOOLS))
    try:
        yield importlib.import_module("lexicon_utils")
    finally:
        sys.path.remove(str(TOOLS))
        sys.modules.pop("lexicon_utils", None)


TOKENS = {"ni3": 11, "hao3": 12, ",": 4, " ": 1, "h": 20, "i": 21}
WORDS = {"你好": ["ni3", "hao3"], "h": ["h"], "i": ["i"], "hi": ["h", "i"]}


def test_tokeniser_maps_traditional_text_through_the_lexicon(lexicon):
    assert lexicon.text_to_phoneme_ids("你好，hi", WORDS, TOKENS) == [11, 12, 4, 1, 20, 21]


@pytest.mark.parametrize("text", ["你好 3 個", "2026年", "Ａ１"])
def test_tokeniser_refuses_text_with_digits(lexicon, text):
    with pytest.raises(ValueError, match="digits"):
        lexicon.text_to_phoneme_ids(text, WORDS, TOKENS)


def test_merged_lexicon_keeps_only_words_spelled_with_known_tokens(lexicon, tmp_path):
    (tmp_path / "tokens.txt").write_text("ni3 11\nhao3 12\nA 30\n", encoding="utf-8")
    (tmp_path / "zh.txt").write_text("你好 ni3 hao3\n壞 huai4\n", encoding="utf-8")
    merged = lexicon.build_merged_lexicon(tmp_path / "zh.txt", tmp_path / "tokens.txt", out_path=tmp_path / "out.txt")
    assert merged["你好"] == ["ni3", "hao3"] and "壞" not in merged
    assert merged["a"] == ["A"]  # a technical-term entry whose tokens all exist
    assert (tmp_path / "out.txt").read_text(encoding="utf-8").startswith("你好 ni3 hao3\n")
