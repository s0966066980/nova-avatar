<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Matcha 引擎與設定檔整合
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)第 6、10、11 點與「第一階段範圍」。

- 移植 jetson-orin 的 `src/tts/engines/matcha.py` 和 `src/tts/pcm_emitter.py`（`git show origin/jetson-orin:<path>`），並照 AGENTS.md 加上來源和修改標示。
- 在 factory、`engines/__init__` 和 `voice_library.TTS_ENGINES` 註冊 `matcha`。數位人設定檔驗證要接受 `matcha`，並要求選定一個已列出的聲線模型。zh-TW 和 en-US 都用這個聲線模型。
- `num_threads` 改為全域伺服器設定，預設 4。`length_scale` 和 `noise_scale` 固定用預設值。
- 設定檔指到的聲線模型不存在時，處理方式跟 BreezyVoice 缺少參考音檔時一致，要明確提示，不能默默改用其他聲音。
- 移植並調整 `tests/test_matcha_tts.py`，納入主要基準；0 失敗、0 跳過。
- 新增或調整的路由列入 `ROUTE_ACCESS`（ADR 0021）。
- 應用日誌要輸出 `first audio:`，格式跟其他引擎一致，供 05 驗收使用。
