# 1. 最終目標

目前 MuseTalk 的視覺流程大致是：

```text
Audio
 ↓
MuseTalk inference
 ↓
speech frame
 ↓
Speech End
 ↓
直接進 idle frame
```

雖然目前已經有：

```text
MouthContinuityController
```

處理 speech / idle 的嘴部 ROI 過渡，但仍要升級成完整：

```text
Speaking
   ↓
Speech End
   ↓
Mouth / Face Settling
   ↓
Idle Phase Matching
   ↓
Micro Crossfade
   ↓
Idle
```

目標是：

```text
說話最後一幀
     ↓
嘴巴逐漸收合
     ↓
沿現有 idle 時間軸尋找適合的自然接點
     ↓
2~3 frame 微量淡接
     ↓
正常 idle cycle
```

必須保持：

- Audio master clock 不變
- TTS latency 不變
- MuseTalk inference latency 不變
- WebRTC audio pipeline 不變
- 不新增 diffusion inference
- 不新增 optical flow model
- 不新增 landmark / pose AI model
- 不 rewind audio
- 不任意改掉 MuseTalk inference 的 idx
- 不因轉場阻塞 audio queue
- speech 隨時重新出現時必須立即中斷 idle transition

---

# 2. 目前架構的重要限制

請先閱讀：

```text
src/avatars/base.py
src/avatars/musetalk/avatar.py
src/avatars/musetalk/mouth_continuity.py
src/avatars/musetalk/audio_stream_handler.py
src/avatars/musetalk/myutil.py
src/avatars/musetalk/genavatar_musetalk.py
tests/test_mouth_continuity.py
config/config.yaml
config/config_musetalk.yaml
```

目前 `process_frames()` 最核心的邏輯是：

```python
if audio_frames[0][1] != 0 and audio_frames[1][1] != 0:
    # idle
    target_frame = self.frame_list_cycle[idx]
else:
    # speech
    current_frame = self.paste_back_frame(res_frame, idx)
```

接著再：

```python
combine_frame = self._compose_mouth_continuity(...)
```

這個 binary switch 是這次主要改善點。

不要直接去破壞：

```python
inference()
MuseAudioStreamHandler
audio queue
feat_queue
res_frame_queue
direct audio
```

---

# 3. 非常重要：不要真的任意跳 ±10 個 idx

MuseTalk speech frame 是：

```text
input_latent_list_cycle[idx]
         ↓
MuseTalk
         ↓
paste_back_frame(...)
         ↓
frame_list_cycle[idx]
```

idle 也是：

```text
frame_list_cycle[idx]
```

所以目前：

```text
speech idx
idle idx
latent idx
source frame idx
```

本來就是同一條時間軸。

錯誤實作：

```python
best_idx = current_idx + 8
idx = best_idx
```

不要這樣做。

否則：

```text
MuseTalk latent phase
          ≠
idle source phase
```

後續再次 speech 時容易產生另一個跳動。

## 正確做法

Live streaming 模式的 Phase Matching：

```text
不 rewind
不直接 jump index
不修改 inference cursor
```

而是：

```text
沿現有 frame sequence 往前看
          ↓
找接下來 4~6 frames 中姿態最佳的 frame
          ↓
把「settling 完成時間」安排在那個 frame
```

也就是：

```text
frame k       speech end
frame k+1     settling
frame k+2     settling
frame k+3     settling
frame k+4     candidate
frame k+5     candidate
frame k+6     candidate

挑最佳者，例如 k+5
```

但實際 playback 仍然：

```text
k
k+1
k+2
k+3
k+4
k+5
```

完全沒有跳 frame。

---

# 4. 新增檔案

新增：

```text
src/avatars/musetalk/avatar_transition.py
```

主要 class：

```python
AvatarTransitionController
```

建議另外建立：

```python
class TransitionState(str, Enum):
    IDLE = "idle"
    SPEAKING = "speaking"
    SETTLING = "settling"
    PHASE_MATCHING = "phase_matching"
    CROSSFADING = "crossfading"
```

其中 `PHASE_MATCHING` 可以是邏輯狀態，不一定需要獨立輸出一個 frame。

---

# 5. AvatarTransitionController 建構參數

建議：

