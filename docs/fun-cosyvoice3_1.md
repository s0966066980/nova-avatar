# 任務

請修改目前專案：

`https://github.com/s0966066980/nova-avatar`

目標是改善：

```text
Fun-CosyVoice3 雖然音色接近 reference audio，
但語氣、腔調、語速、停頓、句尾語調與輸入 reference 差距明顯。
```

目前問題核心不是 MuseTalk，也不是 WebRTC，而是 **Fun-CosyVoice3 推理模式選擇邏輯**。

本次只修改 TTS / CosyVoice3 相關邏輯，不要動 MuseTalk、AvatarTransition、WebRTC、ASR、LLM。

---

# 目前已確認的問題

主要檔案：

```text
src/tts/engines/cosyvoice.py
src/tts/cosyvoice_runtime.py
src/config/schema.py
config/config.yaml
```

目前：

```python
instruct = build_instruct(
    self.config.tts.language,
    self.config.tts.instruct,
    family=family,
)

if instruct:
    return "inference_instruct2", ...
```

而 `fun-cosyvoice3`：

```python
language: Chinese
```

會由 `build_instruct()` 自動轉成類似：

```text
You are a helpful assistant.
请用中文说这句话。
<|endofprompt|>
```

因此即使：

```yaml
instruct: ''
```

也會因為 language 不是 auto 而走：

```text
inference_instruct2
```

而不是：

```text
inference_zero_shot
```

這會導致：

```text
reference audio
主要提供 speaker / timbre conditioning

instruction
重新主導 prosody / speaking style
```

因此：

```text
音色像
但口氣、語速、腔調、句尾語氣不像 reference
```

---

# 修改目標

新增明確的 TTS mode：

```yaml
tts:
  mode: zero_shot
```

支援：

```text
zero_shot
cross_lingual
instruct
auto
```

不要再讓：

```text
language
```

隱含決定 inference mode。

---

# 1. 修改 TTS Config Schema

修改：

```text
src/config/schema.py
```

在：

```python
@dataclass
class TTSConfig:
```

新增：

```python
mode: str = "auto"
```

建議欄位：

```python
type: str = "edgetts"
mode: str = "auto"
ref_file: str = ...
ref_text: Optional[str] = None
language: str = "Chinese"
instruct: str = ""
```

---

# 2. 修改 config/config.yaml

在：

```yaml
tts:
```

新增：

```yaml
mode: auto
```

例如：

```yaml
tts:
  type: edgetts
  mode: auto
  ref_file: zh-TW-HsiaoChenNeural
  ref_text:
  language: Chinese
  instruct: ''
```

註解清楚：

```text
auto
zero_shot
cross_lingual
instruct
```

---

# 3. 修改 CosyVoice 推理模式選擇

修改：

```text
src/tts/engines/cosyvoice.py
```

目前：

```python
def _tts_request(self, text: str, prompt_text: str = ""):
```

重構成明確依據：

```python
mode = str(
    getattr(self.config.tts, "mode", "auto") or "auto"
).strip().lower()
```

---

# 4. zero_shot 模式

如果：

```python
mode == "zero_shot"
```

必須：

```text
使用 inference_zero_shot
```

前提：

```text
ref_text 非空
prompt_wav 存在
```

payload：

```python
return "inference_zero_shot", {
    "tts_text": text,
    "prompt_text": cleaned_prompt_text,
}
```

Fun-CosyVoice3 需要：

```text
<|endofprompt|>
```

時維持現在既有包裝邏輯。

例如：

```python
if family == "cosyvoice3" and "<|endofprompt|>" not in cleaned:
    cleaned = (
        "You are a helpful assistant."
        "<|endofprompt|>"
        + cleaned
    )
```

不要額外加入：

```text
请用中文说这句话
```

不要讓 language instruction 污染 zero-shot prosody。

---

# 5. zero_shot 缺少 ref_text 時

如果：

```python
mode == "zero_shot"
```

但：

```text
ref_text == ""
```

不要偷偷 fallback。

直接丟清楚錯誤：

```python
raise ValueError(
    "Fun-CosyVoice3 zero_shot mode requires tts.ref_text "
    "matching the reference audio transcript."
)
```

目的是避免使用者以為正在 zero-shot，實際卻跑到：

```text
cross_lingual
```

---

# 6. cross_lingual 模式

如果：

```python
mode == "cross_lingual"
```

固定：

```python
return "inference_cross_lingual", {
    "tts_text": text,
}
```

不要因：

```text
language
instruct
ref_text
```

自動改成其他 mode。

---

# 7. instruct 模式

如果：

```python
mode == "instruct"
```

才執行：

```python
build_instruct(...)
```

例如：

```python
instruct = build_instruct(
    getattr(self.config.tts, "language", "auto"),
    getattr(self.config.tts, "instruct", "") or "",
    family=family,
)
```

