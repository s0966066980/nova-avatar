# 語音辨識 (`nova_stt`)

語音轉文字。目標是 loopback 服務：`POST` 音訊，回傳 JSON（ADR 0027）。

- **內容**：`base.py`（`BaseASR`）、`factory.py`、`engines/whisper.py`（faster-whisper）、`engines/fake.py`、`prewarm.py`、`adapter.py`。
- **對外介面**：`nova_contracts.SttService`，由 `adapter.SttAdapter` 實作。
- **引擎**：faster-whisper（唯一的真引擎）；`asr.type: fake` 回傳固定逐字稿，不出現在控制台。
- **測試**：`uv run --no-sync pytest services/stt`。

其他層與契約見 [`contracts/README.md`](../../contracts/README.md)；整體決定見 [ADR 0027](../../docs/adr/0027-split-code-by-processing-layer.md) 與 [ADR 0028](../../docs/adr/0028-monorepo-with-contracts-package.md)。
