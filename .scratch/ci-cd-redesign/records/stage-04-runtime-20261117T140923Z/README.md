<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 第 4 階段之一：runtime 伺服器功能

執行狀態：passed（重驗 242 通過、0 失敗、0 跳過）
理解確認：pending
日期：2026-11-17；命令時間為 UTC

## 目的與來源

驗證伺服器狀態、存取權限、設定保存、資產處理與啟停流程。這是後端六個剩餘
群組中的第一組，不表示整個第 4 階段已完成。

來源 commit `b1afdce7429eb166d3d36f6e233a07a14fbc2d52`，沿用乾淨來源快照與
第 1 階段 frozen 安裝的 Python 3.11／CUDA 環境。開始前確認 CUDA build 與
GPU 可用；沒有執行模型推理或 GPU 效能驗收，也沒有採用場域秘密設定或資產。

來源、時間、檔案 hash 與結果：[manifest.json](manifest.json)。
精確命令、cwd、環境覆寫、退出碼：[commands.json](commands.json)。

## 執行方式

先以 `uv run --no-sync pytest --collect-only -q -m runtime` 列出選取案例，
再以 `uv run --no-sync pytest -v -ra --durations=0 -m runtime --junitxml=紀錄目錄/runtime.xml`
執行並保存原始日誌、逐項狀態、耗時與 JUnit。

通過條件：選取的 242 個案例全部通過，沒有 failure、error 或 skip；案例數不能
因環境問題減少。其他 1287 個案例為本輪未選取，不是跳過或通過。

## 本次實際結果

重驗：**242 passed、0 failed、0 error、0 skipped**；1287 deselected，15 subtests passed，
pytest 報告耗時 92.08 秒。子檢查不能再加成額外案例數。

第一輪與本輪未修改產品程式；只補上隔離快照的 Git metadata 這項必要前置條件。
[第一輪失敗結果](../stage-04-runtime-20261117T140638Z/README.md) 另存，沒有覆寫。

## 14 個檔案驗證了什麼

| 測試檔 | 案例 | 保護的行為 | 真實與模擬的界線 |
| --- | ---: | --- | --- |
| test_health_route.py | 5 | health JSON、readiness 欄位、GPU 警示資訊與路由註冊 | 有真 HTTP，但 ready 由測試指定，GPU 狀態查詢為替身 |
| test_route_access.py | 27 | 路由分類、登入／登出／逾時、密碼保存、跨來源及來源偽造防護 | 真 loopback HTTP、雜湊與暫存檔；LAN remote 模擬，未測真 TLS 或瀏覽器 |
| test_frontend_serving.py | 7 | 只服務 dist、缺 dist 拒啟、禁止讀原始碼／設定／日誌、Git ignore | HTTP 使用簡單 HTML fixture；Vite 案例只查設定文字，未 build |
| test_runtime_settings.py | 46 | ID 防路徑穿越、原子保存、設定驗證、切換與預覽後提交 | 真暫存檔，模型／ASR 暖機與預覽多為 mock，不測 CUDA 推理 |
| test_deferred_settings.py | 5 | 多場連線下延後套用、重載、失敗保留重試與競速 | 真 queue 檔；session／apply 是替身，重載不是真後端重啟 |
| test_event_loop_blocking.py | 21 | 音訊限制、拒絕危險 playlist、重工作不擋 health、錄影暫存清理 | 真音訊解碼與 loopback HTTP；ASR、錄影 pipe／ffmpeg 子程序為替身 |
| test_avatar_import.py | 15 | 使用中不覆寫、失敗保留原檔、成功先回收、上傳限制、錯誤不洩漏路徑 | 真暫存檔案操作；輸入為 fake video，建模／影格提取為替身 |
| test_avatar_profiles.py | 26 | 設定檔遷移、角色資料隔離、revision 防舊編輯覆寫與回覆規則 | 真暫存 YAML store；無真 LLM、TTS 或 RAG |
| test_role_composition.py | 23 | 組合遷移備份、最多五位專門數位人、衝突與轉場引用清理 | 真暫存 store／HTTP，角色媒體為替身，未測 GPU 角色切換 |
| test_kiosk_launcher.py | 10 | 舞台 URL、麥克風 origin 限制、瀏覽器 profile、dry run | 真腳本／JSON；browser 用 true，不開真瀏覽器或收音 |
| test_optional_runtime_extras.py | 2 | MuseTalk extra 宣告與 pkg_resources 可載入 | 一項文字檢查、一項真 import；沒有載入完整 MuseTalk |
| test_pinned_resources.py | 19 | 安裝器／模型 checksum、固定來源、映像 digest、憑證檔權限 | 真 hash／tar／複製；下載、Ollama、憑證工具為替身，不改系統信任庫 |
| test_startup_scripts.py | 30 | 啟動順序、設定路徑、服務失敗恢復、辨識自身程序、先 SIGTERM 後 kill | 真 bash／子程序／signal；Docker、sudo、uv、npm、網路與程序查找用測試命令替身 |
| test_server_shutdown.py | 6 | SIGTERM／SIGINT、重複訊號、session thread 清理與超時保底 | 真 Python 子程序、thread、aiohttp；app/session 是縮小 fixture，無模型與 WebRTC |
| 合計 | 242 | 伺服器操作規則與生命週期的回歸保護 | 不是場域全系統驗收 |

