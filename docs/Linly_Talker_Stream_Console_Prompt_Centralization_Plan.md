# Linly-Talker-Stream：控制台集中管理「助手定義與 Prompt」重構計劃

## 1. 任務目的

目前專案的角色身份、Prompt、語言要求與回覆規則存在多個來源，造成：

- 控制台已改成「ITRI 助手」，LLM 仍可能自稱「Linly 數字人助手」。
- Prompt 已要求繁體中文，LLM 偶爾仍輸出簡體字。
- `AUTO_MODE_PROMPT`、`config/prompt.txt`、`runtime_overrides.yaml`、Session History 會互相影響。
- 修改 Prompt 後，舊 Session History 仍可能保留舊身份。
- 未來若將 ITRI 助手改成其他角色，需要到多個檔案搜尋與修改。

本次重構目標：

> **所有可編輯的角色定義、身份、語言要求、回答風格、System Prompt、Reply Rules，只能從控制台設定與保存。程式碼只保留協定、解析器、格式規則與技術性 fallback，不得再硬編碼 Linly、ITRI 或任何產品角色身份。**

---

# 2. 核心原則

## 2.1 Single Source of Truth

所有「助手行為定義」只有一個來源：

```text
Web 控制台
    ↓
Runtime Settings API
    ↓
config/runtime_overrides.yaml
    ↓
config.llm.assistant_profile
    ↓
compose_system_prompt()
    ↓
LLM
```

禁止：

```text
控制台 Prompt
+
config/prompt.txt
+
AUTO_MODE_PROMPT 角色範例
+
Python 內硬編碼角色名稱
+
舊 Session History
```

共同決定身份。

---

## 2.2 程式碼只能保留「協定」，不能保留「人物設定」

允許寫在程式碼：

```text
[[MODE:SIMPLE]]
[[MODE:BOARD]]
[[SPEECH]]
[[BOARD_JSON]]
[[END]]

BOARD JSON schema
SIMPLE / BOARD 的格式規則
response length rule
parser instruction
安全的技術 fallback
```

禁止寫在程式碼：

```text
你是 Linly 數字人助手
你是 ITRI 助手
你是櫃台人員
你來自某公司
你必須使用臺灣口音
你的個性是...
```

以上全部改由控制台設定。

---

# 3. 目前已確認的問題

## 3.1 `src/llm/prompts.py`

目前 `AUTO_MODE_PROMPT` 包含硬編碼：

```text
你好！我是 Linly 數位人助手，很高興為你服務。
```

這會與控制台的：

```text
你是 ITRI 助手
```

互相衝突。

### 必須修改

AUTO 範例改為完全中性，例如：

```text
[[MODE:SIMPLE]]
[[SPEECH]]
您好，很高興為您服務。
[[END]]
```

更建議：

```text
AUTO_MODE_PROMPT 只說明協定，不提供任何角色自我介紹範例。
```

---

## 3.2 `config/prompt.txt`

目前仍包含：

```text
你是 Linly 數字人助手...
```

`src/llm/base.py::load_system_prompt()` 在沒有 `llm.system_prompt` 時會 fallback 至此檔案。

### 必須修改

本次重構後：

```text
config/prompt.txt
```

不得再是 Runtime Prompt 來源。

處理方式：

- 移除 `load_system_prompt()` 對 `config/prompt.txt` 的 fallback。
- 可刪除 `config/prompt.txt`。
- 若為避免立即刪檔，可保留檔案但必須標記 deprecated，而且 Runtime 不得讀取。
- 所有角色 Prompt 由控制台保存至 runtime settings。

---

# 4. 新的集中設定資料結構

建議在：

```text
src/config/schema.py
```

新增：

```python
@dataclass
class AssistantProfileConfig:
    assistant_name: str = ""
    system_prompt: str = ""
    output_locale: str = "zh-TW"
    enforce_output_locale: bool = True
    forbidden_self_names: list[str] = field(default_factory=list)
```

並掛到：

