<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 訓練環境實驗
Status: ready-for-agent

依[規格](../spec.md)第 8 點。

- 在 `.local/matcha-train/` 建立獨立 venv，不改主程式 `.venv`；先試上游 `matcha-tts`（PyPI，cp310），失敗再試 CosyVoice 內附的 `third_party/Matcha-TTS`。
- 從 ModelScope `dengcunqin/matcha_tts_zh_en_20251010` 下載 `pytorch_model_sherpa.bin`（約 75 MB）到 `.local/matcha-base/`，記錄 SHA-256 與授權欄原文。
- 驗證能嚴格載入權重，並用幾筆假資料在 CPU 跑一個訓練步驟；不要使用 GPU，也不要啟動伺服器。
- 結果寫在本工單 Comments：選用的來源、版本、依賴清單與授權、安裝與載入的實際指令。無法嚴格載入時，說明差異並提出替代做法，不要自行放寬載入檢查。

## Comments

### 2026-11-24 實驗結果：上游 PyPI `matcha-tts` 可嚴格載入底模

**結論**：不需要 CosyVoice 的 `third_party/Matcha-TTS`。PyPI `matcha-tts==0.0.7.2`（cp310 wheel，MIT，Shivam Mehta）以 `strict=True`、`weights_only=True` 載入 `pytorch_model_sherpa.bin`，輸出 `<All keys matched successfully>`；沒有放寬任何載入檢查。CosyVoice 的 `third_party/Matcha-TTS` 只是 git submodule，指向同一個上游倉庫 `shivammehta25/Matcha-TTS`（MIT），不是另一份程式，所以不必另取。

**底模**
- 來源：ModelScope `dengcunqin/matcha_tts_zh_en_20251010`，檔案 `pytorch_model_sherpa.bin`（74,490,446 位元組），固定在 commit `839c6c33693e1ac54a17a6c4d24ef44d96904674`。
- SHA-256：`a7b0458c146cb1712824a355de27f3969e074b80d02787c9e852fec7006a38ab`（與 ModelScope 檔案清單回報的雜湊一致）。
- 授權欄原文（API `License`）：`Apache License 2.0`；`LicenseName`、`LicenseLink` 為空。頁面沒有說明訓練資料，README 只寫「使用 `dengcunqin/matcha_tts_zh_en` 權重進行微調，聲音改為溫柔女聲，4090 微調 1 小時」。所以授權欄不足以證明資料來源，沿用規格決定 3：以此為底的模型標示 Research / Non-commercial 或更嚴。
- 權重檔結構：305 個鍵，全部帶 `model.` 前綴（`model.mel_mean`、`model.mel_std`、`model.encoder.emb.weight` 形狀 2190x192 等）；`mel_mean`、`mel_std` 在檔內，詞彙量 2190，參數 18.59M。

**架構對應**：用 jetson `matcha_arch.py` 同一組超參數（RoPE Encoder、6 層、`n_channels=192`、decoder `act_fn="snakebeta"`、`n_vocab=2190`）建 `matcha.models.matcha_tts.MatchaTTS`，去掉 `model.` 前綴後 `load_state_dict(strict=True)` 通過。上游 0.0.7.2 本來就支援 RoPE 與 snakebeta。

**CPU 訓練步驟**（`CUDA_VISIBLE_DEVICES=`，隨機 16 kHz 音訊 3 秒經 Vocos 同款 log-mel，批次 2、隨機 token id）：3 步 loss 6.91 → 6.73 → 6.70（dur 5.4、prior 1.0、diff 0.3-0.4），皆為有限值；整個檢查約 12-19 秒（含載入）。

**依賴與授權**（`integrations/matcha-train/requirements.in` / `requirements.txt`，Python 3.10，64 個固定版本，加上 torch、torchaudio、matcha-tts 共 67 個套件）
- 直接依賴：`torch==2.5.0`、`torchaudio==2.5.0`（BSD-3-Clause，與主環境同版；cu124 與 cpu 兩種 wheel 由腳本依 `MATCHA_TRAIN_TORCH` 選）、`lightning 2.6.6`、`torchmetrics`（Apache-2.0）、`diffusers==0.30.3`（Apache-2.0）、`huggingface-hub<1`（Apache-2.0）、`conformer==0.3.2`、`hydra-core==1.3.2`、`omegaconf`、`einops`、`rich`、`gdown`、`soundfile`（MIT/BSD）、`wget`（Public Domain）、`matplotlib`（PSF 類）、`numpy<2`（BSD）。
- 傳遞依賴含 `certifi`（MPL-2.0）、`tqdm`（MPL-2.0 AND MIT）；沒有 GPL 套件。這是開發用訓練環境，不隨專案發佈。
- 刻意不裝：`phonemizer`（GPL-3.0，matcha 的英文音素器用，我們用自己的詞典與 token）、`gradio==3.43.2`、`hydra-optuna-sweeper`、`notebook`、`pre-commit`、`pytest` 等 matcha-tts 宣告的 29 個依賴中訓練用不到的部分。方法是 `matcha-tts` 用 `--no-deps --require-hashes` 安裝（hash 釘在 `integrations/matcha-train/matcha-tts.txt`）。在同一個 venv 做完整 `pip install matcha-tts` 會再多裝 164 個套件，並把 torch 換成 2.14 與 CUDA 13 套件。
- 必要的額外套件（只用 `--no-deps` 時逐一由 ImportError 找出）：`hydra-core`（`matcha.utils` 在套件匯入時就載入）、`gdown`、`wget`、`matplotlib`、`rich`，即使訓練用不到也一定要有。

