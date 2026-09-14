"""配置資料結構定義"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class WebConfig:
    """前端 Web 配置"""
    port: int = 3000
    host: str = "0.0.0.0"


@dataclass
class AppConfig:
    """應用配置"""
    listenport: int = 8010
    listenhost: str = "0.0.0.0"  # 監聽地址：0.0.0.0 允許外部訪問，127.0.0.1 僅本地
    max_session: int = 1
    
    # SSL/HTTPS 配置
    ssl: bool = False  # 主開關：true 啟用 HTTPS，false 使用 HTTP
    ssl_cert: Optional[str] = None  # SSL 證書檔案路徑（.pem 或 .crt）
    ssl_key: Optional[str] = None   # SSL 私鑰檔案路徑（.key）
    
    # 前端配置（可選，支援巢狀字典或 WebConfig 物件）
    web: Optional[Dict[str, Any]] = field(default_factory=lambda: {"port": 3000, "host": "0.0.0.0"})


@dataclass
class ERNeRfConfig:
    """ERNeRF 專用配置"""
    # 資料與路徑
    pose: str = "data/avatars/ernerf_obama/data_kf.json"
    au: str = "data/avatars/ernerf_obama/au.csv"

    workspace: str = "data/avatars/ernerf_obama/"
    ckpt: str = "data/avatars/ernerf_obama/ngp_kf.pth"
    torso_imgs: str = ""

    # 取樣與訓練相關
    data_range: List[int] = field(default_factory=lambda: [0, -1])
    seed: int = 0
    num_rays: int = 4096 * 16
    cuda_ray: bool = False
    max_steps: int = 16
    num_steps: int = 16
    upsample_steps: int = 0
    update_extra_interval: int = 16
    max_ray_batch: int = 4096

    # loss 相關
    warmup_step: int = 10000
    amb_aud_loss: int = 1
    amb_eye_loss: int = 1
    unc_loss: int = 1
    lambda_amb: float = 1e-4

    # 網路 / 渲染 backbone 選項
    fp16: bool = False
    bg_img: str = "white" #  white |  black
    fbg: bool = False
    exp_eye: bool = False
    fix_eye: float = -1.0
    smooth_eye: bool = False
    torso_shrink: float = 0.8

    # 資料集 / 空間相關
    color_space: str = "srgb"
    preload: int = 0
    bound: float = 1.0
    scale: float = 4.0
    offset: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    dt_gamma: float = 1.0 / 256.0
    min_near: float = 0.05
    density_thresh: float = 10.0
    density_thresh_torso: float = 0.01
    patch_size: int = 1

    # 嘴唇 / 軀幹相關
    init_lips: bool = False
    finetune_lips: bool = False
    smooth_lips: bool = False
    torso: bool = False
    head_ckpt: str = ""

    # GUI 與相機
    gui: bool = False
    radius: float = 3.35
    fovy: float = 21.24
    max_spp: int = 1

    # 其它雜項（音訊注意力等）
    att: int = 2
    aud: str = ""
    emb: bool = False

    ind_dim: int = 4
    ind_num: int = 10000
    ind_dim_torso: int = 8
    amb_dim: int = 2
    part: bool = False
    part2: bool = False
    train_camera: bool = False
    smooth_path: bool = False
    smooth_path_window: int = 7

    # ASR 相關
    asr: bool = False
    asr_wav: str = ""
    asr_play: bool = False
    asr_model: str = "cpierse/wav2vec2-large-xlsr-53-esperanto"
    asr_save_feats: bool = False

    # 全身模式相關
    fullbody: bool = False
    fullbody_img: str = "data/fullbody/img"
    fullbody_width: int = 580
    fullbody_height: int = 1080
    fullbody_offset_x: int = 0
    fullbody_offset_y: int = 0

    # -O 快捷選項：等價於 fp16 + cuda_ray + exp_eye
    O: bool = False


@dataclass
class TalkingGaussianConfig:
    """TalkingGaussian 專用配置"""
    # 模型路徑
    source_path: str = "data/avatars/talkinggaussian_obama/Obama/source"
    model_path: str = "data/avatars/talkinggaussian_obama/Obama/model"
    bg_img: str = "white"
    sh_degree: int = 3


@dataclass
class MuseTalkQualityConfig:
    """MuseTalk 角色製作時寫入素材的臉框與融合參數。"""
    bbox_shift: int = 0
    extra_margin: int = 10
    parsing_mode: str = "jaw"
    left_cheek_width: int = 90
    right_cheek_width: int = 90
    upper_boundary_ratio: float = 0.5
    expand: float = 1.5
    mask_blur_ratio: float = 0.05
    # Keep the generated mouth temporally continuous across streamed fragments.
    mouth_continuity: bool = True
    # Align the final generated mouth to the moving idle-frame ROI during close.
    mouth_continuity_idle_alignment: bool = True
    opening_frames: int = 2
    settling_enabled: bool = True
    avatar_transition: bool = True
    settling_frames: int = 5
    settling_min_frames: int = 4
    settling_max_frames: int = 6
    phase_matching_enabled: bool = True
    phase_temporal_penalty: float = 0.015
    micro_crossfade_enabled: bool = True
    micro_crossfade_frames: int = 2
    micro_crossfade_fullframe_max_diff: float = 18.0
    max_tts_audio_wait_seconds: float = 0.35
    gap_grace_frames: int = 1
    closing_frames: int = 4


@dataclass
class Wav2LipQualityConfig:
    """Wav2Lip 角色製作時的臉框留白。"""
    pad_top: int = 0
    pad_bottom: int = 10
    pad_left: int = 0
    pad_right: int = 0


@dataclass
class ModelConfig:
    """模型配置"""
    type: str = "musetalk"  # wav2lip | musetalk | ultralight | ernerf | talkinggaussian
    avatar_id: str = "avator_1"
    batch_size: int = 16
    model_path: str = "./models"
    # 256 口型貼回時的觀感；不需重新製作角色
    mouth_sharpen: float = 0.5
    paste_interpolation: str = "lanczos"  # lanczos | cubic | linear

    # 模型專屬配置
    ernerf: ERNeRfConfig = field(default_factory=ERNeRfConfig)
    talkinggaussian: TalkingGaussianConfig = field(default_factory=TalkingGaussianConfig)
    musetalk: MuseTalkQualityConfig = field(default_factory=MuseTalkQualityConfig)
    wav2lip: Wav2LipQualityConfig = field(default_factory=Wav2LipQualityConfig)


@dataclass
class TTSConfig:
    """TTS 配置"""
    type: str = "edgetts"  # edgetts | fishtts | gpt-sovits | cosyvoice | fun-cosyvoice3 | indextts2 | xtts
    mode: str = "auto"  # auto | zero_shot | cross_lingual | instruct
    ref_file: str = "zh-TW-HsiaoChenNeural"
    ref_text: Optional[str] = None
    tts_server: str = "http://127.0.0.1:9880"
    model: str = ""
    language: str = "Chinese"
    speaker: str = "Vivian"
    instruct: str = ""
    device: str = "auto"  # auto | cpu | cuda
    edge_persistent_worker: bool = True
    edge_prefetch: bool = True


@dataclass
class ASRConfig:
    """ASR 語音識別配置"""
    mode: str = "server"  # 互動麥克風固定由 WebRTC 傳到伺服器
    type: str = "whisper"  # whisper (faster-whisper) | funasr
    model_size: str = "base"  # engine-specific model name or Hugging Face/local path
    language: str = "zh"  # zh | en | auto
    output_script: str = "traditional-tw"  # FunASR: traditional-tw | simplified
    device: str = "auto"  # auto | cpu | cuda


@dataclass
class VADConfig:
    """VAD 語音活動檢測配置（服務端端點檢測）"""
    enabled: bool = True
    type: str = "silero"
    sample_rate: int = 16000
    frame_ms: int = 0  # Silero 固定使用 32ms/512 點
    threshold: float = 0.5
    aggressiveness: int = 2  # 保留用於讀取舊配置，不再暴露為可選引擎
    device: str = "cpu"  # silero 專屬：cpu | cuda | auto
    model_path: str = ""  # silero 專屬：本地 silero_vad.jit/.onnx，留空自動載入
    use_onnx: bool = False  # silero 專屬：用 onnxruntime 推理

    # 端點檢測引數（與引擎無關）
    speech_start_ms: int = 100  # 連續多久判定為語音才算開口
    min_speech_ms: int = 250  # 短於此時長的片段當噪聲丟棄
    min_silence_ms: int = 500  # 連續靜音多久判定說完（端點）
    speech_pad_ms: int = 150  # 片段前後各留多少音訊，避免吃字
    max_speech_ms: int = 15000  # 單段上限，超過強制切斷；0 = 不限制


@dataclass
class ResponseRouterConfig:
    """回覆路由配置"""
    enabled: bool = True
    rule_first: bool = True
    llm_fallback: bool = True
    board_threshold: float = 3.0
    simple_threshold: float = 0.0
    classifier_max_tokens: int = 4


@dataclass
class BoardConfig:
    """看板配置"""
    enabled: bool = True
    max_items: int = 8


@dataclass
class ReplyRulesConfig:
    """提供給單一 LLM 的自然語言回覆規則。"""
    revision: int = 1
    activation: str = ""
    speech: str = ""
    board: str = ""


@dataclass
class AssistantProfileConfig:
    """使用者從控制台管理的助手身分與輸出偏好。"""
    assistant_name: str = ""
    system_prompt: str = ""
    restriction_prompt: str = ""
    output_locale: str = "zh-TW"
    enforce_output_locale: bool = True
    forbidden_self_names: List[str] = field(default_factory=list)


@dataclass
class LLMConfig:
    """LLM 配置"""
    api_key: str = ""
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    # ollama | llamacpp
    provider: str = "ollama"
    llamacpp_dir: str = ""
    llamacpp_host: str = "127.0.0.1"
    llamacpp_port: int = 8080
    llamacpp_ctx: int = 8192
    llamacpp_threads: int = 0  # 0 = 自動用滿 CPU
    max_tokens: int = 128  # 語音對話宜短，顯著降低尾端延遲
    response_max_chars: int = 120  # 每次回答的約略字數上限
    # Legacy compatibility only. New writes use assistant_profile.system_prompt.
    system_prompt: str = ""
    # 透傳給 OpenAI 相容介面的額外請求體引數
    # 例如 Ollama 關閉思考鏈：{"reasoning_effort": "none"}
    extra_body: Dict[str, Any] = field(default_factory=dict)
    response_router: ResponseRouterConfig = field(default_factory=ResponseRouterConfig)
    board: BoardConfig = field(default_factory=BoardConfig)
    reply_rules: ReplyRulesConfig = field(default_factory=ReplyRulesConfig)
    assistant_profile: AssistantProfileConfig = field(default_factory=AssistantProfileConfig)


@dataclass
class AudioConfig:
    """音訊配置"""
    fps: int = 50
    sample_rate: int = 16000
    # 滑動視窗配置
    l: int = 10  # left length
    m: int = 8   # middle length
    r: int = 10  # right length
    # 音影像對齊補償（毫秒）。嘴型是用一段 200ms 的 mel 視窗生成的，而該視窗
    # 從配對的音訊幀「開始」往後取，等效中心落在 +100ms，因此嘴型會領先聲音。
    # 正值把音訊輸出往前推（治「聲音比嘴慢」），負值往後延。0 = 不補償。
    av_offset_ms: int = 0


@dataclass
class VideoConfig:
    """影片配置"""
    width: int = 450
    height: int = 450
    fps: int = 25


@dataclass
class CustomVideoConfig:
    """自定義影片配置"""
    config_path: str = ""


@dataclass
class ReplyStreamingConfig:
    """回覆語音串流配置"""
    enabled: bool = False
    # Phase 10 direct PCM fan-out has not passed the real-device A/V and
    # listening-quality gates. Keep the validated renderer-owned audio path
    # unless an isolated soak explicitly opts into the experiment.
    decoupled_audio_clock: bool = False
    inter_fragment_timeout_seconds: float = 5.0
    weak_min_chars: int = 24
    soft_limit_chars: int = 72
    hard_limit_chars: int = 120
    # Strong punctuation only emits a fragment after this many content chars.
    # Raising it joins short sentences and reduces separate TTS requests.
    strong_min_chars: int = 1


@dataclass
class StageConfig:
    """數字人舞台顯示配置。"""
    caption_max_chars: int = 120
    caption_x: int = 50
    caption_y: int = 90
    caption_width: int = 100
    board_style: str = "glass"
    board_width: int = 252
    board_height: int = 300
    board_transparency: int = 28
    board_x: int = 100
    board_y: int = 0
    board_preset: str = "tr"
    board_preview: bool = False
    board_open_x: int = 50
    board_open_y: int = 8
    mic_x: int = 50
    mic_y: int = 62
    mic_preset: str = "custom"


@dataclass
class Config:
    """全域性配置"""
    app: AppConfig = field(default_factory=AppConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    custom_video: CustomVideoConfig = field(default_factory=CustomVideoConfig)
    reply_streaming: ReplyStreamingConfig = field(default_factory=ReplyStreamingConfig)
    stage: StageConfig = field(default_factory=StageConfig)
    
    # 其他動態配置
    sessionid: int = 0
    customopt: List = field(default_factory=list)
    
    @property
    def ernerf(self) -> ERNeRfConfig:
        """返回 model.ernerf"""
        return self.model.ernerf

    @property
    def talkinggaussian(self) -> TalkingGaussianConfig:
        """返回 model.talkinggaussian"""
        return self.model.talkinggaussian