```python
@dataclass
class LLMConfig:
    ...
    assistant_profile: AssistantProfileConfig = field(
        default_factory=AssistantProfileConfig
    )
```

---

# 5. 控制台應集中顯示的欄位

新增或整理一個區塊：

```text
LLM / 助手設定
```

只在這裡管理以下資料。

| 控制台欄位 | 用途 |
|---|---|
| 助手名稱 | 例如 `ITRI 助手` |
| System Prompt | 完整角色定義與回答原則 |
| 輸出語系 | 預設 `zh-TW` |
| 強制語系正規化 | 預設開啟 |
| 禁止自稱名稱 | 例如 `Linly`, `Linly 數字人助手` |
| Reply Rule：啟用規則 | SIMPLE / BOARD 判定偏好 |
| Reply Rule：口語規則 | 語音回答的風格 |
| Reply Rule：看板規則 | Board 內容風格 |
| 回覆字數 | `response_max_chars` |
| 看板項目上限 | `board.max_items` |

---

# 6. 建議的 ITRI 控制台初始設定

## 助手名稱

```text
ITRI 助手
```

## 輸出語系

```text
zh-TW
```

## 強制語系正規化

```text
true
```

## 禁止自稱名稱

```text
Linly
Linly 數字人助手
Linly 數位人助手
```

## System Prompt

控制台可以先使用：

```text
你是 ITRI 助手。

請依使用者問題提供準確、簡潔、自然且適合語音播報的回答。

身份規則：
- 當使用者詢問你是誰時，只能自稱「ITRI 助手」。
- 不得自稱 Linly、Linly 數字人助手、Linly 數位人助手或其他未在本 Prompt 定義的身份。
- 不要自行虛構組織、職稱、經歷或能力。

語言規則：
- 所有中文回答一律使用繁體中文。
- 使用臺灣常用詞彙與表達方式。
- 不得輸出簡體中文字形。
- 英文專有名詞、程式碼、模型名稱、檔案路徑可以保留原文。

回答風格：
- 優先直接回答問題。
- 回答適合語音朗讀。
- 避免不必要的 Markdown、表情符號與冗長開場。
- 不確定時應明確說明，不得編造。
```

此文字只存在：

```text
控制台設定
→ runtime_overrides.yaml
```

不得複製到 `src/llm/prompts.py` 或其他 Python 檔案。

---

# 7. Runtime Persistence 設計

目前：

```text
src/config/overrides.py
```

已會把設定面板內容寫入：

```text
config/runtime_overrides.yaml
```

本次將 `assistant_profile` 一併保存。

建議格式：

```yaml
llm:
  model: qwen3.5:4b
  provider: ollama
  base_url: http://localhost:11434/v1

  assistant_profile:
    assistant_name: ITRI 助手
    output_locale: zh-TW
    enforce_output_locale: true
    forbidden_self_names:
      - Linly
      - Linly 數字人助手
      - Linly 數位人助手
    system_prompt: |
      你是 ITRI 助手。
      ...

  response_max_chars: 120

  reply_rules:
    revision: 1
    activation: |
      ...
    speech: |
      ...
    board: |
      ...
```

---

# 8. `system_prompt` 欄位相容性

目前專案已存在：

```text
config.llm.system_prompt
```

為避免一次大改造成 regression，建議分兩階段。

## Phase 1

保留：

```python
config.llm.system_prompt
```

但 Runtime API / UI 只操作：

```text
llm.assistant_profile.system_prompt
```

Loader 做一次 compatibility mapping：

```python
if assistant_profile.system_prompt:
    use assistant_profile.system_prompt
elif legacy llm.system_prompt:
    migrate legacy value
```

## Phase 2

測試完成後移除 legacy：

```text
llm.system_prompt
config/prompt.txt
```

最終只保留：

```text
llm.assistant_profile.system_prompt
```

---

# 9. `compose_system_prompt()` 重構

檔案：

```text
src/llm/prompts.py
```

最終 Prompt 組合：