如果最後：

```text
instruct == ""
```

直接 raise：

```python
ValueError(
    "CosyVoice instruct mode requires language or tts.instruct."
)
```

然後：

```python
return "inference_instruct2", {
    "tts_text": text,
    "instruct_text": instruct,
}
```

---

# 8. auto 模式

為 backward compatibility 保留：

```python
mode == "auto"
```

但建議優先邏輯改為：

```text
有 ref_text
→ zero_shot

沒有 ref_text + 有 explicit instruct
→ instruct

沒有 ref_text + 沒 instruct
→ cross_lingual
```

注意：

在 `auto` 模式裡：

```text
language: Chinese
```

本身不要直接讓它變成 instruct。

也就是：

錯誤：

```text
language != auto
→ inference_instruct2
```

正確：

```text
explicit tts.instruct 非空
→ instruct
```

否則優先 reference-based cloning。

---

# 9. 建議 auto 邏輯

實作概念：

```python
def _tts_request(self, text, prompt_text=""):
    family = self._family()

    mode = str(
        getattr(self.config.tts, "mode", "auto") or "auto"
    ).strip().lower()

    valid_modes = {
        "auto",
        "zero_shot",
        "cross_lingual",
        "instruct",
    }

    if mode not in valid_modes:
        raise ValueError(
            f"Unsupported CosyVoice mode: {mode}"
        )

    cleaned_prompt = (prompt_text or "").strip()
    explicit_instruct = str(
        getattr(self.config.tts, "instruct", "") or ""
    ).strip()

    if mode == "zero_shot":
        if not cleaned_prompt:
            raise ValueError(...)
        return self._zero_shot_request(text, cleaned_prompt, family)

    if mode == "cross_lingual":
        return "inference_cross_lingual", {
            "tts_text": text,
        }

    if mode == "instruct":
        instruct = build_instruct(...)
        if not instruct:
            raise ValueError(...)
        return "inference_instruct2", {
            "tts_text": text,
            "instruct_text": instruct,
        }

    # auto
    if cleaned_prompt:
        return self._zero_shot_request(
            text,
            cleaned_prompt,
            family,
        )

    if explicit_instruct:
        instruct = build_instruct(...)
        return "inference_instruct2", ...

    return "inference_cross_lingual", {
        "tts_text": text,
    }
```

---

# 10. 建議抽 helper

新增：

```python
def _zero_shot_request(
    self,
    text: str,
    prompt_text: str,
    family: str,
):
```

避免 Fun-CosyVoice3 prompt formatting 重複。

例如：

```python
cleaned = prompt_text.strip()

if family == "cosyvoice3":
    if "<|endofprompt|>" not in cleaned:
        cleaned = (
            "You are a helpful assistant."
            "<|endofprompt|>"
            + cleaned
        )

return "inference_zero_shot", {
    "tts_text": text,
    "prompt_text": cleaned,
}
```

---

# 11. 不要修改 reference WAV preprocess

目前：

```text
prepare_prompt_wav()
```

會：

```text
轉 mono
轉 24kHz
trim leading silence
最多取約 8 秒
```

本次不要動。

除非測試發現 bug，否則保持：

```python
PROMPT_SAMPLE_RATE = 24000
PROMPT_MAX_SECONDS = 8.0
```

---

# 12. 加入 log

每次 TTS request 請記錄一次 mode / endpoint。

例如：

```python
logger.info(
    "CosyVoice request family=%s mode=%s endpoint=%s "
    "has_ref_text=%s has_instruct=%s",
    family,
    mode,
    endpoint,
    bool(prompt_text.strip()),
    bool(explicit_instruct),
)
```

不要記：

```text
完整 ref_text
完整 prompt
個人語音內容
```

只記 boolean。

---

# 13. Regression Tests

新增：

```text
tests/test_cosyvoice_tts.py
```

至少包含以下測試。

---

## Test 1：zero_shot

config：

```text
type = fun-cosyvoice3
mode = zero_shot
language = Chinese
instruct = ''
ref_text = '你好，今天很高興見到你。'
```

要求 endpoint：

```text
inference_zero_shot
```

不能：

```text
inference_instruct2
```

---

## Test 2：zero_shot 不受 language 影響

分別：

```text
language = Chinese
language = zh
language = auto
```

只要：

```text
mode=zero_shot
ref_text 有值
```

endpoint 都必須：

```text
inference_zero_shot
```

---

## Test 3：zero_shot 缺 ref_text

```text
mode=zero_shot
ref_text=''
```

必須：

```text
raise ValueError
```

---

## Test 4：instruct mode

```text
mode=instruct
language=Chinese
instruct='請用溫柔、自然、稍慢的語氣說話。'
```

要求：

```text
endpoint = inference_instruct2
```

---

## Test 5：cross_lingual mode

