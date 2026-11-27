# 數位人渲染 (`nova_render`)

數位人渲染留在核心行程內，只以程式介面和核心隔開（ADR 0027 決定 1）。

- **內容**：`base.py`（`BaseAvatar`）、`factory.py`、`builder.py`（角色製作）、`catalog.py`、`mouth_quality.py`、`musetalk/`（MuseTalk 引擎，另有自己的 `pyproject.toml`）、`scene/`（背景場景）、`fake.py`（契約測試用的假渲染）。
- **對外介面**：`nova_contracts.AvatarRenderer`；說話來源由核心以 `SpeechFactory` 注入，渲染層不 import TTS。
- **引擎**：MuseTalk（支援）；授權見 `THIRD_PARTY_NOTICES.md`，MuseTalk 為 MIT。
- **測試**：`uv run --no-sync pytest avatar`；需要 GPU 或權重的測試以 `gpu` marker 標記，預設排除。

其他層與契約見 [`contracts/README.md`](../contracts/README.md)；整體決定見 [ADR 0027](../docs/adr/0027-split-code-by-processing-layer.md) 與 [ADR 0028](../docs/adr/0028-monorepo-with-contracts-package.md)。
