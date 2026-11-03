<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

---
status: accepted
---

# 在 Jetson Orin 以單一角色與兩階段輕量閘門整合中央氣象署氣候工具

在 `jetson-orin` 分支中，中央氣象署（CWA）即時觀測與預報查詢直接作為目前數位人的內建工具運作，不引入 `main` 分支的雙數位人角色切換、雙素材預載與每輪 Speculative 雙 LLM 路由請求。此決策是針對 AGX Orin 共用記憶體與單機 `llama-server` 推論時 GPU 負載已達約 99% 的硬體限制，同時維持與[預錄呈現](0016-separate-prerecorded-presentation-and-asset-production.md)、[舞台語系](0017-session-owned-stage-language.md)及[對話附件](0018-session-owned-conversation-attachments.md)的完整相容。

本輪發話採兩階段輕量閘門：不含天氣線索且無待續天氣上下文的一般對話直接放行（0 ms 額外延遲，不發起路由 LLM 請求）；明確單一縣市（或沿用場域預設地點／本場對話已確認地點）與可解析日期的天氣提問由純 Python 規則直接組出查詢；僅在命中天氣線索但規則無法單獨拆解時才以結構化 JSON 呼叫本機模型解析。單純天氣查詢略過 RAGFlow 檢索以省下 BGE-M3 嵌入延遲，複合問題或有勾選本輪參考附件時則並行合併。查詢結果以防幻覺提示注入本輪 `rag_context`，由現有模型依助手身分、回覆規則與舞台語系產出口語摘要與看板回覆。

## Considered Options

- **移植 `main` 的雙數位人角色交接與每輪並行路由**：在 Orin 上需同時預載兩套數位人素材、增加高解析度轉場合成負擔，且同輪對本機 `llama-server` 並行發送路由與回答請求會造成佇列爭用並拉長首音延遲，亦與預錄呈現架構衝突。
- **固定中文範本直接播報（不經回答模型）**：無法回答結合氣象資料的生活建議追問，且無法隨每場對話的舞台語系（繁體中文／English）與助手身分自然調整表達。
