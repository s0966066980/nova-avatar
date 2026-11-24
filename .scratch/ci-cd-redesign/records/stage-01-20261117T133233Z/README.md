<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 第 1 階段：隔離環境與依賴準備

執行狀態：依賴準備完成；另有版本固定與開發依賴審計的設計待決事項
理解確認：pending
日期：2026-11-17（各命令時間以 UTC 保存）
執行識別碼：`20261117T133233Z`

## 本階段要回答什麼

這份程式能否在指定版本的 Python／Node 環境安裝所需依賴？安裝後套件彼此是否
相容、是否真的使用 CPU PyTorch，以及實際安裝版本能否追查？

安裝成功不代表功能正確。本階段沒有執行 lint、功能測試或正式建置；案例數、
pass/fail/skip 與 JUnit 不適用。先前的 1526／261 結果沒有計入本次執行。

## 來源與隔離方式

- 來源 commit：`b1afdce7429eb166d3d36f6e233a07a14fbc2d52`。
- 執行前確認已追蹤檔案沒有相對 HEAD 的差異，以 `git archive` 建立乾淨來源快照。
- 本次新增文件及既有未追蹤檔案不在快照內；忽略的場域資料、模型、runtime
  overrides 與秘密設定也沒有複製。這是離線 CI 準備環境，不是場域執行環境。
- 工作區：`/home/oliver/.cache/nova-avatar/ci-validation/20261117T133233Z/`。
- 快照：工作區下 `source/`；Python 環境：`python311-cpu/`；前端依賴安裝於
  快照的 `source/web/node_modules/`。後續階段可沿用這份已記錄的環境。
- 未安裝到原專案 `.venv` 或原專案 `web/node_modules`；沒有修改 workflow 或 lock。
- archive SHA-256、開始時間與輸入檔 hash 在 [manifest.json](manifest.json)。
- 工作目錄狀態見 [執行前](working-tree-status-before.txt)、
  [執行後](working-tree-status-after.txt)；原已追蹤差異見 [tracked-before.diff](tracked-before.diff)。

## 操作與結果

完整精確命令、cwd、環境覆寫、起迄時間、退出碼在
[Python 命令](python-commands.json)、[前端命令](frontend-commands.json)、
[原生工具重驗](frontend-recheck-commands.json)、[審計命令](frontend-audit-commands.json)。

| 操作 | 結果 | 這代表什麼 |
| --- | --- | --- |
| `uv --version` | 0.11.21 | 與目前 workflow 指定版本一致 |
| `uv lock --check` | 退出碼 0 | 目前 lock 與 pyproject 相容；不代表下一步必然依 lock 安裝 |
| 建立獨立 Python 環境 | Python 3.11.16 | 不使用原專案 Python 3.10 環境 |
| 安裝 `dev`、`ci`、`vad`，CPU backend | 退出碼 0 | 目前約束可以解析並安裝 |
| `uv pip check` | 退出碼 0 | 已安裝套件的依賴 metadata 沒有回報衝突 |
| PyTorch CPU 確認 | 2.5.0+cpu，`torch.version.cuda` 為 null | 安裝的是 CPU build；不測試實際 GPU |
| 前端 Node／npm | Node 22.23.5／npm 11.16.0 | 本次實際使用 Node 22；現有 workflow 未顯式固定 npm 版本 |
| `npm ci` | 退出碼 0；新增 169 packages | package-lock 可供這份環境安裝 |
| `npm ls --all --json` | 退出碼 0 | 安裝後 npm 依賴樹檢查通過 |
| 直接執行 esbuild `--version` | 重驗退出碼 0；0.21.5 | 原生工具可執行；未進行 Vite build |
| 全依賴 `npm audit --json` | 退出碼 1；4 moderate、1 high | 有 5 個受影響套件項目，不是「安裝失敗」或「5 個功能測試失敗」 |
| 正式依賴 `npm audit --omit=dev --json` | 退出碼 0；0 vulnerabilities | 本次正式依賴集合未被 npm 回報已知問題；不等於完整安全保證 |

