<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

---
status: accepted
---

# 由控制台集中管理助手身分與 Prompt

助手名稱、System Prompt、限制 Prompt、輸出語系與禁止自稱名稱只由控制台保存為 `llm.assistant_profile`，經 Runtime Settings API 寫入 `config/runtime_overrides.yaml`，再由 `compose_system_prompt()` 組成送給 LLM 的提示詞。程式碼只保留回覆協定、解析器、格式規則與中性的技術 fallback，不得硬編碼任何產品角色身分；`config/prompt.txt` 與程式內角色範例不再是設定來源。

## Considered Options

- 保留 `prompt.txt`、程式預設與 runtime override 三方合併：拒絕，舊角色名稱會從任一來源漏出，修改角色時需搜尋多個檔案。
- 只靠 Prompt 要求繁體中文與正確身分：拒絕，模型偶爾仍輸出簡體或舊身分，需要確定性的後處理。
- 以全域字串取代舊名稱：拒絕，會誤改使用者詢問專案或上游來源時的正當內容。

## Consequences

- 優先權只有兩層：控制台 runtime override，其次是中性的 schema 預設。
- 身分相關欄位改變時清除對話 history 與看板上下文，避免舊 history 讓模型延續舊身分；其他設定變更不清除。
- 繁體正規化（OpenCC `s2twp`）在回覆協定解析之後才套用到語音、字幕、看板與 history，不處理原始協定輸出。
- 使用者未詢問身分時，只移除回答開頭的主動自我介紹；不改寫其他提及名稱的內容。
- 已在 2026-09-14 實作並有回歸測試；原任務規格已移除，細節見該提交的 Git 歷史。