```python
class AvatarTransitionController:
    def __init__(
        self,
        source_frames,
        masks,
        mask_coords,
        face_coords,
        *,
        mouth_controller=None,
        enabled=True,
        fps=25,

        settling_min_frames=4,
        settling_max_frames=6,

        phase_matching_enabled=True,
        phase_temporal_penalty=0.015,

        micro_crossfade_enabled=True,
        micro_crossfade_frames=2,
        micro_crossfade_fullframe_max_diff=18.0,

        opening_frames=2,
    ):
        ...
```

不要載入任何額外 AI model。

只能使用現有：

```text
numpy
opencv
source frames
mask
bbox
```

---

# 6. Controller 需要保存的 runtime state

至少保存：

```python
self.state

self._previous_is_speech
self._previous_output

self._last_speech_frame
self._last_speech_index

self._last_source_index
self._playback_direction

self._settling_step
self._settling_total

self._planned_idle_index
self._planned_idle_offset
self._planned_match_score

self._crossfade_origin
self._crossfade_step

self._generation
```

並提供：

```python
reset()
compose(...)
```

---

# 7. compose() API

建議：

```python
def compose(
    self,
    target_frame: np.ndarray,
    *,
    index: int,
    is_speech: bool,
    frame_type: int,
    eventpoint: dict | None,
) -> np.ndarray:
```

`target_frame`：

speech：

```text
paste_back_frame() 後的 MuseTalk frame
```

idle：

```text
frame_list_cycle[idx]
```

custom video：

```text
custom_img_cycle frame
```

---

# 8. Custom Video 必須 bypass

目前：

```python
frame_type == 0
```

代表 speech。

```python
frame_type == 1
```

代表一般 idle。

```python
frame_type > 1
```

可能是 custom audio/video state。

如果：

```python
frame_type > 1
```

不要做：

```text
Idle Phase Matching
Mouth Settling
Micro Crossfade
```

因為：

```text
custom video
```

不是：

```text
frame_list_cycle
```

直接：

```python
self.reset_visual_transition()
return target_frame
```

或安全地 bypass transition。

不能拿 MuseTalk idle frame 與 custom video 做 phase matching。

---

# 9. Speech 狀態

如果：

```python
is_speech is True
```

執行：

```text
任何 settling
任何 phase matching
任何 crossfade
      ↓
立即取消
```

然後：

```python
state = SPEAKING
```

更新：

```python
_last_speech_frame = output.copy()
_last_speech_index = index
_previous_output = output.copy()
```

speech 優先權永遠最高。

也就是：

```text
SETTLING
     ↓
突然下一句 TTS 開始
     ↓
立即 SPEAKING
```

不能：

```text
等 settling 做完才開嘴
```

---

# 10. Generation change

eventpoint 目前會包含：

```text
turn_id
generation
```

如果：

```python
generation != self._generation
```

要清除舊 transition：

```python
reset()
```

但當前 speech frame 還是要正常輸出。

避免：

```text
上一輪回答的 last_speech_frame
```

污染：

```text
下一輪回答
```

---

# 11. Speech End 偵測

不要依賴 wall clock。

直接依目前 frame：

上一張：

```python
_previous_is_speech == True
```

目前：

```python
is_speech == False
```

就是：

```text
Speech End
```

此時：

```python
state = SETTLING
_settling_step = 0
```

並立即執行：

```python
_plan_idle_return(...)
```

---

# 12. Playback direction 追蹤

現在 MuseTalk 是 ping-pong：

```python
__mirror_index()
```

播放大致：

```text
0
1
2
3
...
N-1
N-1
N-2
...
1
0
0
1
...
```

注意 endpoint 會重複。

Controller 必須透過實際輸入 `index` 推估目前方向。

規則：

```python
if current_index > previous_index:
    direction = +1

elif current_index < previous_index:
    direction = -1

elif current_index == previous_index:
    if current_index == 0:
        direction = +1
    elif current_index == size - 1:
        direction = -1
```

建立：

```python
def _next_pingpong_index(index, direction):
```

正確模擬現有 MuseTalk sequence。

例如 `size=5`：

```text
0 1 2 3 4 4 3 2 1 0 0 1 2 ...
```

---

# 13. Idle Phase Matching 的正確實作

