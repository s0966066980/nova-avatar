# 語音合成 (`nova_tts`)

文字轉語音、音訊庫、聲線模型與聲線訓練。目標是 loopback 服務：每個片段一個請求，以 chunked 回傳 PCM（ADR 0027）。

- **內容**：`engines/`（Edge、BreezyVoice、Matcha、fake）、`voice_library.py`、`voice_models.py`、`training/`（聲線訓練）、`audio_sink.py`、`adapter.py`、`config_api.py`。
- **對外介面**：`nova_contracts.TtsService`，由 `adapter.TtsAdapter` 實作；引擎只依賴 `AudioSink`，不認識渲染層。
- **引擎**：Edge TTS、BreezyVoice、Matcha；`tts.type: fake` 輸出靜音，不出現在控制台。授權標示見 `THIRD_PARTY_NOTICES.md`。
- **測試**：`uv run --no-sync pytest services/tts`；需要 GPU 的測試以 `gpu` marker 標記。

其他層與契約見 [`contracts/README.md`](../../contracts/README.md)；整體決定見 [ADR 0027](../../docs/adr/0027-split-code-by-processing-layer.md) 與 [ADR 0028](../../docs/adr/0028-monorepo-with-contracts-package.md)。
