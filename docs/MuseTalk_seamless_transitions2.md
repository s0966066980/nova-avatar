
# 目標

只修：

1. `opening_frames` 缺少 Config Schema 定義
2. `gap_grace_frames` 與 `settling_total` 的 frame count off-by-one
3. Phase Matching 的 speech descriptor 使用錯誤 ROI index

完成後必須：

```text
Config 可正常載入
+
Settling frame 數正確
+
Phase Matching descriptor ROI 正確
+
原有 transition 功能不退化
+
所有相關測試實際執行成功
```

---

# 重要限制

本次不要：

```text
重新設計 AvatarTransitionController
修改 MuseTalk inference cursor
修改 TTS
修改 WebRTC timing
修改 Audio queue
修改 batch size
修改 audio fps
加入新 AI model
加入 optical flow
加入 landmark model
修改 unrelated UI
修改 LLM
修改 ASR/VAD
```

不要為了讓測試通過而：

```text
刪除既有測試
skip 測試
xfail 測試
降低 assertion
硬編碼測試結果
```

只做必要修改。

---

# Issue 1：修正 opening_frames Config Schema

## 問題

目前：

`config/config_musetalk.yaml`

存在：

```yaml
opening_frames: 2
```

MuseTalk runtime 也會讀：

```python
opening = int(
    getattr(musetalk_cfg, "opening_frames", 2) or 2
)
```

但：

```text
src/config/schema.py
MuseTalkQualityConfig
```

沒有：

```python
opening_frames
```

而 loader 是：

```python
MuseTalkQualityConfig(
    **model_dict.get("musetalk", {})
)
```

因此載入包含：

```yaml
opening_frames: 2
```

的 YAML 時可能直接：

```text
TypeError:
unexpected keyword argument 'opening_frames'
```

---

# 修改要求

修改：

```text
src/config/schema.py
```

在：

```python
@dataclass
class MuseTalkQualityConfig:
```

加入：

```python
opening_frames: int = 2
```

建議與以下放在一起：

```python
gap_grace_frames: int = 1
opening_frames: int = 2
closing_frames: int = 4
```

---

# config/config.yaml

主 config 目前也建議明確加入：

```yaml
opening_frames: 2
```

放在：

```yaml
model:
  musetalk:
```

例如：

```yaml
mouth_continuity: true
mouth_continuity_idle_alignment: true

avatar_transition: true

gap_grace_frames: 1
opening_frames: 2

settling_enabled: true
settling_frames: 5
settling_min_frames: 4
settling_max_frames: 6
```

`config/config_musetalk.yaml` 已經有的話不要重複新增。

---

# 新增 Config Regression Test

請新增或擴充相關 config test。

至少實際測：

```python
config = load_config("config/config_musetalk.yaml")

assert config.model.musetalk.opening_frames == 2
assert config.model.musetalk.avatar_transition is True
assert config.model.musetalk.settling_min_frames == 4
assert config.model.musetalk.settling_max_frames == 6
assert config.model.musetalk.micro_crossfade_frames == 2
```

目的：

之後再加 YAML 欄位但忘記 schema 時，要能立即被 test 抓到。

---

# Issue 2：修正 settling frame count off-by-one

## 現況

Production：

```yaml
gap_grace_frames: 1

settling_min_frames: 4
settling_max_frames: 6
```

假設：

```text
planned settling = 5
```

AvatarTransitionController 會把：

```text
5 張 idle frame
```

視為完整 settling window。

但 MouthContinuityController 現在是：

```text
1 frame grace
+
5 frame mouth transition
```

實際總長：

```text
6 frames
```

因此 AvatarTransitionController 可能：

```text
嘴巴只完成 4/5
↓
就進 CROSSFADING
```

這是 off-by-one。

---

# 正確語意

當：

```python
transition_frames = 5
```

時，它的意義必須是：

> 從第一張 idle frame 到嘴巴 settling 完成，總共 5 張輸出 frame。

如果：

```python
gap_grace_frames = 1
```

則：

```text
1 grace
+
4 closing transition
=
5 total
```

而不是：

```text
1 + 5 = 6
```

---

# 修改要求

修改：

```text
src/avatars/musetalk/mouth_continuity.py
```

Speech → idle 時目前有：

```python
total_frames = (
    self._closing_frames
    if transition_frames is None
    else max(1, int(transition_frames))
)
```

