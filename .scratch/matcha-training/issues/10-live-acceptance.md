<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 實機驗收
Status: ready-for-human
Blocked by: 01, 08, 09, 11, 14

依[規格](../spec.md)「驗收」。在實機上完整跑一次 Edge「快速測試」和一次自己的錄音，確認寫入的聲線模型出現在清單、標示正確、可在數位人設定檔選用，並在舞台試聽；再驗證舞台連線與顯存不足時的阻擋、取消後的 GPU 釋放，並用 11 的評量比較新模型與曉臻的疊字句數。結果與試聽意見寫在 Comments。

另需確認工單 01 的實機驗證：用 Matcha 聲線做一段會切成多片的長回覆，比對日誌中相鄰片段的空白，預期從 221–280 ms 降到約 20–50 ms，並在舞台再聽一次是否仍有跳音；若仍有，另開工單記錄逐幀時間（`put_audio_frame`）並錄 WebRTC 輸出。
