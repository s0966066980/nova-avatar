# 核心 (`nova_core`)

核心持有輪次、對話與設定，負責把各處理層組合起來。

- **內容**：`server`（路由、`reply_streaming`、對話、狀態、聲線訓練工作）、`vad`、`profiles`（角色庫與組合、媒體）、`config`（載入、覆寫、schema）、`greetings`（排程與預寫文案）、`utils`（各層共用的小工具，處理層可以 import）。
- **對外介面**：HTTP 路由（依 ADR 0021 分為 public、stage、admin 三類）；對各層只經由 `nova_contracts` 與各層的 adapter 或 `config_api` 呼叫。
- **狀態歸屬**：輪次狀態全部由核心持有，處理層不記住任何一場對話（ADR 0027）。
- **邊界**：`pyproject.toml` 的 import-linter 契約禁止處理層 import 核心（`nova_core.utils` 例外）。
- **測試**：`uv run --no-sync pytest core`；`tests/` 放核心的輪次、插話、交接、路由與設定測試。

其他層與契約見 [`contracts/README.md`](../contracts/README.md)；整體決定見 [ADR 0027](../docs/adr/0027-split-code-by-processing-layer.md) 與 [ADR 0028](../docs/adr/0028-monorepo-with-contracts-package.md)。