## 不要跳 frame。

Speech End 時：

假設：

```text
current idx = 150
```

且：

```text
settling_min_frames = 4
settling_max_frames = 6
```

預測未來：

```text
+4
+5
+6
```

對應 idle candidate。

例如：

```text
154
155
156
```

計算：

```text
最後 speech frame
vs
idle 154

最後 speech frame
vs
idle 155

最後 speech frame
vs
idle 156
```

找到：

```text
155 score 最低
```

則：

```python
_settling_total = 5
_planned_idle_index = 155
```

正常播放仍然：

```text
151
152
153
154
155
```

沒有 skip。

---

# 14. Phase Matching Descriptor

不能直接比較整張 frame。

因為背景可能幾乎完全不動，會讓 score 被背景主導。

使用：

```text
face + neck + shoulder ROI
```

可以從目前：

```python
coord_list_cycle[index]
```

取得 face bbox：

```python
x1, y1, x2, y2
```

建立擴張 ROI：

建議：

```text
左右：
bbox width * 0.6

上方：
bbox height * 0.25

下方：
bbox height * 1.2
```

clip 到 image boundary。

也就是大約涵蓋：

```text
頭
脖子
部分肩膀
```

---

# 15. Descriptor 必須淡化嘴部影響

最後 speech frame 的嘴是 MuseTalk 生成結果。

candidate idle 是原始閉嘴。

如果直接算嘴：

```text
open mouth
vs
closed mouth
```

會讓 phase matching 被嘴型主導。

Phase matching 真正應該找的是：

```text
head pose
neck
shoulder
face position
```

所以使用現有：

```text
mask_list_cycle
mask_coords_list_cycle
```

將 lower-face / mouth blend region 排除或降低 weight。

例如：

```text
pose ROI weight = 1.0
mouth mask weight = 0.1
```

甚至：

```text
mouth mask weight = 0
```

---

# 16. Descriptor 計算

不要用 SSIM dependency。

只使用 OpenCV/Numpy。

建議：

```python
crop
 ↓
resize(64, 64)
 ↓
grayscale
 ↓
float32
 ↓
brightness normalization
```

例如：

```python
gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
gray = cv2.resize(gray, (64, 64))
gray = gray.astype(np.float32)

mean = gray.mean()
std = gray.std() + 1e-6

gray = (gray - mean) / std
```

然後：

```python
score = np.mean(np.abs(a - b))
```

加上 temporal penalty：

```python
score += offset * phase_temporal_penalty
```

避免：

```text
+6 幀只比 +4 幀好一點點
```

卻選更遠的位置。

---

# 17. Source descriptor 預計算

在：

```python
AvatarTransitionController.__init__()
```

可對：

```python
source_frames
```

預計算 descriptors：

```python
self._source_pose_descriptors
```

這樣 runtime：

```text
Speech End
```

只需：

```text
算一次 speech descriptor
+
比較 3~5 個 numpy arrays
```

CPU 成本很低。

不要每次做：

```text
MediaPipe
DWPose
YOLO Pose
face detector
```

---

# 18. Mouth Settling

保留目前：

```text
MouthContinuityController
```

不要刪掉。

但目前需要讓每次 Speech End 可以使用：

```text
Phase Matching 決定的 settling frames
```

例如：

```text
4
5
6
```

而不是永遠固定。

修改：

```text
src/avatars/musetalk/mouth_continuity.py
```

讓：

```python
compose()
```

多一個 optional keyword：

```python
transition_frames: int | None = None
```

例如：

```python
def compose(
    self,
    target_frame,
    *,
    index,
    is_speech,
    eventpoint,
    transition_frames=None,
):
```

只有：

```python
_previous_is_speech == True
and
is_speech == False
```

第一個 idle frame 時才讀取。

原本：

```python
self._start_transition(
    ...,
    self._closing_frames,
)
```

改成：

```python
total_frames = (
    transition_frames
    if transition_frames is not None
    else self._closing_frames
)
```

再：

```python
self._start_transition(
    ...,
    total_frames,
)
```

必須保證：

```text
舊 caller 不傳 transition_frames
```

時行為完全相容。

---

# 19. Settling 建議值

目前設定：

```text
settling_frames: 12
```

