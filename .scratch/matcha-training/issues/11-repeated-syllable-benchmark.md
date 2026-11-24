<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 疊字評量腳本
Status: ready-for-agent

依[規格](../spec.md)「疊音與跳音診斷」與驗收。把診斷時的做法固定成可重複的評量，讓重訓後的聲線模型能和曉臻、base 模型直接比較。

- 固定測試集：12 句已知會疊音的句子與 12 句乾淨句（含中英混合），放在 `tools/` 下並進 git；每句合成 3 次。
- 以 Whisper 轉寫並用詞時間戳偵測相鄰重複音節或詞，輸出「疊字句數／總句數」與逐句結果 JSON；Whisper 用 CPU，不佔用 GPU；缺少模型時直接失敗，不得跳過。
- 以 `.venv` 的 sherpa-onnx 直接合成，不啟動伺服器；以假的合成器為單元測試，0 失敗、0 跳過。
- 基準數字：曉臻 17/36、base 1/24（診斷結果）；重訓後的模型目標是疊字句數不高於 base 的水準。

## Comments

### 2026-11-24 實作（分支 `mv2/11-benchmark`）

**檔案**：`tools/tts-bench/repeated_syllables.py`、`tools/tts-bench/sentences.json`（診斷用的 12 句疊字句與 12 句乾淨句，id 與原文同 `asr_meta.json`）、`tests/test_repeated_syllable_benchmark.py`（20 個測試，假合成器與假轉寫器，無模型、無 GPU、無網路）；`tests/conftest.py` 登記為 `speech`。

**用法**（專案根目錄，專案環境；輸入是聲線模型目錄，不需要 `voice.json`，所以 base 模型也能比）：

    uv run --no-sync python tools/tts-bench/repeated_syllables.py models/tts/zh-tw-hsiaochen-edge \
        --output /tmp/hsiaochen.json [--repeats 3] [--whisper-model <本機目錄或已快取的名稱>]

- 腳本內強制 `CUDA_VISIBLE_DEVICES=`，Whisper 與 sherpa-onnx 都在 CPU（4 執行緒，Whisper int8）。
- 找不到 Whisper 模型、或聲線模型目錄缺檔，直接以訊息結束（結束碼 2），不跳過、不寫輸出。
- 預設 Whisper 是 `models/whisper-large-v3-turbo`（診斷用的同一個，離線、本機目錄，數字才能比）。`models/` 不進 git，在 worktree 內要用 `--whisper-model /home/oliver/nova-avatar/models/whisper-large-v3-turbo`。
- 只印一行：`model=<目錄> sha256=<model.onnx 或 model-steps-3.onnx 的 SHA-256> repeat-prone=<疊字次數>/<總次數> clean=<疊字次數>/<總次數>`。JSON 含逐句 `runs`（轉寫、詞時間戳、疊字 token、時長）、`flagged_runs`、`repeated_tokens`、`durations`。
- 判定規則與診斷 `asr.py` 相同：繁轉簡、去標點與空白後，轉寫中相鄰重複的 1–2 字 token（`(.{1,2}?)\1`）若不在參考句中、且不是數字或 ASCII，就算疊字；一次合成有任何疊字即記為一次。分子分母以「合成次數」計（句數 × 重複次數），與診斷的 17/36 同單位。

**實測**（CPU，各約 3 分 55 秒，含載入）：

| 模型 | 疊字（12 句 × 3） | 乾淨（12 句 × 3） | 診斷基準 |
|---|---|---|---|
| zh-tw-hsiaochen-edge（SHA-256 `19dd78e3…6d8c9`） | 19/36 | 2/36 | 17/36；乾淨 2/36 |
| matcha-icefall-zh-en（`model-steps-3.onnx`，SHA-256 `524286bf…b16a`） | 2/36 | 1/36 | 1/24；乾淨 1/12 |

曉臻被標出的句子與診斷一致（tw-reading-16/17/23、number-20 三次全中），差 2 次屬 `noise_scale` 隨機性；base 2/36（`tw-reading-23`、`general-03` 各 1 次）約 5.6%，診斷為 1/24 約 4.2%，同量級。重訓目標：疊字次數比例不高於 base。

**與診斷的差異**：(1) 診斷的 `extra` 欄位用轉寫文字判定，詞時間戳只是記錄（本腳本同樣只記錄，不參與判定）；(2) 診斷的 base 數字是 12 句 × 2 次、換詞典的消融實驗，本腳本是 12 句 × 3 次，直接用 base 目錄自己的詞典與 tokens；(3) 診斷乾淨句沒有中英混合句，本腳本沿用同樣 12 句以保持可比，工單原文「含中英混合」尚未滿足，需要時另加一組混合句（會與診斷基準脫鉤）。

**CI**（Python 步驟）：uv lock、ruff、pyright（0 errors）、`scripts/check-integration.py` 通過；pytest 基準 2 failed / 2010 passed / 3 skipped，之後 2 failed / 2030 passed / 3 skipped（同樣兩個既有失敗：PDF OCR、role coordinator；新增 20 個全過、0 跳過）。`tools/` 不在 ruff 與 pyright 的範圍內，另以 `ruff check --isolated --select E9,F,S102,S113,S301,S310,S605` 檢查過。