```text
Assistant Profile / System Prompt
        +
Output Protocol
        +
Reply Mode Protocol
        +
Reply Rules
        +
Board Context
        +
Length Instruction
```

重要：

```text
Output Protocol
Reply Mode Protocol
Board Protocol
```

不得包含任何：

```text
Linly
ITRI
角色名稱
組織名稱
固定人格
固定語言身份
```

---

# 10. 移除所有硬編碼角色名稱

Codex 必須全專案搜尋：

```text
Linly 數字人助手
Linly 數位人助手
我是 Linly
你是 Linly
ITRI 助手
我是 ITRI
你是 ITRI
```

分類：

## 可保留

專案名稱：

```text
Linly-Talker-Stream
```

README 中描述原專案名稱也可以保留。

## 必須移除

任何會進入：

```text
LLM system prompt
few-shot prompt
runtime prompt
reply rule
fallback response
```

的角色名稱。

---

# 11. Prompt 更新後清除舊 Session Identity

目前：

```text
src/llm/service.py
```

`switch_llm_endpoint()` 會更新：

```python
llm.system_prompt = system_prompt
```

但不一定清除既有 conversation history。

這會造成：

```text
舊 Prompt：Linly
↓
History 已存在：
Assistant: 我是 Linly 數字人助手
↓
改 Prompt：ITRI
↓
舊 History 仍存在
↓
模型再次回答 Linly
```

---

## 修改規則

只有以下資料改變時清理對話：

```text
assistant_name
system_prompt
output_locale
forbidden_self_names
```

實作概念：

```python
profile_changed = old_profile != new_profile

if profile_changed:
    llm.system_prompt = new_prompt
    llm.clear_history()
    llm.set_last_board(None)
```

同時清除：

```text
pending board
displayed board context
pending history transaction
```

如果有這些狀態。

---

# 12. 控制台保存後立即套用

控制台按下：

```text
儲存
```

之後必須完成：

```text
前端送出設定
    ↓
Runtime Settings API
    ↓
驗證
    ↓
更新 config
    ↓
persist_runtime_overrides()
    ↓
更新現有 LLM instance
    ↓
若 Profile 有變更 → clear history
    ↓
回傳新的 current_snapshot
```

不應要求：

```text
重新啟動整個服務
```

才能生效。

重啟之後也必須從：

```text
runtime_overrides.yaml
```

恢復相同設定。

---

# 13. 繁體中文不能只靠 Prompt

Prompt 是 soft constraint。

即使寫：

```text
只用繁體中文
```

Qwen / Ollama / llama.cpp 仍可能偶爾產生：

```text
软件
信息
视频
用户
数据
支持
```

因此新增 deterministic output normalizer。

---

# 14. 新增 `src/llm/text_normalizer.py`

專案已依賴：

```text
opencc>=1.1.9
```

新增：

```python
from opencc import OpenCC

_TW = OpenCC("s2twp")


def normalize_output_text(
    text: str,
    *,
    locale: str = "zh-TW",
    enabled: bool = True,
) -> str:
    if not text or not enabled:
        return text

    if locale.lower() == "zh-tw":
        return _TW.convert(text)

    return text
```

---

# 15. Normalizer 套用位置

不要直接轉完整 raw protocol。

錯誤：

```text
raw LLM output
→ OpenCC
→ parser
```

正確：

```text
raw LLM output
        ↓
ResponseProtocolParser
        ↓
  ┌─────┴─────┐
  │           │
SPEECH       BOARD
  │           │
OpenCC       OpenCC
  │           │
  ├── TTS     ├── title
  ├── Caption ├── summary
  └── History └── item title/content
```

---

# 16. 必須正規化的內容

至少：

```text
spoken_response
TTS input
Caption
Board title
Board summary
Board item title
Board item content
History assistant response
```

確保：

```text
模型 raw output = 软件支持用户
```

經過系統後變：

```text
軟體支援使用者
```

而且 History 儲存的也必須是：

```text
軟體支援使用者
```