25 FPS：

```text
12 × 40 ms
=
480 ms
```

再加：

```text
gap_grace_frames: 2
```

會更加拖長。

這次預設改成：

```yaml
gap_grace_frames: 1
settling_frames: 5

settling_min_frames: 4
settling_max_frames: 6
```

也就是：

```text
Mouth Settling：

160~240ms
```

比較符合正常說話收嘴。

---

# 20. Settling easing

使用：

```text
smoothstep
```

不要 linear。

公式：

```python
alpha = t * t * (3.0 - 2.0 * t)
```

其中：

```python
t = step / total
```

效果：

```text
快開始
中間自然
慢收尾
```

比：

```text
0.2
0.4
0.6
0.8
1.0
```

更自然。

---

# 21. Micro Crossfade

Mouth Settling 完成後：

```text
state = CROSSFADING
```

預設：

```yaml
micro_crossfade_frames: 2
```

最多建議：

```text
3
```

25 FPS：

```text
2 frames = 80ms
3 frames = 120ms
```

不要 5~10 frames。

---

# 22. Crossfade 使用 moving target

Crossfade origin 固定：

```python
_crossfade_origin
```

但 target 使用目前新的 idle frame。

例如：

```text
origin = 最後 settling output

Frame 1:
origin 50%
current idle 50%

Frame 2:
current idle 100%
```

若 3 frames：

```text
Frame 1:
~26% target

Frame 2:
~74% target

Frame 3:
100% target
```

使用 smoothstep。

---

# 23. 防止 Ghosting

不要無條件全畫面：

```python
cv2.addWeighted()
```

先算：

```python
frame_difference
```

可使用：

```python
small_a = cv2.resize(origin, (96, 96))
small_b = cv2.resize(target, (96, 96))

mad = np.mean(
    np.abs(
        small_a.astype(np.float32)
        -
        small_b.astype(np.float32)
    )
)
```

如果：

```python
mad <= micro_crossfade_fullframe_max_diff
```

才做：

```text
whole-frame crossfade
```

否則：

```text
不要做 whole-frame crossfade
```

fallback：

```text
只 blend face/jaw transition mask
```

避免：

```text
雙臉
雙肩
ghosting
```

---

# 24. Face/Jaw fallback mask

可直接重用：

```text
mask_list_cycle
mask_coords_list_cycle
```

投影到 full frame。

不要新增 segmentation model。

建立 helper：

```python
_build_full_mask(index)
```

並 feather。

如果 mask 是：

```text
crop mask
```

使用：

```text
mask_coords_list_cycle[index]
```

resize 並投影回 full image。

---

# 25. BaseAvatar 修改

修改：

```text
src/avatars/base.py
```

在：

```python
BaseAvatar.__init__()
```

加入：

```python
self._avatar_transition = None
```

保留：

```python
self._mouth_continuity = None
```

---

# 26. 新增 generic compose hook

加入：

```python
def _compose_avatar_transition(
    self,
    frame,
    *,
    index,
    is_speech,
    frame_type,
    eventpoint,
):
```

流程：

```python
controller = getattr(self, "_avatar_transition", None)

if controller is not None:
    try:
        return controller.compose(...)
    except Exception as exc:
        logger.warning(...)
        self._avatar_transition = None
```

fallback：

```python
return self._compose_mouth_continuity(...)
```

這樣：

```text
Wav2Lip
ERNeRF
TalkingGaussian
```

不受影響。

---

# 27. process_frames 修改

目前最後：

```python
combine_frame = self._compose_mouth_continuity(
    combine_frame,
    index=idx,
    is_speech=self.speaking,
    eventpoint=video_eventpoint,
)
```

改成：

```python
combine_frame = self._compose_avatar_transition(
    combine_frame,
    index=idx,
    is_speech=self.speaking,
    frame_type=visual_frame_type,
    eventpoint=video_eventpoint,
)
```

其中：

speech：

```python
visual_frame_type = 0
```

idle：

```python
visual_frame_type = audiotype
```

---

# 28. Direct Audio 模式的重要修改

目前 `process_frames()` 裡：

```text
combine visual frame
 ↓
mouth continuity state advance
 ↓
VideoFrame
 ↓
檢查 audio queue 是否空
 ↓
可能 continue
```

