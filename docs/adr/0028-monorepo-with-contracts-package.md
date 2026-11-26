<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

---
status: accepted
---

# 維持單一 repo，各處理層各自宣告依賴，`contracts/` 是跨層契約的唯一來源

ADR 0027 依處理層劃分程式，但程式仍然維持在 `nova-avatar` 這一個 repo，每個處理層各占一個資料夾。理由如下：

- 只有一個部署目標，也就是一台場域主機。
- 跨層的介面還在演進，一個跨層修改（例如回覆語音串流）應該能在同一個 PR 完成。
- `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 和 `scripts/check-integration.py` 的改名稽核都只需要維護一份。

repo 留在維護者的個人帳號下，`CODEOWNERS` 改用個別帳號標示各段程式的負責人。

## 依賴

每個處理層都有自己的 `pyproject.toml`，宣告自己需要的依賴。

- **同一行程時**：所有處理層都在核心行程內，由根專案以 path 依賴引用，共用根目錄的 `uv.lock`。
- **拆成獨立行程時**：該層才改成獨立的 uv 專案，有自己的 lock 和 venv。

不採用 uv workspace 作為拆開後的形式，因為 workspace 只有一份 lock，容納不了互相衝突的依賴。例如已移除的 Fun-ASR-Nano 需要 transformers ≥ 4.51，MuseTalk 卻需要 < 4.47。

## 契約

- `contracts/` 只放跨層的 Pydantic 模型與各層的 Protocol，不帶任何重型依賴。
- 各服務的 OpenAPI 由這些模型產生並提交進 repo，CI 會檢查兩者是否一致。
- 契約不另外編版號。若要做破壞性變更，必須在同一個 PR 內同時修改核心與對應的處理層。
- 拆成行程後，服務在 `/health` 回報 `contract_version`，供執行時比對（ADR 0027）。

## 捨棄的方案

- **每層一個 repo**：每次跨層修改都要協調多個版本，授權稽核也得維護好幾份。目前只有一位主要維護者，換不到任何實際好處。
- **改到 GitHub Organization、用 team 設定 `CODEOWNERS`**：維護者決定先留在個人帳號。