不能保存簡體版本。

---

# 17. Identity Guard

除了 Prompt，也增加簡單 deterministic guard。

目的不是改寫所有內容，而是防止已知舊角色名稱漏出。

建立：

```python
def normalize_assistant_identity(
    text: str,
    *,
    assistant_name: str,
    forbidden_names: list[str],
) -> str:
```

只有當輸出是明確自我身份陳述時才處理。

不要做：

```text
全域 replace("Linly", "ITRI")
```

因為使用者可能在詢問：

```text
Linly-Talker-Stream 是什麼？
```

此時不可亂改專案名稱。

---

# 18. Identity Guard 建議策略

優先靠：

```text
System Prompt
+
清 History
```

Identity Guard 只作最後保險。

可以檢測常見形式：

```text
我是 Linly...
我叫 Linly...
我是 Linly 數字人助手...
```

若命中禁止身份，再替換「自稱片段」。

不要處理：

```text
Linly-Talker-Stream
Linly 專案
原始 Linly 架構
```

---

# 19. 控制台 UI 重構

Codex 請搜尋現有前端：

```text
system_prompt
reply_rules
response_max_chars
board_max_items
```

找到目前設定頁。

將分散欄位整理成：

```text
對話 / 助手設定
```

建議版面：

```text
┌────────────────────────────┐
│ 助手設定                    │
├────────────────────────────┤
│ 助手名稱                    │
│ [ ITRI 助手              ] │
│                            │
│ 輸出語系                    │
│ [ zh-TW ▼ ]                │
│                            │
│ ☑ 強制轉為繁體臺灣用語     │
│                            │
│ 禁止自稱名稱                │
│ [ Linly                  ] │
│ [ Linly 數字人助手       ] │
│                            │
│ System Prompt              │
│ ┌────────────────────────┐ │
│ │ ...                    │ │
│ └────────────────────────┘ │
├────────────────────────────┤
│ Reply Rules                │
│ 啟用規則                    │
│ 口語規則                    │
│ 看板規則                    │
├────────────────────────────┤
│ 回覆字數                    │
│ 看板項目上限                │
│                            │
│ [儲存設定]                  │
└────────────────────────────┘
```

---

# 20. 控制台增加「最終 Prompt 預覽」

建議新增：

```text
最終 System Prompt 預覽
```

用途：

讓開發者知道真正送給 LLM 的內容。

預覽必須包含：

```text
assistant_profile.system_prompt
+
mode protocol
+
reply rules
+
length instruction
```

但不要顯示：

```text
conversation history
使用者私人對話內容
```

可以提供：

```text
Preview composed prompt
```

的 debug endpoint。

---

# 21. 控制台增加「目前生效來源」

建議顯示：

```text
Prompt Source:
Runtime Console

Last updated:
<timestamp>

Session history reset:
Yes / No
```

禁止顯示：

```text
config/prompt.txt
AUTO_MODE_PROMPT identity
```

作為角色來源。

---

# 22. `load_system_prompt()` 最終行為

修改：

```text
src/llm/base.py
```

不要再讀：

```text
config/prompt.txt
```

建議：

```python
def load_system_prompt(config=None) -> str:
    profile = getattr(
        getattr(config, "llm", None),
        "assistant_profile",
        None,
    )

    prompt = str(
        getattr(profile, "system_prompt", "") or ""
    ).strip()

    if prompt:
        return prompt

    raise RuntimeError(
        "Assistant System Prompt 尚未在控制台設定"
    )
```

若不希望啟動失敗，可以用中性技術 fallback：

```text
You are a helpful assistant.
```

但 fallback：

- 不得包含 Linly
- 不得包含 ITRI
- 不得包含任何公司身份

並應記錄 warning。

---

# 23. `DEFAULT_BASE_PROMPT` / `DEFAULT_SYSTEM_PROMPT`

目前：

```text
You are a helpful assistant.
```

可以保留作技術 fallback。

禁止改成：

```text
You are ITRI assistant
```