這表示：

```text
transition controller 已經走了一 frame
```

但：

```text
使用者根本沒有看到那 frame
```

要修正。

把：

```python
if self.direct_audio_enabled:
    audio_queue = getattr(audio_track, "_queue", None)
    if audio_queue is not None and audio_queue.qsize() == 0:
        continue
```

移到：

```text
visual transition compose
```

之前。

也就是：

```text
取得 raw visual frame
 ↓
確認這 frame 可以 enqueue
 ↓
AvatarTransitionController.compose()
 ↓
VideoFrame
 ↓
enqueue
```

避免：

```text
settling step=1
settling step=2
settling step=3
```

實際上一張都沒顯示。

---

# 29. flush_talk()

修改：

```python
BaseAvatar.flush_talk()
```

除了：

```python
mouth_continuity.reset()
```

也：

```python
avatar_transition.reset()
```

例如：

```python
transition = getattr(self, "_avatar_transition", None)

if transition is not None:
    transition.reset()
```

---

# 30. MuseTalkAvatar 初始化

修改：

```text
src/avatars/musetalk/avatar.py
```

目前建立：

```python
self._mouth_continuity = MouthContinuityController(...)
```

保留。

再建立：

```python
from .avatar_transition import AvatarTransitionController
```

然後：

```python
self._avatar_transition = AvatarTransitionController(
    self.frame_list_cycle,
    self.mask_list_cycle,
    self.mask_coords_list_cycle,
    self.coord_list_cycle,
    mouth_controller=self._mouth_continuity,
    fps=config.video.fps,
    ...
)
```

---

# 31. 不要 double-compose MouthContinuity

當：

```python
self._avatar_transition
```

存在時：

```text
MouthContinuityController
```

必須由：

```text
AvatarTransitionController
```

內部負責。

不能：

```text
AvatarTransitionController
 ↓
MouthContinuity

然後 BaseAvatar
 ↓
再 MouthContinuity 一次
```

所以 `_compose_avatar_transition()`：

```text
controller available
    → only AvatarTransitionController

controller unavailable
    → old MouthContinuityController fallback
```

---

# 32. 建議 Controller 完整流程

核心 pseudo code：

```python
def compose(
    self,
    target_frame,
    *,
    index,
    is_speech,
    frame_type,
    eventpoint,
):
    with self._lock:

        self._handle_generation(eventpoint)

        self._update_playback_direction(index)

        # custom video
        if not is_speech and frame_type > 1:
            self._reset_transition_only()
            return target_frame.copy()

        # SPEAKING
        if is_speech:
            output = self._mouth_controller.compose(
                target_frame,
                index=index,
                is_speech=True,
                eventpoint=eventpoint,
            )

            self.state = TransitionState.SPEAKING

            self._last_speech_frame = output.copy()
            self._last_speech_index = index
            self._previous_output = output.copy()
            self._previous_is_speech = True

            return output

        # SPEECH -> IDLE
        if self._previous_is_speech:
            planned_frames, target_index, score = (
                self._plan_idle_return(
                    self._last_speech_frame,
                    index,
                )
            )

            self._settling_total = planned_frames
            self._planned_idle_index = target_index
            self._planned_match_score = score
            self._settling_step = 0

            self.state = TransitionState.SETTLING

            output = self._mouth_controller.compose(
                target_frame,
                index=index,
                is_speech=False,
                eventpoint=eventpoint,
                transition_frames=planned_frames,
            )

        elif self.state == TransitionState.SETTLING:

            output = self._mouth_controller.compose(
                target_frame,
                index=index,
                is_speech=False,
                eventpoint=eventpoint,
            )

        elif self.state == TransitionState.CROSSFADING:

            mouth_output = self._mouth_controller.compose(
                target_frame,
                index=index,
                is_speech=False,
                eventpoint=eventpoint,
            )

            output = self._apply_micro_crossfade(
                mouth_output,
                index=index,
            )

        else:

            output = self._mouth_controller.compose(
                target_frame,
                index=index,
                is_speech=False,
                eventpoint=eventpoint,
            )

        ...
```

然後更新：

```python
_previous_is_speech = is_speech
_previous_output = output.copy()
```

---

