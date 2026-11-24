<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# CI/CD 逐步驗證地圖

更新日期：2026-11-17

## Notes

使用者不了解先前「Python 1526 通過、3 跳過；前端 261 通過」各自驗證了什麼，
要求重新設計 CI 的驗證步驟，逐步說明並留下紀錄，再推進 CI/CD。

目前工作是盤點、設計與保存證據。尚未修改 `.github/workflows/ci.yml`。

## Decisions-so-far

- 採前一輪建議的交付方向：CI 通過、產生可追溯版本、管理者核准場域更新、
  實機驗收、失敗可回退。部署細節與驗收門檻仍需後續確認。
- 現有總數只能作為歷史基線，不能直接代表真實模型、GPU、麥克風、喇叭與
  WebRTC 全鏈路已驗收。盤點與執行證據分開保存。
- 使用者已確認：按「驗證階段＋功能群組」記錄，另存完整案例清單。
- 使用者已確認：每完成一階段先解說並存檔，等使用者確認理解再進下一階段。
- 使用者於 2026-11-17 回覆「確認」，完成第 0 階段理解確認，進入第 1 階段。

- 使用者明確指定本版只做有 CUDA 的環境，取消本版 CPU-only 驗證路線；原 CPU 紀錄保留為歷史證據。

- 使用者回覆 `ok`，已完成第 1 階段 CUDA 補驗的理解確認，接續第 2 階段。

- 使用者再次回覆 `ok`，完成第 2 階段理解確認，已執行第 3 階段。

- 使用者回覆 `ok`，完成第 3 階段理解確認，接續第 4 階段 runtime 群組。

- 使用者回覆 `ok`，完成 runtime 群組理解確認，已執行 speech 群組。

- 使用者回覆 `ok`，完成 speech 群組理解確認，已執行 llm 群組。

- 使用者否決 Qwen3.8 選用豁免：該模型不在本版範圍，清理過期測試並建立現版主要基準。
- 使用者已選擇先完成本機基準與範圍清理，之後才處理 GitHub GPU runner。
- 本機現版基準已完整執行，Python 1515／前端 261 皆零失敗、零跳過。

## Fog

1. 新 CI 的分組、順序、跳過政策、失敗門檻與產物保存方式尚未共同確認。
2. 場域實機驗收使用哪一組實際設定、模型與聲音，以及通過條件，後續再確認；
   不直接採用其他歷史 spec 的模型組合。
3. CUDA 環境改依現有 lock frozen 安裝；現有 workflow 的 CPU 安裝與 runner 尚未更新。
   GPU runner 的實際位置與觸發方式仍待確認。
4. 第 1 階段全 npm audit 回報開發依賴 5 項，正式依賴為 0；開發工具審計門檻
   與升級範圍尚未決定。

5. 第 3 階段發現舊 lock／CI 契約測試要求 CPU 安裝選項；實作 CUDA-only workflow 時須同步更新該測試，不將舊契約通過誤記為新設計完成。

6. 舊 llm skip 提案已被使用者否決並取代：Qwen3.8 檔案需求已移除；現版基準不接受主要回歸 skip。

## 目前交付物

- [階段設計草案](spec.md)：每階段的目的與確認狀態。
- [測試範圍盤點](test-inventory.md)：各群組保護的行為、限制與可追查清單。
- [歷史基線](records/2026-11-17-recovered-baseline/README.md)：保存上一輪的原始日誌，
  明確標示沒有在執行當下記錄的資訊。
- [每階段執行紀錄範本](records/TEMPLATE.md)：後續逐步執行時填寫，不預填通過。
- [第 0 階段紀錄](records/2026-11-17-stage-00/README.md)：本次實際盤點與環境快照。
- [第 1 階段紀錄](records/stage-01-20261117T133233Z/README.md)：乾淨來源快照、隔離安裝、
  版本與退出碼、失敗重驗與依賴審計；其中 CPU 安裝現為歷史紀錄。
- [第 1 階段 CUDA 補驗](records/stage-01-cuda-20261117T134344Z/README.md)：本版採用的
  CUDA 環境、lock frozen 安裝與實際 GPU 運算檢查。
- [CPU／CUDA 用途說明](cpu-cuda-scope.md)：CPU 用於重現目前離線 CI；原專案
  `.venv` 經查仍為 CUDA build。兩層驗證提案已由使用者的 CUDA-only 決定取代，僅作背景說明。

- [第 2 階段紀錄](records/stage-02-20261117T135529Z/README.md)：CUDA 環境中的 Ruff、Pyright、ESLint 與實際檢查範圍。

- [第 3 階段紀錄](records/stage-03-20261117T135802Z/README.md)：離線稽核與 19 個 governance 案例的逐項結果、JUnit 與限制說明。

- [第 4 階段 runtime 紀錄](records/stage-04-runtime-20261117T140923Z/README.md)：242 案例通過；保留第一輪環境失敗與 Git metadata 補備後的重驗結果。

- [第 4 階段 speech 紀錄](records/stage-04-speech-20261117T141759Z/README.md)：279 案例通過、0 跳過；真實模型／音訊運算與替身分界、5 個警告及逐案證據。

- [第 4 階段 llm 紀錄](records/stage-04-llm-20261117T142627Z/README.md)：116 通過、1 跳過；個別 skip 原因與分類提案、真 binary help 與模型推理的界線。

- [現版主要測試基準完整結果](records/current-version-baseline-20261117T143902Z/README.md)：Python 1515、前端 261 通過，原始證據與範圍清理決策。

## 下一個節點

以 [目前版本測試指南](../../docs/current-version-testing.md) 與 JSON 定義作主要基準，
不再沿用舊的模型豁免與固定歷史總數。使用者目前要求的本機基準已完成。
接續審查基準範圍，再設定 GPU runner、接入 GitHub workflow 與補齊實機發布驗收。
舊逐階段紀錄保持歷史證據，不等於仍有待接受的 Qwen3.8 skip。