```text
mode=cross_lingual
```

不管：

```text
language
ref_text
```

都固定：

```text
inference_cross_lingual
```

---

## Test 6：auto + ref_text

```text
mode=auto
ref_text='...'
language=Chinese
instruct=''
```

必須：

```text
inference_zero_shot
```

---

## Test 7：auto + explicit instruct

```text
mode=auto
ref_text=''
instruct='請用活潑的語氣。'
```

必須：

```text
inference_instruct2
```

---

## Test 8：auto + language only

```text
mode=auto
ref_text=''
instruct=''
language=Chinese
```

必須：

```text
inference_cross_lingual
```

不能因 language 自動進：

```text
inference_instruct2
```

---

# 14. Config loader test

確認：

```yaml
tts:
  type: fun-cosyvoice3
  mode: zero_shot
```

可以正常 load：

```python
config.tts.mode == "zero_shot"
```

---

# 15. 建議實際配置

完成後請提供推薦設定：

```yaml
tts:
  type: fun-cosyvoice3
  mode: zero_shot

  ref_file: /absolute/path/reference.wav
  ref_text: "與 reference.wav 完整對應的逐字稿"

  language: auto
  instruct: ''

  model: Fun-CosyVoice3-0.5B-2512
  device: auto
```

如果模型路徑目前是其他方式管理，不要強制修改。

---

# 16. 實際 A/B 測試

修改完成後，請實際產生兩份音訊。

相同：

```text
reference.wav
ref_text
tts_text
```

A：

```text
mode=zero_shot
```

B：

```text
mode=instruct
language=Chinese
instruct=''
```

若現在程式規定 instruct='' 不允許 instruct mode，可以使用：

```text
instruct='請用中文自然說話。'
```

測試文字：

```text
您好，請問今天有什麼可以為您服務的嗎？
```

輸出：

```text
/tmp/cosy_zero_shot.wav
/tmp/cosy_instruct.wav
```

如果 server streaming response 無法直接保存，請用現有 TTS pipeline 或最小測試 script 完成。

---

# 17. 實際測試要求

執行：

```bash
uv run pytest -q tests/test_cosyvoice_tts.py
```

再執行相關 TTS tests：

```bash
uv run pytest -q tests -k "cosyvoice or tts"
```

然後：

```bash
uv run python -m compileall \
    src/tts/engines/cosyvoice.py \
    src/tts/cosyvoice_runtime.py \
    src/config/schema.py \
    src/config/loader.py
```

最後：

```bash
uv run pytest -q
```

---

# 18. 如果測試失敗

不要只回報。

流程：

```text
執行測試
↓
分析 failure
↓
修正
↓
重跑 targeted tests
↓
重跑 full pytest
↓
直到本次修改造成的問題全部通過
```

不要：

```text
skip
xfail
降低 assertion
刪測試
```

---

# 19. 驗收標準

必須確認：

```text
[ ] tts.mode 已加入 schema

[ ] 支援 auto / zero_shot / cross_lingual / instruct

[ ] zero_shot 不會被 language 強制切成 instruct2

[ ] zero_shot 必須有 ref_text

[ ] auto + ref_text 優先 zero_shot

[ ] auto + explicit instruct 才走 instruct2

[ ] language 本身不再隱含切換 inference mode

[ ] cross_lingual 可顯式指定

[ ] Fun-CosyVoice3 prompt format 正確

[ ] reference WAV preprocess 未被破壞

[ ] 有 endpoint logging

[ ] regression tests PASS

[ ] config loader PASS

[ ] compileall PASS

[ ] full pytest 已執行

[ ] A/B audio 已實際產生
```

---

# 20. 最終回報

完成後回覆：

## 修改檔案

列出實際修改檔案。

## Endpoint 行為

用表格回報：

| mode | ref_text | instruct | endpoint |
|---|---|---|---|
| zero_shot | 有 | 任意 | inference_zero_shot |
| cross_lingual | 任意 | 任意 | inference_cross_lingual |
| instruct | 任意 | 有 | inference_instruct2 |
| auto | 有 | 空 | inference_zero_shot |
| auto | 空 | 有 | inference_instruct2 |
| auto | 空 | 空 | inference_cross_lingual |

## 測試

實際貼：

```text
test_cosyvoice_tts:
xx passed

tts related tests:
xx passed

compileall:
PASS

full pytest:
xxx passed / x failed
```

## A/B 音訊

列出：

```text
zero-shot 輸出檔
instruct 輸出檔
使用的 reference
使用的 ref_text
使用的 tts_text
```

## 最終判定

只有上述完成後才可寫：

```text
Fun-CosyVoice3 推理模式已分離完成，
zero-shot 不再被 language 設定誤導到 instruct2，
可以進入 reference audio / prosody 實機比較。
```

如果沒有實際測試成功，不要宣告完成。
