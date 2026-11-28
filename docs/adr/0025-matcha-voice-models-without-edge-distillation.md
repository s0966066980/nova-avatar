<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Matcha 聲線模型作為可選 TTS 引擎，不以 Edge 輸出蒸餾

新增在 CPU 上執行的 Matcha-TTS（sherpa-onnx ONNX 推理）作為第三種可選 TTS 引擎，出廠預設仍是 Edge TTS。這個引擎的聲音單位是「聲線模型」：數位人設定檔選一個聲線模型，中文和英文都由它負責，不需要參考音檔。聲線模型必須附有使用限制標示，沒有標示的不會出現在選項中。引擎與預設參數照 jetson-orin 分支移植；該分支和 main 已大幅分歧，所以採手動移植，不做 cherry-pick。

訓練與蒸餾流程**刻意不使用 Edge TTS 當老師**，也不用 Edge 做試聽預覽。Microsoft Services Agreement §14(s)(iv)（2026-09-30 生效）規定「You may not use the AI services, or data from the AI services, to create, train, or improve (directly or indirectly) any AI technology」，這條沒有區分商用和非商用。Edge 朗讀端點是否在 MSA 的適用範圍內雖然還沒確認，但風險仍然存在。jetson-orin 分支的 `distill_edge_teacher.py` 和 Edge 試聽預覽都不移植。老師只能用 CosyVoice3 搭配已授權的參考音檔，或者用真人錄音。

已經用 Edge 蒸餾出來的 `zh-tw-hsiaochen-edge` 標示為 `Development only`，做法跟 Edge 和未授權的參考音檔一致：只做標示，系統不阻擋使用，也不散佈。base 模型 `dengcunqin/matcha_tts_zh_en_20251010` 在 ModelScope 上標示 Apache-2.0，但訓練資料沒有說明，可能包含限非商用的 Baker 資料集。因此 base 模型和從它微調出來的所有聲線模型，在資料授權確認之前一律標示 `Research / Non-commercial`。

## Considered Options

- **直接 cherry-pick jetson-orin 的 commit**：不採用。那個 commit 同時刪除了 main 仍在使用的 BreezyVoice 和 Edge worker 程式碼，而且兩個分支都有兩百多個對方沒有的 commit。
- **把 hsiaochen-edge 標為 Research / Non-commercial，視為可在場域使用**：不採用。MSA 的禁止條款不限於商用。
- **硬性禁止 Development only 的聲線模型上舞台**：不採用。main 對 Edge 和開發用參考音檔一向只做標示；硬性阻擋的話，連在控制台試用都沒辦法。

規格見 Matcha 聲線模型。本決策修訂 ADR 0006 的 TTS 引擎清單。

## 2026-11-24 修訂

「訓練與蒸餾流程不使用 Edge 當老師」這一項由 [ADR 0026](0026-edge-as-test-only-matcha-teacher.md) 修訂：Edge 可作為僅限測試的老師，附限制。其餘決定（Matcha 為可選引擎、聲線模型必須有使用限制標示、base 模型標示 Research / Non-commercial）不變。
