<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 修正閒置時招呼內容仍被停用

Type: task
Status: resolved

使用者回報無法修改招呼內容。

## 重現與原因

`cd web && node --test tests/greeting.test.js` 在修正前有兩項原生 HTML 渲染測試失敗。預寫文案與 AI 模式都輸出 `<fieldset disabled>`。

內容編輯器以空字串表示沒有預覽／試播工作，卻直接以 `disabled || busy` 綁定原生布林屬性。Vue 將空字串視為存在的布林屬性，所以整個欄位組，包括模式、文案、Prompt 與字數都被鎖住。先前的元件測試直接呼叫模型更新，沒有檢查瀏覽器的原生停用語義，因此漏掉此錯誤。

## 修正與驗證

改用明確的 `isPreparing` 布林值控制欄位與按鈕；閒置可編輯，載入／儲存／預覽／試播期間仍正確鎖住。新增實際 Vue HTML 渲染檢查，以及預覽／試播成功和失敗後恢復編輯的操作測試。

前端完整測試為 121 項，Lint、Build 通過；後端 661 passed、3 skipped，整合稽核通過。此修正不變更招呼內容或觸發規則。
