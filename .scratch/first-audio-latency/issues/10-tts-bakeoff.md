<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# TTS 評比
Status: ready-for-agent
Blocked by: 01, 04, 09

依[規格](../spec.md)。主角 BreezyVoice；對照 Qwen3-TTS 0.6B（`faster-qwen3-tts`，權重已在本機 HF 快取、`.venv-qwen-speech` 已裝 `qwen_tts`）與 Fun-CosyVoice3 0.5B（已整合）。在 MuseTalk 與 E2B 都載入的實機上量測：

- 第一個片段（約 15 字）合成時間 P50／P95，冷／暖、LLM 串流中；目標 P50 ≤ 0.4 s、P95 ≤ 0.7 s。
- 額外顯存。
- 100 句繁體中文字錯率（含台灣讀音字：垃圾、和、星期、企業；地名；新台幣金額與日期；中英混合）；英文字錯率。
- 500 句截斷／幻覺率；8 小時穩定性。
- 產生試聽頁給使用者評主觀音質。

未達時間目標依序：縮短首句（issue 08）→ 加速 BreezyVoice（半精度、TensorRT）→ 改用 Fun-CosyVoice3＋台灣讀音字典。結果與使用者決定寫入 Comments。

## Comments
