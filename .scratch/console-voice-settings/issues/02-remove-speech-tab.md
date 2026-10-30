<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 移除「語音辨識與合成」頁
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)「移除語音辨識與合成頁」「預設聲音」。

- 語音辨識（引擎、模型、繁簡輸出）移到「訪客互動」頁並改名「訪客互動與語音辨識」。
- 移除全域 TTS 設定 UI；尚未套用設定檔時使用主數位人的聲音（後端：全域 TTS 由主數位人設定檔決定；舊的 `runtime_overrides.yaml` `tts` 區塊不再是第二個來源，處理方式與測試寫入 Comments）。
- 移除只為該頁存在的程式與測試；更新文件與控制台說明文字。

## Comments
