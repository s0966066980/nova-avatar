<!-- Copyright (c) 2026 HongXian0903 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 測試

本目錄與各層的 `tests/` 共同構成目前版本的測試基準。發行範圍與驗收規則定義在
[`current-version-baseline.json`](current-version-baseline.json)，說明（必要基準、`gpu` 與 `live` 標記、
本機完整執行方式）見[目前版本的主要測試基準](../docs/project/current-version-testing.md)。
本機基準以 `scripts/check-current-version.py` 在已準備好的 CUDA 環境執行；GitHub 的 GPU runner 另行設定中。

主要回歸（`not live`）維持離線、可重現、自足；每個測試模組必須屬於且只屬於一個產品領域，
未分類的模組會讓 collection 失敗。缺少 GPU 或必要依賴是失敗，不是可接受的 skip。

## 產品領域

| 標記 | 範圍 |
| --- | --- |
| `avatar` | MuseTalk 轉場、嘴型連續與渲染品質 |
| `conversation` | 回覆協定、串流、媒體隔離、播放與語音工作階段 |
| `governance` | 品牌、授權、打包與整合稽核契約 |
| `llm` | 模型請求、設定檔、正規化與本機 llama.cpp 生命週期 |
| `ragflow` | 選用的 RAGFlow 部署、設定、用戶端與回合整合 |
| `runtime` | 伺服器健康檢查、執行期設定與選用依賴契約 |
| `speech` | ASR、VAD、TTS 引擎與 Edge TTS 工作行程生命週期 |

`slow` 是手動維護的執行提示，不是完整的耗時預算；`live` 標示依賴本機環境的檢查
（已配置的模型、已安裝的 llama-server、本機 CPU 的實際時間預算）。執行標記是產品領域標記之外的補充。

## 常用指令

```bash
uv run --no-sync pytest                          # 預設：不含 gpu
uv run --no-sync pytest services/tts             # 只跑一層
uv run --no-sync pytest -v -ra -m "speech and not live"   # 單一產品領域
uv run --no-sync pytest -v -ra -m "not live"     # 主要 Python 回歸
NOVA_AVATAR_LIVE_LLM_CONTRACT=1 uv run --no-sync pytest -v -ra -m live   # 已配置模型與已安裝 binary 的檢查
```

## 合併原則

只有在模組擁有獨立的現行產品契約，或有特殊的執行邊界時，才保留獨立模組；小模組只有在斷言與歸屬仍清楚時才合併。
否則檔案路徑保持穩定，以免破壞連結。

每條規則只有一個負責的測試。位於其上的層（工作管理器、HTTP 路由）只保留自己多出來的部分：接線，
以及失敗對應的狀態或訊息。路由權限由 `test_route_access.py` 負責，它在真實應用程式上掃過所有路由；
其他模組只斷言自己的路由被宣告為 `ADMIN`。

共用的 fake 與 fixture 放在 `*_fakes.py` 與 `access_helpers.py` 輔助模組。測試模組不得 import 另一個測試模組，
所以合併或刪除其中一個不會破壞其他的。

## 測試放在哪裡

每個處理層自己擁有測試（ADR 0027）：`core/tests/`、`avatar/tests/`、
`services/stt/tests/`、`services/llm/tests/` 與 `services/tts/tests/`。測試只有在
除了 `nova_core.utils` 之外不需要核心任何東西時，才放進某一層的資料夾；凡是會建立
核心設定、驅動伺服器或串接多個層的測試（包含會載入核心設定的各層合約測試）都放在
`core/tests/`。本資料夾 `tests/` 只保留不屬於任何單一層的測試：品牌與授權稽核、
相依鎖定、啟動與權重腳本、ruff 安全規則，以及層級邊界設定。測試檔名在整個儲存庫內
保持唯一。

每個測試模組用 `pytestmark = pytest.mark.<領域>` 自己宣告產品領域（`gpu`／`live`／`slow` 同樣標在模組或
測試函式上），沒有集中登記表：新增、搬移或刪除測試都不用改別的檔案。根目錄的 `conftest.py` 只負責
「沒宣告領域就讓 collection 失敗」，以及測試不得寫入 `data/` 的規則，所以適用於每個資料夾。測試資料夾沒有 `__init__.py`；`pyproject.toml`
的 `pythonpath` 把每個套件根目錄、測試資料夾與各層腳本資料夾放進 `sys.path`，所以
像 `llm_fakes` 這樣的輔助模組可在任何測試中直接以模組名稱匯入。
`uv run --no-sync pytest <資料夾>` 只執行單一資料夾。

研究與基準工具的結論記在工單後（本機 `.scratch/`，更早的在 git 歷史），決定套用完就連同它的測試一併刪除。

已過時的產品契約不必留成選用的 skip。仍支援的通用行為，用自足的 fixture 取代已退役模型的依賴。
刪除測試時，要記下現行契約或已接受的 ADR 作為理由；不要因為遷移、安全或聲明相關的測試含有舊名稱就刪掉。