實際安裝清單：[Python freeze](python-installed-packages.log)、
[Python metadata JSON](python-installed-packages.json)、
[前端依賴樹](frontend-dependency-tree.log)。
本次沒有出現跳過的檢查，也沒有執行 `npm audit fix` 或變更套件版本設定。

## 發現一：目前 Python CI 沒有依 lock 版本安裝

現有 CI 先執行 `uv lock --check`，再以 `uv pip install --no-sources ...` 解析
`pyproject.toml` 的範圍約束。兩個操作的責任不同：前者確認 lock 相容，後者
沒有自動使用該 lock 的精確版本。

| 套件 | uv.lock | 本次實際安裝 |
| --- | --- | --- |
| pytest | 9.1.1 | 9.2.0 |
| silero-vad | 6.2.1 | 6.2.3 |
| Ruff | 0.17.1 | 0.17.1 |
| Pyright | 1.1.414 | 1.1.414 |

PyTorch 的 CPU／CUDA wheel 差異另有目的，不能把 CUDA lock 直接當成 CPU 環境
的完整安裝方案。原始版本對照見 [python-lock-comparison.json](python-lock-comparison.json)。

因此本次安裝可用，但不能宣稱「未來重建時一定取得相同依賴」。套件清單已保存，
後續可在同一環境逐階段驗證；新的 CI 仍需決定 CPU 依賴的固定方式。

建議的新政策是：CI 必須依已審查的鎖定版本安裝，不能只檢查 lock 後再自由解析。
這是待使用者確認的設計方向，本次沒有產生新 lock 或修改安裝流程。

## 發現二：開發依賴審計另有問題

全依賴審計列出 `@eslint/config-array`、`esbuild`、`eslint`、`minimatch` 與 `vite`。
正式依賴審計為 0，表示本次回報落在開發依賴集合。

原始結果：[全依賴 JSON](frontend-audit-all.json)、
[正式依賴 JSON](frontend-audit-production.json)。
現有 workflow 的正式依賴審計是 advisory；是否加入開發工具審計及何時阻擋，
尚未共同決定。審計結果依執行當時的 npm 資料庫，後續可能改變。

## 執行過程中的一次命令錯誤

最初以 `node node_modules/esbuild/bin/esbuild --version` 驗證工具，但該檔案是
原生 ELF 執行檔，Node 無法解析，退出碼 1。這是驗證命令錯用，不是依賴安裝失敗。

保留 [原始失敗日誌](frontend-esbuild-install-verification.log)，改成直接執行
`node_modules/.bin/esbuild --version` 後得到退出碼 0，見
[重驗日誌](frontend-esbuild-recheck.log)。失敗證據沒有被重跑覆蓋。

`npm ci` 另有 esbuild install-script allowlist 提示；本次沒有擴大授權執行安裝腳本，
直接執行工具的補充檢查通過。後續正式建置仍須獨立驗證。

## 如何在下一階段使用此環境

下列是環境選取說明，不表示已執行靜態檢查：

```bash
export NOVA_CI_SOURCE=/home/oliver/.cache/nova-avatar/ci-validation/20261117T133233Z/source
export UV_PROJECT_ENVIRONMENT=/home/oliver/.cache/nova-avatar/ci-validation/20261117T133233Z/python311-cpu
cd "$NOVA_CI_SOURCE"
```

Node 的實際 executable 與本次 PATH 覆寫保存在
[frontend-environment.json](frontend-environment.json)。使用後續前端命令時，
必須沿用它或重新確認 Node 22，不能默認系統 Node 24 等價。

## 證據與下一個節點

結構化結果：[result.json](result.json)。日誌及 JSON 的完整性清單：
[evidence-sha256.json](evidence-sha256.json)。

先等待使用者確認理解本階段結果，並確認是否採取「依鎖定版本安裝」政策。
若採取，先完成 CPU 依賴固定方案，再進入靜態檢查；不把現有安裝結果當成
可重現性問題已解決。審計門檻與套件升級則另外確認。
