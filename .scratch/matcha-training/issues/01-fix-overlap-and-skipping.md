<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 診斷並修正疊音與跳音
Status: needs-triage

依[規格](../spec.md)第 1 點。管理者在舞台聽到 `zh-tw-hsiaochen-edge` 有疊音與跳音。診斷代理已在離線重現（比對 main 的引擎、jetson-orin 原版與直接呼叫 sherpa-onnx），結果寫回本工單 Comments 後，再補上確切的修正範圍並改為 ready-for-agent。

待驗證的原因：sherpa callback 重複送出樣本、`pcm_emitter` 在片段邊界裁切或重複、取樣率處理、CPU 與 MuseTalk／LLM 搶資源造成斷續、共用模型併發、模型或詞典前端本身（含訓練時數字被丟掉造成的文字與音檔錯位）。

驗收：同一組測試句在離線比對下無重複片段、無明顯爆音或空洞；實機舞台再聽一次確認。若原因在模型本身，改記為需要重新訓練的後續項目。