請改為區分：

### 舊模式

如果：

```python
transition_frames is None
```

保持目前 legacy behavior。

不要破壞舊 caller。

例如：

```python
total_frames = self._closing_frames
```

---

### AvatarTransition override 模式

如果：

```python
transition_frames is not None
```

代表：

```text
整個 settling window 總長
```

因此真正 mouth interpolation frame 數應為：

```python
total_frames = max(
    1,
    int(transition_frames) - self._gap_grace_frames,
)
```

注意：

```text
transition_frames <= gap_grace_frames
```

時仍必須安全：

```python
max(1, ...)
```

不得出現：

```text
0 frame
negative frame
division by zero
```

---

# 重要：Controller 的 planned frame 不要改

不要修改：

```text
AvatarTransitionController._settling_total
```

它仍表示：

```text
從 speech end 後第一張 idle
到 settling 完成
```

總共有幾張 frame。

例如：

```text
planned = 5
```

必須保持：

```text
Idle 1 grace
Idle 2 closing
Idle 3 closing
Idle 4 closing
Idle 5 closing 完成
Idle 6 crossfade
```

---

# 新增 Production-like test

目前 `tests/test_avatar_transition.py` 使用：

```python
gap_grace_frames=0
```

這無法抓到 production bug。

請新增至少一個：

```python
gap_grace_frames=1
settling_frames=5
settling_min_frames=5
settling_max_frames=5
```

的 regression test。

測試流程：

```text
speech
↓
idle 1
idle 2
idle 3
idle 4
idle 5
```

要求：

在第 5 張 idle frame：

```text
mouth settling 已完整完成
```

並且：

```text
Controller 正好離開 SETTLING
```

不能：

```text
Controller 進 CROSSFADING
但嘴型仍未完全收完
```

---

# 建議 assert

例如建立：

```text
speech mouth ROI = 200
idle mouth ROI = 0
```

輸出序列必須：

```text
Frame 1:
仍接近 speech mouth / grace

Frame 2~4:
逐步下降

Frame 5:
完全等於 idle mouth
```

最後：

```python
assert mouth_value == idle_value
```

並：

```python
assert controller.state in {
    TransitionState.CROSSFADING,
    TransitionState.IDLE,
}
```

視 crossfade config 而定。

如果：

```python
micro_crossfade_frames=0
```

則應：

```python
controller.state == TransitionState.IDLE
```

這會更容易精確驗證 settling boundary。

---

# Issue 3：修正 Phase Matching reference ROI index

## 問題

目前：

```python
_plan_idle_return(
    speech_frame,
    first_idle_index,
)
```

內：

```python
descriptor = self._descriptor(
    speech_frame,
    first_idle_index,
)
```

但：

```text
speech_frame
```

其實是：

```text
_last_speech_frame
```

它應該使用：

```text
_last_speech_index
```

對應的 face bbox / pose ROI。

現在卻拿：

```text
第一張 idle frame 的 bbox
```

裁最後 speech image。

例如：

```text
Speech image = idx 150
first idle = idx 151
```

現在等於：

```text
用 bbox 151
裁 frame 150
```

在頭部移動明顯時 descriptor 可能偏掉。

---

# 正確實作

修改：

```python
_plan_idle_return()
```

API。

建議：

```python
def _plan_idle_return(
    self,
    speech_frame,
    speech_index,
    first_idle_index,
):
```

reference descriptor：

```python
descriptor = self._descriptor(
    speech_frame,
    speech_index,
)
```

candidate：

```python
candidate = self._future_index(...)
```

仍然：

```python
self._source_pose_descriptors[candidate]
```

不要改。

---

# compose 呼叫

Speech End 時原本：

```python
planned, candidate, score = self._plan_idle_return(
    self._last_speech_frame,
    index,
)
```

改成：

```python
planned, candidate, score = self._plan_idle_return(
    self._last_speech_frame,
    self._last_speech_index,
    index,
)
```

如果：

```python
_last_speech_index is None
```

要安全 fallback。

例如使用：

```python
speech_index = (
    self._last_speech_index
    if self._last_speech_index is not None
    else first_idle_index
)
```

---

# Phase Matching 測試

新增 regression test。

刻意製造：

```text
speech bbox/index A
first idle bbox/index B
```

且兩個 ROI 明顯不同。

驗證：

```text
reference speech descriptor
```

使用：

