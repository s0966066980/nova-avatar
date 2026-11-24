<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 疊字評量腳本
Status: ready-for-agent

依[規格](../spec.md)「疊音與跳音診斷」與驗收。把診斷時的做法固定成可重複的評量，讓重訓後的聲線模型能和曉臻、base 模型直接比較。

- 固定測試集：12 句已知會疊音的句子與 12 句乾淨句（含中英混合），放在 `tools/` 下並進 git；每句合成 3 次。
- 以 Whisper 轉寫並用詞時間戳偵測相鄰重複音節或詞，輸出「疊字句數／總句數」與逐句結果 JSON；Whisper 用 CPU，不佔用 GPU；缺少模型時直接失敗，不得跳過。
- 以 `.venv` 的 sherpa-onnx 直接合成，不啟動伺服器；以假的合成器為單元測試，0 失敗、0 跳過。
- 基準數字：曉臻 17/36、base 1/24（診斷結果）；重訓後的模型目標是疊字句數不高於 base 的水準。
