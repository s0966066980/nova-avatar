<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Edge 測試用老師
Status: ready-for-agent
Blocked by: 03

依[規格](../spec.md)第 2、4 點與 ADR 0026。

- 從 jetson-orin 的 `distill_edge_teacher.py` 帶入並調整：以 `src.tts.edge_connection.EdgeConnectionPool` 逐句合成，失敗退避重試、句間等待。
- 內建句庫（問候、天氣、交通、口語、中英混合，約 900 句）取代對 `lexicon-zh.txt` 的依賴；可選「快速測試」約 15 分鐘或「標準」約 1 小時，也接受管理者上傳的文字檔。
- 聲線可選 Edge 的 zh-TW 聲音，預設 HsiaoChen；英文句由同一聲音念。
- 合成後做品質檢查（長度、音量、faster-whisper 比對），並寫成 03 的語料，來源為測試用老師。
- 啟動前必須取得「已閱讀並確認 MSA 條文」的紀錄；沒有確認紀錄時拒絕開始。
- 測試以假的 Edge 連線進行，不連網。

## 範圍補充（2026-11-24）

- 只做服務層：提供可由背景工作呼叫的合成函式與進度回呼（逐句進度、可取消），**不新增路由**；路由與工作排程由 05、06 負責。
- 使用 `src/tts/training/` 的語料 API（工單 03 Comments），不要另建儲存格式。
- 「已確認 MSA 條文」的紀錄放在語料資料夾的來源宣告旁，由服務層檢查。