# 33. Settling state 結束

每顯示一個 settling frame：

```python
_settling_step += 1
```

如果：

```python
_settling_step >= _settling_total
```

則：

如果：

```python
micro_crossfade_enabled
and
micro_crossfade_frames > 0
```

進：

```python
state = CROSSFADING
_crossfade_origin = output.copy()
_crossfade_step = 0
```

否則：

```python
state = IDLE
```

---

# 34. Crossfade state 結束

每輸出一 frame：

```python
_crossfade_step += 1
```

當：

```python
_crossfade_step >= micro_crossfade_frames
```

設定：

```python
state = IDLE
_crossfade_origin = None
```

最終 frame 必須：

```text
100% current idle
```

不能留：

```text
1%
5%
```

舊 speech frame。

---

# 35. Opening transition

目前 `MouthContinuityController` 已經有：

```text
opening_frames
```

保留。

當：

```text
Idle
SETTLING
CROSSFADING
```

突然變：

```text
SPEAKING
```

必須：

```text
立即取消 idle return
```

並交給：

```text
MouthContinuityController opening
```

進入 speech。

---

# 36. Configuration

修改：

```text
config/config.yaml
```

以及 MuseTalk 專用 config。

建議：

```yaml
model:
  musetalk:
    mouth_continuity: true
    mouth_continuity_idle_alignment: true

    avatar_transition: true

    gap_grace_frames: 1
    opening_frames: 2

    settling_enabled: true
    settling_frames: 5
    settling_min_frames: 4
    settling_max_frames: 6

    phase_matching_enabled: true
    phase_temporal_penalty: 0.015

    micro_crossfade_enabled: true
    micro_crossfade_frames: 2
    micro_crossfade_fullframe_max_diff: 18.0
```

---

# 37. backward compatibility

程式必須支援舊 config：

如果沒有：

```yaml
settling_min_frames
settling_max_frames
```

則：

```python
fixed = settling_frames
min_frames = fixed
max_frames = fixed
```

如果沒有：

```yaml
avatar_transition
```

預設：

```python
True
```

但必須可以：

```yaml
avatar_transition: false
```

立即回到目前舊行為。

---

# 38. 不要刪除舊 enable_transition code 前先確認

`BaseAvatar.process_frames()` 目前還有：

```python
enable_transition = False
```

以及舊的：

```python
cv2.addWeighted()
```

transition prototype。

新 controller 完成後：

```text
刪掉或清理這段 dead transition code
```

避免專案同時存在：

```text
legacy transition
new transition
mouth continuity
```

三套邏輯。

最終只保留：

```text
AvatarTransitionController
        ↓
MouthContinuityController
```

以及 fallback。

---

# 39. Logger

只在狀態切換時記錄。

不要每 frame `INFO`。

例如：

```text
[AvatarTransition] SPEAKING -> SETTLING idx=152 planned=5 target=157 score=0.083
[AvatarTransition] SETTLING -> CROSSFADING
[AvatarTransition] CROSSFADING -> IDLE
[AvatarTransition] transition cancelled by new speech
```

frame 細節只用：

```python
logger.debug()
```

---

# 40. Thread safety

`process_frames()` 與：

```text
flush_talk()
```

可能不同 thread 呼叫。

AvatarTransitionController 建議：

```python
from threading import RLock
```

並：

```python
self._lock = RLock()
```

包：

```python
compose()
reset()
```

不要讓 flush 發生時：

```text
transition state
```

半更新。

---

# 41. Input frame 不得被修改

controller 所有 output：

```python
.copy()
```

或保證不直接修改原始：

```text
frame_list_cycle
```

特別注意：

```python
cv2
numpy slice
```

可能共享 memory。

Source frames 必須保持 immutable。

---

# 42. 新增測試

新增：

```text
tests/test_avatar_transition.py
```

至少包含以下測試。

## Test 1

Speech 正常 pass through：

```text
IDLE → SPEAKING
```

state 正確。

---

## Test 2

Speech → idle：

```text
SPEAKING
→ SETTLING
```

不能直接：

```text
IDLE
```

---

## Test 3

Phase matcher 必須在：

```text
4~6 frames
```

內選擇。

例如 candidate：

