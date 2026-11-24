<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Runtime 第一輪：保留失敗結果

執行狀態：failed
結果：241 passed、1 failed、0 skipped；1287 deselected，15 subtests passed。

失敗案例是 `tests/test_frontend_serving.py::test_web_logs_are_ignored_by_git`。
乾淨來源採 git archive，沒有 `.git`，所以 `git check-ignore` 回傳 128。
這是測試環境缺少必要 Git metadata；沒有因此修改產品程式或忽略該案例。

[原始日誌](runtime-tests.log)、[JUnit](runtime.xml)、[逐項 JSON](cases.json)、
[命令與退出碼](commands.json)、[manifest](manifest.json) 皆保留。

另外，第一版報告轉換器對歷史案例 ID 的假設不適用於鎖定版 pytest 的長字串
參數 ID，轉換時發生 AssertionError。已直接從本輪 JUnit 的 module/class/name
重建真實 ID 並補存報告，未修改測試或原始 XML。完整案例數仍為 242。

僅在隔離來源快照執行 `git init`，沒有 add／commit，沒有改動原專案 Git。
環境修復命令與退出碼見 [environment-repair.json](environment-repair.json)。

重驗另建紀錄：[第二輪](../stage-04-runtime-20261117T140923Z/README.md)。不得把此失敗紀錄改寫成通過。
