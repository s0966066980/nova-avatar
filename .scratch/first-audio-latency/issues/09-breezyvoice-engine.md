<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# BreezyVoice 引擎
Status: resolved

依[規格](../spec.md)。BreezyVoice（MediaTek，程式碼與權重 Apache-2.0）以 CosyVoice v1 為基礎，吃繁體字、以 g2pW 處理台灣讀音、可指定注音；不支援串流，以參考音訊＋逐字稿複製聲線。

- 先試以專案現有 `scripts/cosyvoice_fastapi_server.py` 載入 BreezyVoice 權重；不相容再新增獨立伺服器，同樣只綁 loopback、模型目錄來自 `models/` 掃描（ADR 0021、CODING_STANDARDS 規則 1）。
- 新增 `breezyvoice` 引擎：參考音訊與逐字稿取自音訊庫；以可播回覆片段為單位合成。
- 權重下載比照 `scripts/musetalk_weights.py` 釘 commit 與 sha256。
- 範例參考錄音只供開發，不設為正式預設；在 Comments 記錄其授權查證結果。
- THIRD_PARTY_NOTICES 與軟體組合文件加入 BreezyVoice。

完成：引擎單元測試；實機合成一句繁體中文並記錄第一個片段合成時間。

## Comments

### 2026-10-30 實作（分支 `fal/09-breezyvoice-engine`）

**現有伺服器能否載入**（只用 CPU，`CUDA_VISIBLE_DEVICES=""`）：原樣不行。BreezyVoice 的
`cosyvoice.yaml` 是舊版 CosyVoice v1 格式，現行 `~/CosyVoice` 的 `TransformerLM` 必填
`sampling`，`AutoModel` 直接 `TypeError`。因此沿用 `scripts/cosyvoice_fastapi_server.py`
（不另開伺服器，仍只綁 loopback、模型目錄來自 `models/` 清單），以資料夾內的
`word_utils.py` 辨識 BreezyVoice，載入時：

- 以 hyperpyyaml overrides 補上 BreezyVoice 原本的 top-k 25 取樣；
- 修正 prompt mel 取樣率：現行前端一律以 24 kHz 抽 prompt 特徵，v1 模型需 22.05 kHz
  （否則參考聲音的頻譜偏移約 9%），改用模型本身取樣率；
- 文字先過 g2pW，依 BreezyVoice 的字頻／讀音表在罕用字與非常用讀音後加注音
  （例：`垃[:ㄌㄜ4]圾[:ㄙㄜ4]`），已寫好的 `[:注音]` 保留；`/health` 回報
  `family: breezyvoice`、`streaming: false`，整段合成不串流。

CPU 實測：模型載入 6–12 s；`/inference_zero_shot` 端對端合成成功，Whisper 回辨
「歡迎來到台北，我們一起研究垃圾分類」。g2pW（CPU、6 執行緒）每片段 P50 44 ms、
P95 86 ms（原套件預設 2 執行緒為 112／233 ms）；可用 `BREEZYVOICE_G2PW_THREADS` 調整。

**引擎**：新增 `breezyvoice`（`src/tts/engines/breezyvoice.py`），以 22.05 kHz PCM 重取樣，
每個可播回覆片段送一次 zero-shot。參考音訊只能選音訊庫 ID，無內建預設聲音；逐字稿
優先用 `tts.ref_text`，否則用音訊庫記錄的逐字稿。音訊庫上傳新增選填 `transcript`
（500 字內），控制台選 BreezyVoice 時會帶入／一併上傳。日誌 `breezyvoice first audio:X s`
即第一個片段合成時間。

**權重**：`scripts/breezyvoice_weights.py` 釘版本＋SHA-256，已下載到主 checkout 的
`models/BreezyVoice`（`--check` 通過）：BreezyVoice `e33b502e…`（僅 llm/flow/hift/onnx/yaml/
spk2info，未抓 JIT／TensorRT 匯出）、BreezyVoice GitHub `d592c9d3…` 的 `word_utils.py`
（以 `ast.literal_eval` 讀取，不執行）、g2pW ONNX `YC-Chen/g2pW` `fb4784f7…`（原
`storage.googleapis.com` 網址已 404，改用作者本人的 HF 倉庫）、`bert-base-chinese`
分詞檔 `8f23c25b…`。

**新依賴**：`g2pw==0.1.1`（Apache-2.0）須裝在 conda 環境 `cosyvoice`（用 `--no-deps`，
避免拉 CPU 版 onnxruntime 覆蓋 onnxruntime-gpu）；主 venv 與 `pyproject.toml` 不變。
本次未改動 conda 環境，只在 scratchpad 目錄以 `--target` 試裝。

