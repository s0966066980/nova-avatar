<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 前一輪本機驗證：補存的歷史基線

記錄日期：2026-11-17
證據性質：recovered；不是重新執行，也不是新流程的驗收通過紀錄。

## 來源與可信範圍

原始日誌來自前一輪對目前專案的本機 CI 檢查。本次將它們從 `/tmp` 複製到
同目錄，保留原文；SHA-256 清單在 `evidence-sha256.json`。

當時沒有保存來源 commit SHA、工作目錄 diff、每個命令的開始／結束時間、完整
環境清單或 JUnit 報告。因此這份證據可以解釋先前數字的來源，不能冒充已具備
完整來源追溯的 release 驗收。後續各階段使用新範本，在執行前記錄這些資訊。

本次盤點時的 HEAD 是 `b1afdce7429eb166d3d36f6e233a07a14fbc2d52`，
不是執行當下已保存的 commit 證據。

## 已知執行方式

- Python：獨立暫存虛擬環境，Python 3.11.16；依 `dev`、`ci` 與 `vad` 安裝，
  使用 `--no-sources --torch-backend cpu`。沒有取代場域的 GPU `.venv`。
- 前端：Node.js 22.23.5；`npm ci` 後執行 audit、lint、test、build。
- 這些是本機執行結果，沒有查驗 GitHub-hosted run 或合併保護設定。

## 結果與原始日誌

| 檢查 | 已知結果 | 原始日誌 |
| --- | --- | --- |
| `uv lock --check` | 退出碼 0 | [lock](python-lock.log) |
| Python 安裝 | 退出碼 0 | [install](python-install.log) |
| Ruff | 退出碼 0 | [ruff](python-ruff.log) |
| Pyright | 退出碼 0，0 errors | [pyright](python-pyright.log) |
| 離線整合／品牌稽核 | 退出碼 0 | [integration](python-integration.log) |
| `pytest` | 退出碼 0；1526 passed、3 skipped、5 warnings | [pytest](python-pytest.log) |
| `npm ci` | 退出碼 0 | [install](frontend-install.log) |
| `npm audit --omit=dev` | 退出碼 0；0 vulnerabilities | [audit](frontend-audit.log) |
| ESLint | 退出碼 0 | [lint](frontend-lint.log) |
| Node 測試 | 退出碼 0；261 passed、0 skipped | [test](frontend-test.log) |
| Vite 正式建置 | 退出碼 0 | [build](frontend-build.log) |

退出碼依前一輪工具輸出補記，原始 `.log` 沒有逐項內嵌退出碼。下一輪必須在
各命令結束時直接保存退出碼，而不是事後只看日誌文字。

Python 5 個警告來自 Silero VAD 使用已棄用的 `importlib.resources.path`。
測試檔與 3 個跳過案例的逐項解說見 [盤點](../../test-inventory.md)。
