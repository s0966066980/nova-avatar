---
status: accepted
---

# 只支援不需外部憑證的語音引擎

產品完整移除需要第三方 API key、token 或雲端訂閱憑證的 TTS 引擎，包括 DashScope CosyVoice API、Doubao、Tencent 與 Azure TTS；同步刪除其工廠註冊、實作、設定、環境變數、專屬依賴與 UI 文案。STT 保留本機 faster-whisper 與 FunASR；其餘 TTS 僅在不需外部憑證的前提下列入支援目錄，藉此縮小部署與秘密管理範圍。

2026-10-30 進一步收斂：TTS 只保留 BreezyVoice 與 Edge TTS（first-audio-latency issue 18），CosyVoice 2、Fun-CosyVoice3、Fish、GPT-SoVITS、IndexTTS2 與 XTTS 一併移除；已存設定指到這些引擎時改用 Edge TTS 並提示。

2026-11-24 新增不需外部憑證的 Matcha 聲線模型引擎（CPU、sherpa-onnx），TTS 支援清單改為 BreezyVoice、Edge TTS、Matcha；理由與使用限制見 ADR 0025。

2026-11-26 移除 FunASR（Fun-ASR-Nano-2512）STT 引擎：場域與預設設定都使用 faster-whisper，FunASR 未被使用，維護者也不再需要。STT 只剩 faster-whisper；已存設定仍選 `funasr` 時改用 faster-whisper `small` 並記錄警告，FunASR 專用的 `asr.output_script` 欄位載入時忽略。首段「STT 保留本機 faster-whisper 與 FunASR」為當時的決定，原文保留。
