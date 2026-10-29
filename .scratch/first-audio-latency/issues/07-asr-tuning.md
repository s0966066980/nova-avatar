<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 語音辨識加速與 FunASR 對照
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)。Whisper small 在應用中 0.42–0.59 s（benchmark 暖機中位 0.167 s）：語系 auto、beam 5、經暫存檔。FunASR 10/22 實際輪次 0.04–0.13 s；`docs/project-status.md` 寫場域用 FunASR，實際跑的是 Whisper。

- Whisper：依目前對話語系固定語言、beam 1、記憶體直傳（不寫暫存檔）。
- 以 issue 01 的錄音集比較 Whisper（調整後）與 FunASR 的延遲 P50／P95 與中英文字錯率，結果寫入 Comments，選擇較快且字錯率可接受者為預設，並修正文件。

## Comments