**範例參考錄音授權查證**：BreezyVoice GitHub 的 `data/example.wav`（17.2 s；README 寫
`tc_speaker.wav`，實際檔名不同）只受倉庫整體 Apache-2.0 涵蓋，未說明說話者身分、同意或
錄音來源；對應逐字稿看來取自中文維基百科「加密」條目導言（CC BY-SA，未逐字比對）。結論：僅供開發，不設為
預設、不納入發行；正式聲線須自錄或取得書面授權。開發用片段已切成第一句
（1.10–9.00 s，7.9 s）：
`/tmp/claude-1000/-home-oliver-nova-avatar/f284899e-3e7d-40e8-bf07-77d0ecc09394/scratchpad/breezy-dev-prompt.wav`（暫存，不入庫）。

**授權文件**：`THIRD_PARTY_NOTICES.md` 新增「BreezyVoice and g2pW」段、
`docs/software-stack.md` 新增一列、README 補安裝步驟（皆為新增，不動 ticket 11 的段落）。

**未處理／留給後續**：

- 數字、日期、金額不做正規化（wetext 的 modelscope 資源回 403，現行伺服器本來也關閉
  text frontend），`2026年` 以阿拉伯數字直接送入；留給 ticket 10 的字錯率評估決定。
- 端點仍是 `async def` 在 event loop 上做推論（security-followups 03），不串流後一次
  阻塞整段合成時間。
- 參考錄音被裁到 8 秒，逐字稿必須對應裁切後的內容。

驗證（已合併 `first-audio-latency`，含 ticket 11）：`pytest` 1155 passed、2 failed（皆為已知 worktree
基準失敗）、3 skipped；`ruff`、`pyright`、`scripts/check-integration.py` 通過；web `lint`／`test`（210）／`build` 通過。

### 待實機驗證

GPU 只剩約 2.4 GB；BreezyVoice（約 300M LLM＋flow＋HiFT，FP32）預估 2–3 GB，可能需先完成
ticket 12 釋出顯存。套用 TTS 需先斷開舞台連線。

1. 安裝 g2pw：
   `/home/oliver/anaconda3/envs/cosyvoice/bin/python -m pip install --no-deps g2pw==0.1.1`
   預期 `Successfully installed g2pw-0.1.1`。
2. 檢查權重：`uv run --no-sync python scripts/breezyvoice_weights.py --check`
   預期 `BreezyVoice and g2pW weights verified`。
3. 控制台「語音」→ 引擎選 BreezyVoice →「參考語音逐字稿」填
   `在密碼學中，加密是將明文資訊改變為難以讀取的密文內容，使之不可讀的方法。` →
   上傳 `breezy-dev-prompt.wav` → 套用。預期試聽「語音設定完成」，
   `curl -s 127.0.0.1:50000/health` 含 `"family":"breezyvoice","streaming":false`；
   記錄 `nvidia-smi` 前後顯存差。
4. 第一個片段時間（約 15 字，暖機後 20 次）：
   ```bash
   for i in $(seq 20); do curl -s -o /dev/null -w '%{time_total}\n' \
     -F 'tts_text=歡迎來到臺北，我是你的數位助理。' \
     -F 'prompt_text=在密碼學中，加密是將明文資訊改變為難以讀取的密文內容，使之不可讀的方法。' \
     -F 'prompt_wav=@breezy-dev-prompt.wav' http://127.0.0.1:50000/inference_zero_shot; done | sort -n
   ```
   取 P50／P95 對照目標 0.4／0.7 s；再以舞台講一句，於後端日誌讀
   `breezyvoice first audio:` 與 `logs/cosyvoice-server.log` 的 rtf。
5. 實測後把顯存、P50／P95 寫回本節；達標或交給 ticket 10 後改 `Status: resolved`。

### 2026-10-30 實機（orchestrator）
g2pw 0.1.1 已裝入 cosyvoice conda 環境。在 MuseTalk＋E2B 已載入的 GPU 上以開發用參考錄音實跑（issue 10 評比）：第一個片段（約 15 字）合成 P50 2.48／P95 2.94 s，LLM 生成中 3.20 s；額外顯存峰值 5.9 GB（總用量 23.9／24.5 GB）；500 句 0 失敗。引擎可用，但遠未達 0.4 s 目標，是否採用見 issue 10。
