<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 逐檔測試速查表

來源與限制見 [測試範圍盤點](../test-inventory.md)。數量是本次收集／歷史名稱對照，不是重新執行的結果。

## Python

| 領域 | 測試檔 | 案例數 |
| --- | --- | ---: |
| `avatar` | [tests/test_avatar_safe_loading.py](../../../tests/test_avatar_safe_loading.py) | 20 |
| `avatar` | [tests/test_avatar_transition.py](../../../tests/test_avatar_transition.py) | 17 |
| `avatar` | [tests/test_mouth_continuity.py](../../../tests/test_mouth_continuity.py) | 8 |
| `avatar` | [tests/test_mouth_quality.py](../../../tests/test_mouth_quality.py) | 12 |
| `avatar` | [tests/test_musetalk_acceleration.py](../../../tests/test_musetalk_acceleration.py) | 15 |
| `avatar` | [tests/test_musetalk_preprocessing.py](../../../tests/test_musetalk_preprocessing.py) | 1 |
| `avatar` | [tests/test_role_media.py](../../../tests/test_role_media.py) | 9 |
| `avatar` | [tests/test_scene_background.py](../../../tests/test_scene_background.py) | 17 |
| `conversation` | [tests/test_answer_board.py](../../../tests/test_answer_board.py) | 5 |
| `conversation` | [tests/test_any_to_any_handoff.py](../../../tests/test_any_to_any_handoff.py) | 15 |
| `conversation` | [tests/test_auto_response_protocol.py](../../../tests/test_auto_response_protocol.py) | 13 |
| `conversation` | [tests/test_concurrent_routing.py](../../../tests/test_concurrent_routing.py) | 21 |
| `conversation` | [tests/test_conversation_attachments.py](../../../tests/test_conversation_attachments.py) | 14 |
| `conversation` | [tests/test_conversation_settings.py](../../../tests/test_conversation_settings.py) | 34 |
| `conversation` | [tests/test_cwa_weather.py](../../../tests/test_cwa_weather.py) | 12 |
| `conversation` | [tests/test_first_audio_latency.py](../../../tests/test_first_audio_latency.py) | 44 |
| `conversation` | [tests/test_first_fragment_exception.py](../../../tests/test_first_fragment_exception.py) | 13 |
| `conversation` | [tests/test_handoff_dry_run.py](../../../tests/test_handoff_dry_run.py) | 13 |
| `conversation` | [tests/test_idle_greetings.py](../../../tests/test_idle_greetings.py) | 44 |
| `conversation` | [tests/test_live_llm_board_contract.py](../../../tests/test_live_llm_board_contract.py) | 2 |
| `conversation` | [tests/test_media_fencing.py](../../../tests/test_media_fencing.py) | 21 |
| `conversation` | [tests/test_n_way_routing.py](../../../tests/test_n_way_routing.py) | 21 |
| `conversation` | [tests/test_pc_conversations.py](../../../tests/test_pc_conversations.py) | 21 |
| `conversation` | [tests/test_playback_commit.py](../../../tests/test_playback_commit.py) | 23 |
| `conversation` | [tests/test_realtime_avatar.py](../../../tests/test_realtime_avatar.py) | 20 |
| `conversation` | [tests/test_render_stop.py](../../../tests/test_render_stop.py) | 7 |
| `conversation` | [tests/test_reply_latency.py](../../../tests/test_reply_latency.py) | 18 |
| `conversation` | [tests/test_reply_streaming.py](../../../tests/test_reply_streaming.py) | 44 |
| `conversation` | [tests/test_response_protocol.py](../../../tests/test_response_protocol.py) | 21 |
| `conversation` | [tests/test_reverse_role_handoff.py](../../../tests/test_reverse_role_handoff.py) | 19 |
| `conversation` | [tests/test_role_coordinator.py](../../../tests/test_role_coordinator.py) | 32 |
| `conversation` | [tests/test_speech_timing.py](../../../tests/test_speech_timing.py) | 45 |
| `conversation` | [tests/test_stage_idle_reset.py](../../../tests/test_stage_idle_reset.py) | 8 |
| `conversation` | [tests/test_stage_presentation.py](../../../tests/test_stage_presentation.py) | 6 |
| `conversation` | [tests/test_turn_lifecycle.py](../../../tests/test_turn_lifecycle.py) | 13 |
| `conversation` | [tests/test_voice_session.py](../../../tests/test_voice_session.py) | 35 |
| `conversation` | [tests/test_voice_test_history.py](../../../tests/test_voice_test_history.py) | 10 |
| `conversation` | [tests/test_weather_context.py](../../../tests/test_weather_context.py) | 5 |
| `conversation` | [tests/test_weather_keywords.py](../../../tests/test_weather_keywords.py) | 63 |
| `conversation` | [tests/test_web_search.py](../../../tests/test_web_search.py) | 60 |
| `conversation` | [tests/test_webrtc_lifecycle.py](../../../tests/test_webrtc_lifecycle.py) | 18 |
| `governance` | [tests/test_branding_compliance.py](../../../tests/test_branding_compliance.py) | 6 |
| `governance` | [tests/test_dependency_lock.py](../../../tests/test_dependency_lock.py) | 5 |
| `governance` | [tests/test_integration_check.py](../../../tests/test_integration_check.py) | 4 |
| `governance` | [tests/test_ruff_security.py](../../../tests/test_ruff_security.py) | 4 |
| `llm` | [tests/test_assistant_profile.py](../../../tests/test_assistant_profile.py) | 4 |
| `llm` | [tests/test_default_llm_endpoint.py](../../../tests/test_default_llm_endpoint.py) | 6 |
| `llm` | [tests/test_editable_llm_rules.py](../../../tests/test_editable_llm_rules.py) | 6 |
| `llm` | [tests/test_first_sentence_rule.py](../../../tests/test_first_sentence_rule.py) | 10 |
| `llm` | [tests/test_gemma_e2b.py](../../../tests/test_gemma_e2b.py) | 7 |
| `llm` | [tests/test_llamacpp.py](../../../tests/test_llamacpp.py) | 23 |
| `llm` | [tests/test_llm_endpoints.py](../../../tests/test_llm_endpoints.py) | 25 |
| `llm` | [tests/test_llm_quality_eval.py](../../../tests/test_llm_quality_eval.py) | 20 |
| `llm` | tests/test_llm_router.py（已退休；此列僅為歷史盤點） | 11 |
| `llm` | [tests/test_llm_text_normalizer.py](../../../tests/test_llm_text_normalizer.py) | 5 |
| `ragflow` | [tests/test_ragflow_integration.py](../../../tests/test_ragflow_integration.py) | 22 |
| `ragflow` | [tests/test_ragflow_llamacpp_embedding.py](../../../tests/test_ragflow_llamacpp_embedding.py) | 11 |
| `runtime` | [tests/test_avatar_import.py](../../../tests/test_avatar_import.py) | 15 |
| `runtime` | [tests/test_avatar_profiles.py](../../../tests/test_avatar_profiles.py) | 26 |
| `runtime` | [tests/test_deferred_settings.py](../../../tests/test_deferred_settings.py) | 5 |
| `runtime` | [tests/test_event_loop_blocking.py](../../../tests/test_event_loop_blocking.py) | 21 |
| `runtime` | [tests/test_frontend_serving.py](../../../tests/test_frontend_serving.py) | 7 |
| `runtime` | [tests/test_health_route.py](../../../tests/test_health_route.py) | 5 |
| `runtime` | [tests/test_kiosk_launcher.py](../../../tests/test_kiosk_launcher.py) | 10 |
| `runtime` | [tests/test_optional_runtime_extras.py](../../../tests/test_optional_runtime_extras.py) | 2 |
| `runtime` | [tests/test_pinned_resources.py](../../../tests/test_pinned_resources.py) | 19 |
| `runtime` | [tests/test_role_composition.py](../../../tests/test_role_composition.py) | 23 |
| `runtime` | [tests/test_route_access.py](../../../tests/test_route_access.py) | 27 |
| `runtime` | [tests/test_runtime_settings.py](../../../tests/test_runtime_settings.py) | 46 |
| `runtime` | [tests/test_server_shutdown.py](../../../tests/test_server_shutdown.py) | 6 |
| `runtime` | [tests/test_startup_scripts.py](../../../tests/test_startup_scripts.py) | 30 |
| `speech` | [tests/test_asr_comparison.py](../../../tests/test_asr_comparison.py) | 11 |
| `speech` | [tests/test_breezyvoice_tts.py](../../../tests/test_breezyvoice_tts.py) | 22 |
| `speech` | [tests/test_default_voice.py](../../../tests/test_default_voice.py) | 9 |
| `speech` | [tests/test_edge_connection.py](../../../tests/test_edge_connection.py) | 14 |
| `speech` | [tests/test_edge_endpoint.py](../../../tests/test_edge_endpoint.py) | 6 |
| `speech` | [tests/test_edge_resilience.py](../../../tests/test_edge_resilience.py) | 2 |
| `speech` | [tests/test_edge_tts_worker.py](../../../tests/test_edge_tts_worker.py) | 22 |
| `speech` | [tests/test_funasr.py](../../../tests/test_funasr.py) | 37 |
| `speech` | [tests/test_profile_voice_preview.py](../../../tests/test_profile_voice_preview.py) | 13 |
| `speech` | [tests/test_tts_bakeoff.py](../../../tests/test_tts_bakeoff.py) | 21 |
| `speech` | [tests/test_tts_engine_cleanup.py](../../../tests/test_tts_engine_cleanup.py) | 18 |
| `speech` | [tests/test_vad.py](../../../tests/test_vad.py) | 43 |
| `speech` | [tests/test_voice_library.py](../../../tests/test_voice_library.py) | 48 |
| `speech` | [tests/test_whisper_asr.py](../../../tests/test_whisper_asr.py) | 13 |