```text
+4 score 0.5
+5 score 0.1
+6 score 0.4
```

必須：

```text
planned = 5
```

---

## Test 4

Phase matching 不修改 / jump idx。

送入：

```text
10
11
12
13
14
```

controller 不得自己輸出：

```text
18
```

或要求 inference index reset。

---

## Test 5

Ping-pong：

```text
0 1 2 3 3 2 1 0 0 1
```

future prediction 正確。

---

## Test 6

Mouth settling：

mouth ROI brightness：

```text
200
→
160
→
120
→
80
→
40
→
0
```

或 smoothstep 對應值。

必須：

```text
monotonic
```

最終完全等於 idle。

---

## Test 7

Speech 在 settling 中重新開始。

例如：

```text
speech
idle
idle
speech
```

最後 state 必須：

```text
SPEAKING
```

舊 settling 完全取消。

---

## Test 8

Speech 在 crossfade 中重新開始。

一樣必須：

```text
立即 SPEAKING
```

---

## Test 9

Generation change：

```text
generation 1
```

的：

```text
last speech frame
```

不能污染：

```text
generation 2
```

---

## Test 10

Micro crossfade：

2 frames 最終：

```text
100% target
```

---

## Test 11

Ghosting guard：

如果：

```text
MAD > threshold
```

不能 whole-frame blend。

必須：

```text
ROI-only
```

或：

```text
skip crossfade
```

---

## Test 12

custom frame：

```text
frame_type > 1
```

不能做 MuseTalk idle phase matching。

---

## Test 13

flush_talk reset。

flush 後：

```text
state
previous frame
speech frame
crossfade frame
generation
```

全部清掉。

---

## Test 14

Input source frame immutable。

compose 前後：

```python
np.array_equal(source_before, source_after)
```

必須 True。

---

# 43. MouthContinuity 原測試不能壞

必須執行：

```bash
uv run pytest -q tests/test_mouth_continuity.py
```

所有原測試必須 pass。

另外新增：

```bash
uv run pytest -q tests/test_avatar_transition.py
```

---

# 44. 全部測試

最後執行：

```bash
uv run pytest -q
```

若整套測試有既有、與此次修改無關的 failure：

請明確列出：

```text
原本就失敗
vs
本次修改造成
```

不要偷偷修改 unrelated tests。

---

# 45. Compile check

執行：

```bash
python -m compileall \
    src/avatars/base.py \
    src/avatars/musetalk/avatar.py \
    src/avatars/musetalk/avatar_transition.py \
    src/avatars/musetalk/mouth_continuity.py
```

---

# 46. 不允許做的事情

不要：

```text
新增 sleep 做轉場
```

不要：

```text
等待 audio
```

不要：

```text
hold TTS
```

不要：

```text
修改 WebRTC timestamp
```

不要：

```text
修改 audio fps
```

不要：

```text
降低 MuseTalk batch performance
```

不要：

```text
改 MuseTalk model
```

不要：

```text
增加新的 GPU inference
```

不要：

```text
真正 rewind idle sequence
```

不要：

```text
直接 current_idx += best_offset
```

不要：

```text
把 ±10 frame phase matching 理解成跳 frame
```

不要：

```text
長時間 whole-frame crossfade
```

---

# 47. Performance requirement

transition 只能增加：

```text
OpenCV
numpy
少量 frame copy
descriptor comparison
```

目標：

```text
每 frame 額外 CPU 開銷極小
```

不能新增：

```text
Torch model inference
```

---

# 48. 最終 runtime 流程

完成後必須是：

```text
                  TTS Audio
                      │
                      ▼
              MuseAudioStreamHandler
                      │
                      ▼
               MuseTalk inference
                      │
                      ▼
                res_frame_queue
                      │
                      ▼
               BaseAvatar.process_frames
                      │
            ┌─────────┴─────────┐
            │                   │
         speech               silence
            │                   │
            ▼                   ▼
 paste_back_frame()      frame_list_cycle[idx]
            │                   │
            └─────────┬─────────┘
                      │
                      ▼
          AvatarTransitionController
                      │
          ┌───────────┴───────────┐
          │                       │
      SPEAKING                Speech End
                                  │
                                  ▼
                         Idle Phase Planning
                         future 4~6 frames
                                  │
                                  ▼
                          Mouth Settling
                            4~6 frames
                                  │
                                  ▼
                         Micro Crossfade
                            2 frames
                                  │
                                  ▼
                                IDLE
                                  │
                                  ▼
                           VideoFrame
                                  │
                                  ▼
                             WebRTC
```