```text
speech_index
```

而不是：

```text
first_idle_index
```

不要只測 `_plan_idle_return()` 最後 candidate。

最好直接 monkeypatch / spy `_descriptor()`。

例如記錄：

```python
calls = []
```

驗證第一次 speech descriptor 呼叫：

```python
assert index == speech_index
```

---

# 既有功能不得退化

修改完成後確認：

## Phase Matching 仍然不能 jump idx

不得新增：

```python
self.idx = ...
index += best_offset
current_index = candidate
```

只允許：

```text
預測 future frame
↓
決定 settling duration
```

真正 frame cursor 必須仍由原 MuseTalk inference：

```python
index += 1
```

管理。

---

# Ping-pong 必須保持

仍必須符合：

```text
0
1
2
3
3
2
1
0
0
1
```

不能因本次修改改壞。

---

# Speech interruption 必須保持

以下：

```text
SPEAKING
↓
SETTLING
↓
新 speech
```

必須立即：

```text
SPEAKING
```

Crossfade 也是。

---

# Custom video bypass 必須保持

```python
frame_type > 1
```

不得 phase match MuseTalk idle frames。

---

# Direct audio 行為不能改壞

目前：

```text
確認 video frame 可前進
↓
才 compose avatar transition
```

不要改回：

```text
transition state 先 advance
↓
frame 最後被 continue/drop
```

---

# Ghosting Guard 必須保持

目前：

```text
MAD <= threshold
→ full-frame blend

MAD > threshold
→ mask-only blend
```

不要移除。

---

# Test Execution Requirement

這不是只修改程式。

你必須實際執行測試。

---

# 第一階段：精準測試

先跑：

```bash
uv run pytest -q tests/test_mouth_continuity.py
```

然後：

```bash
uv run pytest -q tests/test_avatar_transition.py
```

以及新增/修改的 config test。

---

# 第二階段：直接測 Config Loader

至少實際執行等效測試：

```bash
uv run python - <<'PY'
from src.config.loader import load_config

config = load_config("config/config_musetalk.yaml")

m = config.model.musetalk

print("opening_frames:", m.opening_frames)
print("avatar_transition:", m.avatar_transition)
print("settling_frames:", m.settling_frames)
print("settling_min_frames:", m.settling_min_frames)
print("settling_max_frames:", m.settling_max_frames)
print("phase_matching_enabled:", m.phase_matching_enabled)
print("micro_crossfade_frames:", m.micro_crossfade_frames)

assert m.opening_frames == 2
assert m.avatar_transition is True
assert m.settling_min_frames == 4
assert m.settling_max_frames == 6
assert m.micro_crossfade_frames == 2
PY
```

必須成功 exit code 0。

---

# 第三階段：Compile Check

執行：

```bash
uv run python -m compileall \
    src/config/schema.py \
    src/config/loader.py \
    src/avatars/base.py \
    src/avatars/musetalk/avatar.py \
    src/avatars/musetalk/avatar_transition.py \
    src/avatars/musetalk/mouth_continuity.py
```

必須：

```text
exit code 0
```

---

# 第四階段：完整 pytest

執行：

```bash
uv run pytest -q
```

---

# 如果測試失敗

不要立即結束。

你必須：

```text
執行測試
↓
找到 failure
↓
判斷是否由本次修改造成
↓
如果由本次修改造成：
    修 code
    再跑精準測試
    再跑完整測試
↓
直到通過
```

不能：

```text
測試失敗
↓
只回報失敗
↓
停止
```

本任務要求你實際修改到完成。

---

# 如果是既有 unrelated failure

若完整：

```bash
uv run pytest -q
```

存在與本次修改完全無關、且在修改前就已存在的 failure：

請：

1. 確認不是本次 regression
2. 不要修改 unrelated subsystem
3. 記錄 failure 名稱與原因
4. 相關 AvatarTransition / Config tests 仍必須全部 PASS

只有能合理證明：

```text
pre-existing unrelated failure
```

才允許最終保留。

---

# 額外靜態驗證

請搜尋確認沒有以下錯誤：

```text
opening_frames 出現在 YAML
但不存在 schema
```

以及沒有：

```text
_plan_idle_return(
    speech_frame,
    first_idle_index
)
```

這種舊 API 殘留。

並確認：

```text
transition_frames
```

的語意已變成：

```text
總 settling window
```

而非：