因為角色身份仍會再次分散進程式碼。

---

# 24. Reply Rules 也納入控制台

目前：

```text
activation
speech
board
```

已可被 runtime config 保存。

本次不要再在其他 Python 檔加入產品專用語意。

例如不要寫：

```python
SPEECH_RULE = "ITRI 助手要..."
```

Reply Rules 只能來自控制台。

---

# 25. Runtime Override 優先權

最終優先權明確定義：

```text
1. 控制台 runtime_overrides.yaml
2. 中性的 schema 技術預設
```

禁止再有：

```text
3. config/prompt.txt
4. prompts.py 裡的角色範例
5. 某 engine 內自己的角色 Prompt
```

---

# 26. 建議資料流

```text
┌──────────────────────────────┐
│ Web 控制台                    │
│                              │
│ assistant_name               │
│ system_prompt                │
│ output_locale                │
│ enforce_output_locale        │
│ forbidden_self_names         │
│ reply_rules                  │
└───────────────┬──────────────┘
                │ Save
                ▼
┌──────────────────────────────┐
│ runtime_settings.py          │
│ validate + apply             │
└───────────────┬──────────────┘
                ▼
┌──────────────────────────────┐
│ runtime_overrides.yaml       │
│ Single Source of Truth       │
└───────────────┬──────────────┘
                ▼
┌──────────────────────────────┐
│ config object                │
└───────────────┬──────────────┘
                ▼
┌──────────────────────────────┐
│ compose_system_prompt()      │
│ profile + protocol + rules   │
└───────────────┬──────────────┘
                ▼
              LLM
                │
                ▼
       ResponseProtocolParser
                │
       ┌────────┴────────┐
       ▼                 ▼
     SPEECH             BOARD
       │                 │
       ▼                 ▼
    zh-TW normalize   zh-TW normalize
       │                 │
   ┌───┼────┐            ▼
   ▼   ▼    ▼          Web UI
  TTS UI  History
```

---

# 27. 需要修改的主要檔案

## 必改

```text
src/config/schema.py
```

功能：

- 新增 `AssistantProfileConfig`
- 掛到 `LLMConfig`

---

```text
src/config/overrides.py
```

功能：

- Persist `assistant_profile`
- 確保 restart 後設定不遺失

---

```text
src/server/runtime_settings.py
```

功能：

- Snapshot
- Validation
- Apply assistant profile
- Prompt change detection
- Session reset
- Persist

---

```text
src/llm/prompts.py
```

功能：

- 移除所有角色身份硬編碼
- AUTO / SIMPLE / BOARD 只留下協定

---

```text
src/llm/base.py
```

功能：

- 移除 `config/prompt.txt` Runtime fallback
- 使用集中 profile
- LLM output normalization

---

```text
src/llm/service.py
```

功能：

- Profile 改變時更新所有 session
- 清除 conversation history / board context

---

## 新增

```text
src/llm/text_normalizer.py
```

功能：

- zh-TW `OpenCC("s2twp")`
- 統一 Speech / Board / History output

---

## 前端

Codex 搜尋：

```text
system_prompt
reply_rules
response_max_chars
```

找到設定頁後：

- 新增 Assistant Profile UI
- 統一欄位
- 加 Preview
- 儲存後立即套用

---

# 28. 不應修改的範圍

本次不要修改：

```text
MuseTalk
AvatarTransition
MouthContinuity
TTS inference
Fun-CosyVoice3 zero-shot
ASR
VAD
WebRTC timing
Audio queue
Video queue
LLM model server protocol
```

本次只有：

```text
Assistant Profile
Prompt
Reply Rules
Language normalization
Runtime settings
Session reset
Console UI
```

---

# 29. 測試需求

至少新增：

```text
tests/test_assistant_profile.py
tests/test_llm_text_normalizer.py
```

若已有適合測試檔，可擴充現有檔案。

---

# 30. Test：身份只有一個來源

設定：

```text
assistant_name = ITRI 助手
system_prompt = 你是 ITRI 助手...
```