**實際指令**
```bash
bash scripts/setup-matcha-train.sh            # 預設 torch 2.5.0+cu124
MATCHA_TRAIN_TORCH=cpu bash scripts/setup-matcha-train.sh   # 本次實驗使用
```
腳本依序：`uv venv --python 3.10 .local/matcha-train/venv`；用 PyTorch 索引安裝 torch 與 torchaudio；`uv pip install -r integrations/matcha-train/requirements.txt`；`uv pip install --no-deps --require-hashes -r integrations/matcha-train/matcha-tts.txt`；`scripts/matcha_base_weights.py` 下載底模並核對 SHA-256（已存在且正確就跳過，雜湊不符時停下不覆蓋，另寫 `.local/matcha-base/SOURCE.txt` 記錄來源、commit、雜湊與授權欄）；最後 `scripts/matcha_train_env_check.py` 以 CPU 嚴格載入並跑 3 步。在本工作樹刪掉 venv 從零執行約 19 秒（套件已在 uv 快取），第二次執行 12 秒且不重裝。cu124 變體只做了 `--dry-run` 解析（torch 2.5.0+cu124 與 nvidia-*-cu12 12.4 可解析），沒有安裝、沒有碰 GPU。

**新增檔案**：`scripts/setup-matcha-train.sh`、`scripts/matcha_base_weights.py`、`scripts/matcha_train_env_check.py`、`integrations/matcha-train/{requirements.in,requirements.txt,matcha-tts.txt}`、`tests/test_matcha_train_setup.py`（14 個測試，不連網：以假的 `uv` 與假 python 驗證指令順序與不碰主 `.venv`，下載函式以注入的假下載器驗證雜湊、`.part` 清除與不覆蓋）。`.gitignore` 新增 `.local/matcha-train/` 與 `.local/matcha-base/`（原本 `.local/` 沒有整個被忽略，只列了個別子目錄，venv 與權重會出現在 `git status`）。

**意外與給工單 06 的提醒**
1. 上游 `MatchaTTS.forward` 回傳 4 個值 `(dur_loss, prior_loss, diff_loss, attn)`，jetson `train_matcha.py` 解 3 個值會出錯；GitHub 上游 main 與 PyPI 0.0.7.2 都是 4 個。jetson 用的 CosyVoice 檢出可能是舊 commit，這裡沒有該檢出可核對。
2. 一批裡最短的語句若少於 `out_size`（172 幀）會在 decoder 出現形狀錯誤（假資料 2 秒時重現），訓練時必須像 jetson 那樣把 `out_size` 縮到該批最短長度的 4 的倍數。
3. `diffusers` 不能用最新版（0.41 呼叫 `torch.accelerator`，torch 2.5.0 沒有），釘 0.30.3 並限 `huggingface-hub<1`。
4. 工單 06 可直接 `from matcha.models.matcha_tts import MatchaTTS`，不需要 `sys.path` 技巧；`matcha_train_env_check.py` 的 `build_model`、`load_checkpoint` 與 `fake_batch` 可併入移植後的 `matcha_arch.py`，避免兩份。
5. `torch.load(..., weights_only=True)` 對此底模可用，建議保留，避免載入第三方 pickle 時執行任意程式。
6. 這次沒有改 `THIRD_PARTY_NOTICES.md`（屬工單 09）；09 應加入 Matcha-TTS（MIT，Shivam Mehta）與底模（授權欄 Apache License 2.0，資料來源未說明）。

**驗證**：`uv lock --check`、ruff、pyright、`scripts/check-integration.py` 通過；pytest 1578 passed、2 failed、3 skipped（基準 1564 passed、同樣 2 failed 與 3 skipped：PDF OCR 與 role coordinator 既有失敗，新增的 14 個測試全過、無跳過）。
