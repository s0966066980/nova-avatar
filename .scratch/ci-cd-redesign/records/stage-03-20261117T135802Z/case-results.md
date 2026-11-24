<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Governance 逐項執行結果

本次實際 JUnit 結果與對應斷言的白話解說；不是歷史基線。

| 案例 ID | 驗證內容 | 結果 | 秒 |
| --- | --- | --- | ---: |
| `tests/test_branding_compliance.py::BrandingComplianceTests::test_commercial_review_profile_and_audits_are_present` | 商業審查設定與稽核文件存在並含必要文字，不是商業授權結論。 | passed | 0.000 |
| `tests/test_branding_compliance.py::BrandingComplianceTests::test_legal_attribution_and_restrictions_are_present` | 保留 Apache、上游與 Tencent 聲明、MuseTalk license 及 Wav2Lip 限制。 | passed | 0.000 |
| `tests/test_branding_compliance.py::BrandingComplianceTests::test_project_metadata_uses_nova_avatar` | Python／前端套件名稱、版本、維護者與 repository 等 metadata 符合既有預期。 | passed | 0.000 |
| `tests/test_branding_compliance.py::BrandingComplianceTests::test_restricted_tts_engines_are_labeled_in_catalog_ui_and_notices` | 語音元件在 catalog、UI、檔頭與 notices 等指定位置保留限制標示。 | passed | 0.001 |
| `tests/test_branding_compliance.py::BrandingComplianceTests::test_user_visible_surfaces_do_not_show_old_brand` | 指定 UI／語系／prompt 原始檔、README 標題及主頁 title 不顯示舊專案品牌。 | passed | 0.007 |
| `tests/test_branding_compliance.py::BrandingComplianceTests::test_wav2lip_is_labeled_non_commercial_in_runtime_and_ui` | Wav2Lip 明確標 Research / Non-commercial，未被宣告為 Apache-2.0。 | passed | 0.000 |
| `tests/test_dependency_lock.py::DependencyLockTests::test_lock_is_present_and_not_ignored_by_git` | lock 存在，根 gitignore 沒有單獨 uv.lock 條目；不等於完整 Git 追蹤檢查。 | passed | 0.000 |
| `tests/test_dependency_lock.py::DependencyLockTests::test_python_ci_checks_the_lock_before_installing` | 目前 workflow 先查 lock 再安裝，且保留舊 CPU 選項；新版 CUDA 落實時需同步更新此契約。 | passed | 0.002 |
| `tests/test_dependency_lock.py::DependencyLockTests::test_web_ci_audits_production_dependencies_without_blocking` | 目前前端 audit 是 production-only 且 advisory。 | passed | 0.002 |
| `tests/test_dependency_lock.py::LockCheckTests::test_dependency_change_without_lock_update_fails` | 在暫存複本改依賴卻未更新 lock 時，uv 應拒絕。 | passed | 0.130 |
| `tests/test_dependency_lock.py::LockCheckTests::test_lock_matches_pyproject` | 實際執行 uv lock --check --offline，驗證目前 lock 相容。 | passed | 0.014 |
| `tests/test_integration_check.py::IntegrationCheckTests::test_commercial_profile_uses_the_supported_avatar_path` | 商業審查設定選用 MuseTalk。 | passed | 0.002 |
| `tests/test_integration_check.py::IntegrationCheckTests::test_parse_args_defaults_to_the_offline_check` | 預設不啟用 smoke，也不指定輸出音檔。 | passed | 0.000 |
| `tests/test_integration_check.py::IntegrationCheckTests::test_required_project_contract_includes_legal_and_audit_artifacts` | 檢查器必要清單包含 NOTICE 與稽核文件。 | passed | 0.000 |
| `tests/test_integration_check.py::IntegrationCheckTests::test_runtime_module_contract_covers_selected_optional_engines` | 可選引擎模組清單遵守目前主環境／獨立環境的約定。 | passed | 0.000 |
| `tests/test_ruff_security.py::RuffSecurityGateTests::test_assert_is_allowed_only_in_tests` | 額外啟用 S101 時，src assert 被拒、tests 例外可用；一般 gate 未因此全域啟用 S101。 | passed | 0.034 |
| `tests/test_ruff_security.py::RuffSecurityGateTests::test_each_rule_rejects_a_representative_violation` | 十種選定違規範例被 Ruff 對應規則拒絕；只 lint，不執行範例。 | passed | 0.159 |
| `tests/test_ruff_security.py::RuffSecurityGateTests::test_requests_without_timeout_fails_and_with_timeout_passes` | requests 無 timeout 被拒，附 timeout 後通過。 | passed | 0.031 |
| `tests/test_ruff_security.py::RuffSecurityGateTests::test_rules_apply_to_tests_and_scripts` | 相同指定違規在 tests 與 scripts 仍被 Ruff 擋下。 | passed | 0.032 |