驗證：

```text
compose_system_prompt()
```

包含：

```text
ITRI 助手
```

且不得包含：

```text
Linly 數字人助手
Linly 數位人助手
```

---

# 31. Test：AUTO_MODE_PROMPT 不含身份

直接 assert：

```python
assert "Linly" not in AUTO_MODE_PROMPT
assert "ITRI" not in AUTO_MODE_PROMPT
```

也可加：

```python
assert assistant_name not in protocol prompt
```

---

# 32. Test：Prompt 更新立即套用

流程：

```text
Session 使用 Linly 舊 Prompt
↓
建立 history
↓
控制台更新為 ITRI
↓
existing llm.system_prompt 更新
↓
history cleared
↓
board context cleared
```

assert：

```text
下一輪只看到新 Prompt
```

---

# 33. Test：單純修改非身份設定不清 History

例如只改：

```text
response_max_chars
board_max_items
```

不要清除 History。

---

# 34. Test：繁體中文正規化

輸入：

```text
这个软件支持视频和用户数据。
```

`zh-TW + enforce=true`

預期：

```text
這個軟體支援視訊和使用者資料。
```

至少確認：

```text
软件
视频
用户
数据
```

不再存在。

---

# 35. Test：英文與程式碼不應被破壞

輸入：

```text
OpenAI API 使用 Python FastAPI。
```

正規化後：

```text
OpenAI
API
Python
FastAPI
```

必須保持。

---

# 36. Test：Board 同樣轉繁體

Raw：

```json
{
  "title": "软件功能",
  "items": [
    {
      "title": "视频",
      "content": "支持用户查看数据"
    }
  ]
}
```

UI 前：

```text
軟體功能
視訊
支援使用者查看資料
```

---

# 37. Test：History 保存 normalize 後內容

LLM Raw：

```text
这个软件支持视频。
```

TTS：

```text
這個軟體支援視訊。
```

History 也必須是：

```text
這個軟體支援視訊。
```

不能保存 raw 簡體。

---

# 38. Test：Identity Guard 不破壞專案名稱

輸入：

```text
Linly-Talker-Stream 是一個數字人專案。
```

不得變成：

```text
ITRI 助手-Talker-Stream
```

---

# 39. Test：重啟後設定仍存在

流程：

```text
Console Save
↓
persist_runtime_overrides
↓
reload config
```

驗證：

```text
assistant_name
system_prompt
output_locale
enforce_output_locale
forbidden_self_names
reply_rules
```

全部一致。

---

# 40. 靜態搜尋驗收

Codex 完成後執行：

```bash
rg -n \
  "我是 Linly|你是 Linly|Linly 數字人助手|Linly 數位人助手|我是 ITRI|你是 ITRI" \
  src config tests
```

允許：

```text
tests fixture
migration test
README / docs
```

禁止：

```text
src/llm/prompts.py
src/llm/base.py
src/llm/engines/*
src/server/*
```

存在會進 Runtime Prompt 的角色身份。

---

# 41. 實際測試命令

先跑 targeted：

```bash
uv run pytest -q tests/test_assistant_profile.py
uv run pytest -q tests/test_llm_text_normalizer.py
```

再跑 LLM / runtime：

```bash
uv run pytest -q tests -k "llm or prompt or runtime or rule"
```

compile：

```bash
uv run python -m compileall \
  src/config \
  src/llm \
  src/server/runtime_settings.py
```

最後：

```bash
uv run pytest -q
```

---

# 42. 實際 Runtime 驗證

Codex 必須啟動服務或使用等效 integration test 驗證。

## Case A：身份

控制台：

```text
助手名稱：
ITRI 助手
```

Prompt：

```text
你是 ITRI 助手...
```

問：

```text
你是誰？
```

預期：

```text
我是 ITRI 助手。
```

不得：

```text
我是 Linly...
```

---

## Case B：簡體

問：

```text
請介紹你的软件和视频功能
```