## 前端

功能組別是待納入新流程的紀錄分組，不是現有 npm script。

| 建議分組 | 測試檔 | 案例數 |
| --- | --- | ---: |
| `access-security-delivery` | [web/tests/admin-session.test.js](../../../web/tests/admin-session.test.js) | 6 |
| `access-security-delivery` | [web/tests/backend-health.test.js](../../../web/tests/backend-health.test.js) | 2 |
| `access-security-delivery` | [web/tests/markdown.test.js](../../../web/tests/markdown.test.js) | 5 |
| `access-security-delivery` | [web/tests/offline-assets.test.js](../../../web/tests/offline-assets.test.js) | 4 |
| `access-security-delivery` | [web/tests/page-routing.test.js](../../../web/tests/page-routing.test.js) | 8 |
| `access-security-delivery` | [web/tests/storageKeys.test.js](../../../web/tests/storageKeys.test.js) | 2 |
| `access-security-delivery` | [web/tests/tts-license-labels.test.js](../../../web/tests/tts-license-labels.test.js) | 2 |
| `conversation-state` | [web/tests/console-shortcuts.test.js](../../../web/tests/console-shortcuts.test.js) | 15 |
| `conversation-state` | [web/tests/console-turn-commit.test.js](../../../web/tests/console-turn-commit.test.js) | 3 |
| `conversation-state` | [web/tests/consoleBoardState.test.js](../../../web/tests/consoleBoardState.test.js) | 2 |
| `conversation-state` | [web/tests/conversationAttachments.test.js](../../../web/tests/conversationAttachments.test.js) | 5 |
| `conversation-state` | [web/tests/conversationComposer.test.js](../../../web/tests/conversationComposer.test.js) | 19 |
| `conversation-state` | [web/tests/conversationPanel.test.js](../../../web/tests/conversationPanel.test.js) | 3 |
| `conversation-state` | [web/tests/presentation.test.js](../../../web/tests/presentation.test.js) | 1 |
| `management-configuration` | [web/tests/defaultPromptSettings.test.js](../../../web/tests/defaultPromptSettings.test.js) | 33 |
| `management-configuration` | [web/tests/greeting.test.js](../../../web/tests/greeting.test.js) | 10 |
| `management-configuration` | [web/tests/idle-greeting-settings.test.js](../../../web/tests/idle-greeting-settings.test.js) | 4 |
| `management-configuration` | [web/tests/llm-endpoint-selection.test.js](../../../web/tests/llm-endpoint-selection.test.js) | 2 |
| `management-configuration` | [web/tests/profile-settings.test.js](../../../web/tests/profile-settings.test.js) | 3 |
| `management-configuration` | [web/tests/rag-scope.test.js](../../../web/tests/rag-scope.test.js) | 2 |
| `management-configuration` | [web/tests/ragflow-settings.test.js](../../../web/tests/ragflow-settings.test.js) | 2 |
| `management-configuration` | [web/tests/role-composition-model.test.js](../../../web/tests/role-composition-model.test.js) | 6 |
| `management-configuration` | [web/tests/role-composition.test.js](../../../web/tests/role-composition.test.js) | 9 |
| `management-configuration` | [web/tests/scene-preview.test.js](../../../web/tests/scene-preview.test.js) | 4 |
| `management-configuration` | [web/tests/settings-organization.test.js](../../../web/tests/settings-organization.test.js) | 6 |
| `management-configuration` | [web/tests/sttPrewarmProgress.test.js](../../../web/tests/sttPrewarmProgress.test.js) | 3 |
| `management-configuration` | [web/tests/system-status.test.js](../../../web/tests/system-status.test.js) | 5 |
| `management-configuration` | [web/tests/voice-selection.test.js](../../../web/tests/voice-selection.test.js) | 8 |
| `management-configuration` | [web/tests/voice-test-panel.test.js](../../../web/tests/voice-test-panel.test.js) | 4 |
| `management-configuration` | [web/tests/web-search.test.js](../../../web/tests/web-search.test.js) | 4 |
| `stage-connection-playback` | [web/tests/role-state.test.js](../../../web/tests/role-state.test.js) | 3 |
| `stage-connection-playback` | [web/tests/stage-board-layout.test.js](../../../web/tests/stage-board-layout.test.js) | 5 |
| `stage-connection-playback` | [web/tests/stage-caption-view.test.js](../../../web/tests/stage-caption-view.test.js) | 2 |
| `stage-connection-playback` | [web/tests/stage-caption-window.test.js](../../../web/tests/stage-caption-window.test.js) | 4 |
| `stage-connection-playback` | [web/tests/stage-connection.test.js](../../../web/tests/stage-connection.test.js) | 6 |
| `stage-connection-playback` | [web/tests/stage-error-message.test.js](../../../web/tests/stage-error-message.test.js) | 5 |
| `stage-connection-playback` | [web/tests/stage-kiosk.test.js](../../../web/tests/stage-kiosk.test.js) | 2 |
| `stage-connection-playback` | [web/tests/stage-microphone.test.js](../../../web/tests/stage-microphone.test.js) | 14 |
| `stage-connection-playback` | [web/tests/stage-reply-lifecycle.test.js](../../../web/tests/stage-reply-lifecycle.test.js) | 3 |
| `stage-connection-playback` | [web/tests/stage-resilience.test.js](../../../web/tests/stage-resilience.test.js) | 13 |
| `stage-connection-playback` | [web/tests/useSpeechRecognition.test.js](../../../web/tests/useSpeechRecognition.test.js) | 2 |
| `stage-connection-playback` | [web/tests/useWebRTC.test.js](../../../web/tests/useWebRTC.test.js) | 5 |
| `visual-accessibility` | [web/tests/console-theme-tokens.test.js](../../../web/tests/console-theme-tokens.test.js) | 5 |
| `visual-accessibility` | [web/tests/console-theme.test.js](../../../web/tests/console-theme.test.js) | 5 |
| `visual-accessibility` | [web/tests/console-visual.test.js](../../../web/tests/console-visual.test.js) | 4 |
| `visual-accessibility` | [web/tests/settings-layout.test.js](../../../web/tests/settings-layout.test.js) | 1 |
