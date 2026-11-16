<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Nova Avatar 商用交付前合規與授權檢查清單（Phase A）

本文件彙整 Nova Avatar（`jetson-orin` Phase A 交付基線）在**內部 POC 試用**與**對外商業銷售**兩階段的授權邊界、阻礙項目與交付前檢查程序。根目錄 [Apache-2.0](../LICENSE) 僅涵蓋 Nova Avatar 原創整合程式碼，**不授予**任何第三方模型、權重、語音服務、人物素材或外部開放資料平台之商業權利。

詳細歸屬與上游聲明請併同參閱：
- [config/config_commercial.yaml](../config/config_commercial.yaml)（Phase A 商業審查設定檔基線）
- [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
- [docs/models.md](models.md)
- [docs/software-stack.md](software-stack.md)
- [docs/source-attribution-audit.md](source-attribution-audit.md)

---

## 1. Phase A 商用基線設定（禁止沿用受限或未稽核基線）

[`config/config_commercial.yaml`](../config/config_commercial.yaml) 鎖定以下 Orin Phase A 商用基線：

| 環節 | Phase A 基線選型 | 授權摘要 | 排除項目 |
| --- | --- | --- | --- |
| 數位人呈現 | `model.type: musetalk` + `presentation_modes.<avatar_id>: prerecorded`（**預錄呈現**） | 執行期播放預錄待機／說話影片，不執行即時嘴型權重推論 | 禁止納入 `Wav2Lip`（`Research / Non-commercial`） |
| 語言與視覺模型 | `llm.provider: llamacpp` + `gemma-4-E2B_q4_0-it`（配對 `gemma-4-E2B-it-mmproj.gguf`） | 官方模型卡標示 **Apache-2.0**（固定 revision `675cff42a74c774d6cb76f76d8eacb49b48c9b93`） | 不再沿用含年營收 1,000 萬美元上限之 `LFM2.5`，亦不採用未稽核之 `qwen3.5` |
| 語音轉文字（STT） | `faster-whisper small`（`models/whisper-small/`） | **MIT**（OpenAI `whisper-small` + `faster-whisper`） | 不採用模型授權未稽核之 `FunASR` |
| 語音端點偵測（VAD） | `Silero VAD`（`silero-vad` 6.2.1） | 套件 metadata 標示 **MIT**；**隨附權重尚未獨立稽核**（見下表） | — |

---

## 2. 內部 POC 試用 vs 對外商業銷售（Blocking 關卡）

| 評估項目 | 內部 POC 試用（Internal POC） | 對外商業銷售（External Commercial Sale） | 狀態 |
| --- | --- | --- | --- |
| **TTS 語音合成（`Edge TTS`）** | 可**暫時沿用** `Edge TTS`（`zh-TW-HsiaoChenNeural`）做內網功能、延遲與業務流程驗證 | **嚴禁使用 `Edge TTS`**（`edge-tts` 為 LGPLv3，且微軟線上服務與內建語音未授權商業再散佈）。必須改為授權明確且通過音質／延遲驗收之本機 TTS（優先評估免憑證方案如 `Fun-CosyVoice 3.0` 並審閱模型與 checkpoint 條款）或已簽署商業合約之付費雲端 TTS（並同步修訂 ADR-0006） | **Blocking** |
| **數位人素材（`musetalk_1`）** | 可暫時使用開發測試角色 `musetalk_1` 驗證互動與播放器 | **嚴禁交付 `musetalk_1`**（其 `avator_info.json` 標記 `source_type: "user_upload"`，無書面肖像權與聲音／演繹授權紀錄）。必須由客戶或授權人員重新錄製具完整肖像權與聲音授權書之專屬待機／說話影片（`prerecorded`） | **Blocking** |
| **舞台背景與知識庫文件** | 可使用內部測試圖資與測試 PDF | 必須確認所有客戶現場背景圖／影片、歡迎詞、知識庫文件均具合法商業使用與再散佈權利 | **Blocking** |
| **CWA OpenData API Key** | 可使用測試金鑰並設定場域預設地點 | 必須由商業營運主體自行申請正式 API Key（置於部署端 `config/cwa.env`，禁止進 Git），保留「交通部中央氣象署」出處標示並確認平台規範；不需天氣功能時可設 `weather.enabled: false` | 需部署前確認 |

---

## 3. 第三方元件、模型權重與外部服務稽核總表

| 元件／模型 | 用途與適用階段 | 已查證授權依據 | 未稽核／限制與處置方式 |
| --- | --- | --- | --- |
| **Gemma-4-E2B（含 `mmproj`）** | Phase A 核心 LLM 與附件視覺分析 | Hugging Face 固定 revision `675cff42a74c774d6cb76f76d8eacb49b48c9b93` 模型卡標示 **Apache-2.0**（見 `llama/metadata/gemma4-e2b/`） | 保留上游模型卡、SHA-256 與 Apache-2.0 聲明即可納入商用基線 |
| **whisper-small** | Phase A 語音轉文字（STT） | `openai/whisper-small`（revision `973afd24965f72e36ca33b3055d56a652f456b4d`）目錄內 `LICENSE` 與 `faster-whisper` 皆為 **MIT** | 保留 OpenAI MIT 版權聲明即可納入商用基線 |
| **TAESD（`madebyollin/taesd`）** | 僅 Phase B 即時 MuseTalk 近似 VAE 解碼（Phase A 預錄不用） | **MIT**，Copyright (c) 2023 Ollin Boer Bohan，固定 revision `614f76814bbe30edbe2e627ace1c2234c81a2c0e` | Phase A 預錄呈現不載入；若啟用 Phase B 即時模式須保留 MIT 聲明 |
| **MuseTalk 程式碼 vs 權重** | 數位人編排框架（Phase A 僅作預錄容器／可選離線產製；Phase B 即時推論） | 程式碼為 **MIT**（Copyright (c) 2024 Tencent Music Entertainment Group，`third_party/licenses/MuseTalk-LICENSE.txt`） | **權重未稽核**：`musetalkV15/unet.pth`、TensorRT engine、`models/sd-vae/`、`dwpose`、`s3fd`、`models/face-parse-bisent/` 未完成獨立商用稽核。Phase A 採預錄呈現避開執行期依賴；若使用離線錄製或 Phase B 即時推論，交付前須另行審閱上述權重條款 |
| **Wav2Lip** | 選用引擎目錄（`src/avatars/wav2lip/`） | 上游僅限 **Research / Non-commercial**（`third_party/licenses/Wav2Lip-NON-COMMERCIAL-NOTICE.txt`） | **禁止商用**：對外交付映像／打包必須排除 `src/avatars/wav2lip/` 與任何 Wav2Lip 權重及範例角色 |
| **Silero VAD 權重** | Phase A 伺服器端語音端點偵測 | `silero-vad` 6.2.1 套件 metadata classifier 標示 **MIT License** | **權重未獨立稽核**：wheel 內含 `silero_vad.jit` / `.onnx` 權重但未附獨立 `LICENSE` 檔，訓練資料與權重條款未在本 repo 完成獨立稽核；對外商售前須覆核上游 `snakers4/silero-vad` LICENSE 與權重條款 |
| **BGE-M3** | 選用 RAGFlow 知識庫嵌入（預設停用） | 上游模型卡位於 `https://huggingface.co/BAAI/bge-m3` | **未稽核**：本 repo 未附獨立快照授權查證（且 RAGFlow 另含 Elasticsearch、MySQL、MinIO-compatible、Valkey、Microsoft ODBC EULA 等外部映像）。啟用知識庫交付前須完成逐項審閱 |
| **CWA OpenData（`src/weather/`）** | 選用台灣即時天氣／預報查詢 | 非軟體權重，屬交通部中央氣象署開放資料 API（`https://opendata.cwa.gov.tw/`） | 須遵守政府資料開放授權條款（OGDL v1.0）及平台使用規範、保留資料來源出處（交通部中央氣象署）、並由營運方以商業用途申請自有 API Key；停用時設 `weather.enabled: false` |
| **Edge TTS（`edge-tts`）** | 僅限內部 POC 語音合成 | `edge-tts` 7.2.8 套件 metadata 標示 **LGPLv3**；連線微軟線上端點 | **對外商用 Blocking**：線上服務與聲音條款未過商用審查，交付前必須替換 |
| **pypdfium2 / Tesseract** | Phase A 對話附件 PDF／圖片解析與 OCR | `pypdfium2` 5.14.0（Apache-2.0 OR BSD-3-Clause；已保存 ARM64 wheel 聲明於 `third_party/licenses/pypdfium2-5.14.0/`）；Tesseract 5.3.4 + `tessdata_fast`（Apache-2.0，見 `third_party/licenses/tesseract/`） | 僅就 Apache-2.0／BSD-3-Clause 與上游聲明留存紀錄；Tesseract 訓練資料完整來源未另行稽核 |

---

## 4. 客戶交付前必做檢查項目

在建置或交付對外商業版本前，請逐項打勾並保留紀錄：

- [ ] **驗證商業審查設定檔與合約測試**：執行 `uv run python scripts/check-integration.py config/config_commercial.yaml`，確認 `model.type == "musetalk"`、`presentation_modes` 為 `prerecorded`、`asr.model_size == "small"`、`llm.provider == "llamacpp"` 且 `llm.model == "gemma-4-E2B_q4_0-it"`，並確認無 `wav2lip`、`LFM2.5`、`qwen3.5`。
- [ ] **確認已解除 `Edge TTS` Blocking**：`config/config_commercial.yaml` 與執行期 `config/runtime_overrides.yaml` 之 `tts.type` 已替換為通過商用授權審查與音質驗收之引擎，並已移除 POC 暫用設定。
- [ ] **確認已解除人物素材 Blocking**：`data/avatars/` 內僅包含客戶／公司擁有完整書面肖像與聲音授權之預錄角色（待機影片 + 說話影片），已移除開發測試角色 `musetalk_1`（`user_upload`）及所有 `wav2lip*` 範例角色。
- [ ] **確認發行版無非商用程式碼與未授權權重**：已排除 `src/avatars/wav2lip/`（及依賴環境未保留研究用權重）、確認未打包 `LFM2.5*` / `Qwen3.5*` 權重；若僅提供預錄呈現且不開放現場重錄，確認未誤附不必要之未稽核即時權重。
- [ ] **覆核未獨立稽核項目**：針對本次交付實際啟用的 `Silero VAD` 權重、選用的 `BGE-M3`（若啟用 RAGFlow）與 `CWA OpenData` 商業營運金鑰，已完成法務／合規覆核並留存紀錄。
- [ ] **保留授權聲明與管理端安全邊界**：發行版保留根目錄 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`、`third_party/licenses/`，且已設定管理者驗證邊界（密碼／PIN）與正式 HTTPS 憑證。
- [ ] **執行完整回歸測試**：
  ```bash
  uv run python scripts/check-integration.py
  uv run pytest
  cd web && npm test && npm run build
  ```