即使 LLM raw 可能出簡體，最終：

```text
Caption
TTS
Board
History
```

不得出現：

```text
软件
视频
用户
数据
支持
```

---

## Case C：Prompt 即時切換

先設定：

```text
助手名稱 A
```

對話數輪。

不重啟服務，控制台改：

```text
助手名稱 B
```

下一輪：

```text
你是誰？
```

必須只回答 B。

---

# 43. Acceptance Criteria

全部符合才可宣告完成。

```text
[ ] 角色身份只由控制台設定

[ ] System Prompt 只由控制台設定

[ ] Reply Rules 只由控制台設定

[ ] Output Locale 只由控制台設定

[ ] AUTO_MODE_PROMPT 不包含 Linly / ITRI

[ ] SIMPLE_MODE_PROMPT 不包含角色身份

[ ] BOARD_MODE_PROMPT 不包含角色身份

[ ] config/prompt.txt 不再是 Runtime Prompt 來源

[ ] runtime_overrides.yaml 是唯一持久化角色設定來源

[ ] Prompt 更新可立即套用

[ ] Profile 改變會清除舊 Session History

[ ] 非 Profile 設定改變不會亂清 History

[ ] Speech 強制繁體臺灣用語

[ ] Board 強制繁體臺灣用語

[ ] Caption 強制繁體臺灣用語

[ ] History 保存的是正規化後文字

[ ] 不會全域 replace Linly 專案名稱

[ ] 重啟後設定不遺失

[ ] Targeted tests PASS

[ ] Compile PASS

[ ] Full pytest 已實際執行
```

---

# 44. Codex 執行規則

不要只修改程式後停止。

必須：

```text
讀現有架構
↓
確認 Prompt / runtime settings / history 資料流
↓
實作 Single Source of Truth
↓
更新控制台
↓
新增 migration / compatibility
↓
新增 tests
↓
跑 targeted tests
↓
修失敗
↓
跑 full pytest
↓
實際 runtime 驗證
↓
直到 acceptance criteria 全部成立
```

禁止：

```text
skip test
xfail
刪除既有 assertion
用硬編碼 ITRI 取代硬編碼 Linly
只修改 prompt.txt
只修改 AUTO_MODE_PROMPT
只靠 Prompt 解決繁體問題
```

---

# 45. 最終回報格式

Codex 完成後請回報：

## A. Single Source of Truth

```text
角色設定來源：
<實際來源>

Legacy Prompt Sources：
<已移除 / deprecated 項目>
```

## B. 修改檔案

列出：

```text
file
- 修改內容
- 原因
```

## C. 控制台欄位

列出目前可在 UI 管理的：

```text
assistant_name
system_prompt
output_locale
enforce_output_locale
forbidden_self_names
reply_rules
response_max_chars
board_max_items
```

## D. Session 行為

```text
Profile 改變：
history reset = YES

非 Profile 設定：
history reset = NO
```

## E. 繁體輸出

```text
Speech normalized = PASS
Board normalized = PASS
Caption normalized = PASS
History normalized = PASS
```

## F. 測試

```text
assistant profile tests:
xx passed

normalizer tests:
xx passed

LLM/runtime tests:
xx passed

compileall:
PASS

full pytest:
xxx passed / x failed
```

## G. Runtime 驗證

```text
「你是誰？」：
實際回答 = ...

簡體測試：
實際最終文字 = ...

Prompt A → Prompt B 不重啟：
PASS / FAIL
```

---

# 46. 完成判定

只有以下全部成立：

```text
角色定義集中
+
Prompt 集中
+
Reply Rules 集中
+
控制台可修改
+
即時套用
+
Restart 可保存
+
舊 Session 不污染新身份
+
繁體 deterministic normalize
+
Tests PASS
+
Runtime Test PASS
```

才可宣告：

```text
「助手定義與 Prompt 已完成控制台集中化，
Runtime 不再依賴分散硬編碼身份，
角色切換與繁體輸出已具備一致且可驗證的行為。」
```