## 存取規則不能簡化成什麼

- 匿名 LAN 對指定舞台 API 被拒，匿名 loopback 可到 handler；但測試也明確允許
  已登入管理者從 LAN 到 `/api/stage`，不能說所有 LAN 的舞台 API 都被禁止。
- stage.html 靜態頁可由 LAN 下載；邊界在 API 與 session 權限，不是隱藏 HTML。
- 某些案例只證明 access guard 放行，後續 handler 可以因缺 session 回 404；
  不能寫成該 API 業務功能已成功完成。
- CookieJar 在測試中允許 HTTP 使用 Secure cookie；沒有實測現場 HTTPS。

## 環境副作用與限制

startup／shutdown 確實會建立並送 signal 給測試自己的子程序，沒有啟停場域
後端、Docker 或執行真 sudo。PATH 裡的替身只宣告 fixture listener。

多數寫檔在 pytest 暫存目錄；kiosk 短暫在隔離快照 root 建測試 YAML，結束後清除。
shutdown fixture 的 `/tmp/nova-shutdown-*` 小量腳本／marker／log 可能留存。
本組依賴 Linux 的 bash、/proc、signal 與 process group，不是跨平台純單元測試。

名稱提到暖機、GPU、真實前端建置或開 Docker，也不代表真的執行那些動作。
既有 Wav2Lip／CosyVoice 等 fixture 名稱僅驗證資料處理與程序辨識，不表示推薦
該引擎，也不改變其授權限制。RAGFlow 的既有 CPU image 契約屬獨立整合，不改變
本版 Python 驗證環境的 CUDA-only 決定。

## 失敗與重驗

第一輪為 241 passed、1 failed，原因是 git archive 缺 Git metadata，導致
`test_web_logs_are_ignored_by_git` 的真 `git check-ignore` 回傳 128。
只在隔離快照補 `git init`，沒有 add／commit 或產品程式修改，再另建本次重驗。

報告轉換器也曾因 pytest 版本不同的長字串參數 ID 假設而失敗；已改依本輪 XML
保留實際 ID，未修改測試或原始 JUnit。逐項清單可能因此與歷史 ID 字串不同，
不應靠較舊的 ID 格式判定漏跑。

## 證據與下一步

逐項結果：[case-results.md](case-results.md)、[cases.json](cases.json)。
原始日誌：[runtime-tests.log](runtime-tests.log)；JUnit：[runtime.xml](runtime.xml)。
證據 hash：[evidence-sha256.json](evidence-sha256.json)。

完成後等待使用者理解確認，再進 speech 語音群組（盤點 279 案例），其他後端
群組仍分次執行與解說。不會因本組通過直接進部署。