```text
純 closing interpolation frame count
```

---

# 測試還需要新增這 3 個 regression case

最終至少增加：

## Regression A

```text
config_musetalk.yaml
```

可以正常 load：

```text
opening_frames == 2
```

---

## Regression B

```text
gap_grace_frames = 1
planned = 5
```

必須：

```text
第 5 張 idle
嘴型已完全 settle
```

---

## Regression C

Phase matching：

```text
speech frame descriptor
```

必須用：

```text
speech_index
```

裁 ROI。

---

# 完整驗收清單

最終請逐項確認：

```text
[ ] opening_frames 已加入 MuseTalkQualityConfig

[ ] config/config.yaml 有 opening_frames: 2

[ ] config/config_musetalk.yaml 可以正常 load

[ ] 沒有 unexpected keyword argument opening_frames

[ ] transition_frames 的語意為「完整 settling window」

[ ] gap_grace_frames=1 不再多出額外一張 settling frame

[ ] planned=5 時，第 5 張 idle mouth 已完全完成

[ ] Crossfade 不會早於 mouth settling 完成

[ ] Phase Matching speech descriptor 使用 last_speech_index

[ ] Candidate descriptor 使用 candidate index

[ ] Phase Matching 仍不修改 inference idx

[ ] Ping-pong 預測仍正確

[ ] Speech 可以中斷 Settling

[ ] Speech 可以中斷 Crossfade

[ ] generation reset 正常

[ ] custom video bypass 正常

[ ] Ghosting guard 正常

[ ] Direct Audio 不會讓 transition 偷跑

[ ] source frame 不被修改

[ ] tests/test_mouth_continuity.py PASS

[ ] tests/test_avatar_transition.py PASS

[ ] Config regression tests PASS

[ ] compileall PASS

[ ] 完整 pytest 已實際執行
```

---

# 完成判定

只有以下條件都滿足才能宣告完成：

```text
三個問題都已修正
+
相關 regression tests 已新增
+
相關 pytest 全部 PASS
+
config_musetalk.yaml 實際 load PASS
+
compileall PASS
+
完整 pytest 已執行
+
沒有本次修改造成的 regression
```

否則：

```text
不要宣告完成
```

請繼續修改與測試。

---

# 最終回報格式

完成後請用以下格式回覆。

## 1. 修改結果

```text
Issue 1 opening_frames schema:
PASS / FAIL

Issue 2 settling off-by-one:
PASS / FAIL

Issue 3 speech ROI index:
PASS / FAIL
```

---

## 2. 修改檔案

列出實際修改檔案與原因，例如：

```text
src/config/schema.py
- 加 opening_frames

config/config.yaml
- 補 opening_frames

src/avatars/musetalk/mouth_continuity.py
- 修 settling window 計數

src/avatars/musetalk/avatar_transition.py
- speech descriptor 使用 last_speech_index

tests/...
- regression tests
```

---

## 3. 實際測試結果

請貼實際執行結果摘要：

```text
test_mouth_continuity:
xx passed

test_avatar_transition:
xx passed

config tests:
xx passed

compileall:
PASS

full pytest:
xxx passed / x failed
```

如果有 failure：

```text
列出 test 名稱
是否與本次修改相關
判斷依據
```

---

## 4. 最終流程確認

確認最終流程為：

```text
Speech last frame
       ↓
Speech End
       ↓
Phase Matching planning
       ↓
1 frame grace（若設定 1）
       ↓
剩餘 settling interpolation
       ↓
在 planned frame 數內完全閉嘴
       ↓
Micro Crossfade
       ↓
Idle
```

例如：

```text
planned = 5
gap = 1

Idle #1 grace
Idle #2 settle
Idle #3 settle
Idle #4 settle
Idle #5 settle complete
Idle #6 crossfade
```

---

## 5. 完整度重新評估

請依實際測試結果評分：

```text
Architecture:
x / 100

Config integration:
x / 100

Transition correctness:
x / 100

Regression coverage:
x / 100

Runtime safety:
x / 100

Overall:
x / 100
```

只有所有相關 test 都成功、三個 regression 都已驗證時：

```text
Overall >= 98/100
```

才可寫：

```text
「本次 speech → idle transition 修改已完成，可進入實機視覺參數微調。」
```

如果未達成：

請明確寫：

```text
「尚未完成」
```

並繼續修正，不要只提出下一步建議。
