<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 設定介面
Status: ready-for-agent
Blocked by: 02

依[規格](../spec.md)第 6、7、11 點。

- 數位人設定檔編輯器：引擎多一個 Matcha 選項，選了之後出現聲線模型下拉選單；切換引擎時，不能把其他引擎的聲音帶過來（沿用 `switchTtsEngine` 的規則）。
- 在聲線模型名稱後面顯示使用限制標示（例如「Development only」），設定檔編輯器、角色組合、設定頁都要顯示。
- 介面說明寫出 hsiaochen-edge 的實測品質：中文 CER 13.2%、英文 WER 5.6%，以及 CPU 推理的特性。
- 補齊 zh-TW、zh-CN、en-US 三份 locales；前端測試 0 失敗、0 跳過。