注意：

```text
Audio
```

完全沒有經過：

```text
AvatarTransitionController
```

---

# 49. 實際時序範例

25 FPS：

```text
Frame 100
Speech

Frame 101
Speech

Frame 102
Speech last frame
mouth = open

Speech End
Phase matcher 預測：

Frame 106 score 0.21
Frame 107 score 0.09  ← best
Frame 108 score 0.15

所以 planned settling = 5 frames
```

接著：

```text
103
mouth 80%
idle pose 正常前進

104
mouth 60%

105
mouth 40%

106
mouth 15%

107
mouth 0%
```

然後：

```text
108
micro crossfade 50%

109
100% idle
```

最終：

```text
110
111
112
...
```

正常 idle。

沒有：

```text
102
直接跳到 107
```

---

# 50. Speech 突然重新開始範例

假設：

```text
102 Speech End

103 settling
104 settling

105 新 speech 到
```

結果必須：

```text
102 speech
103 settling
104 settling
105 speech opening
106 speech
107 speech
```

而不是：

```text
105 settling
106 settling
107 crossfade
108 speech
```

Audio 永遠優先。

---

# 51. 建議實作順序

請依此順序修改，不要一次全部混在一起。

### Step 1

先 refactor：

```text
BaseAvatar
```

新增：

```text
_avatar_transition
_compose_avatar_transition()
```

確保 fallback 舊功能完全正常。

### Step 2

修改：

```text
MouthContinuityController
```

加入：

```text
transition_frames override
```

跑原測試。

### Step 3

建立：

```text
AvatarTransitionController
```

只做：

```text
SPEAKING
SETTLING
IDLE
```

跑 tests。

### Step 4

加入：

```text
Phase Matching planner
```

但不得改 idx。

### Step 5

加入：

```text
Micro Crossfade
```

與 ghosting guard。

### Step 6

處理：

```text
speech interruption
generation change
custom video
flush
```

### Step 7

修改 config。

### Step 8

全測試。

---

# 52. 最終驗收標準

功能完成必須同時滿足：

```text
[ ] Speech 開始沒有增加延遲

[ ] Speech 結束不會下一幀直接完全閉嘴

[ ] Mouth close 約 160~240 ms

[ ] Idle frame index 沿現有 MuseTalk sequence 前進

[ ] Phase matching 不 rewind

[ ] Phase matching 不修改 inference idx

[ ] Crossfade 最多 2~3 frames

[ ] Pose 差太大時不 whole-frame blend

[ ] 新 speech 可隨時中斷 transition

[ ] flush 可完整 reset

[ ] generation 不互相污染

[ ] custom video 不做 idle phase matching

[ ] direct audio starvation 不會偷偷 advance transition

[ ] 原 MouthContinuity tests 全部通過

[ ] 新 AvatarTransition tests 全部通過

[ ] pytest regression 通過
```

---

# 53. 完成後請回報

完成修改後，請提供：

1. 修改了哪些檔案
2. 每個檔案修改目的
3. AvatarTransitionController 的 state diagram
4. Phase Matching 如何保證不跳 idx
5. 最終 config defaults
6. pytest 結果
7. compileall 結果
8. 任何仍可能需要實機調整的參數
9. 不要只貼 diff，要簡短說明架構改變

實機第一輪建議參數：

```yaml
avatar_transition: true

gap_grace_frames: 1
opening_frames: 2

settling_frames: 5
settling_min_frames: 4
settling_max_frames: 6

phase_matching_enabled: true
phase_temporal_penalty: 0.015

micro_crossfade_enabled: true
micro_crossfade_frames: 2
micro_crossfade_fullframe_max_diff: 18.0
```

優先調整順序：

```text
1. settling_min/max
2. gap_grace_frames
3. micro_crossfade_frames
4. fullframe_max_diff
5. phase temporal penalty
```

不要先調 TTS、Audio buffer、WebRTC 或 MuseTalk batch size。
