<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# LLM 逐項結果

本次實際 JUnit 狀態；跳過與通過分別列出。

| 案例 ID | 狀態 | 秒 | 理由 |
| --- | --- | ---: | --- |
| `tests/test_assistant_profile.py::AssistantProfileTests::test_profile_is_the_prompt_source_and_protocol_has_no_identity` | passed | 0.000 |  |
| `tests/test_assistant_profile.py::AssistantProfileTests::test_profile_persists_in_snapshot_and_legacy_value_is_read_only_migration` | passed | 0.001 |  |
| `tests/test_assistant_profile.py::AssistantProfileTests::test_profile_round_trips_through_runtime_overrides` | passed | 0.005 |  |
| `tests/test_assistant_profile.py::AssistantProfileTests::test_profile_update_resets_sessions_but_length_update_does_not` | passed | 0.001 |  |
| `tests/test_default_llm_endpoint.py::test_shipped_config_selects_the_managed_llama_server` | passed | 0.004 |  |
| `tests/test_default_llm_endpoint.py::test_ollama_stays_an_explicit_opt_in_endpoint` | passed | 0.004 |  |
| `tests/test_default_llm_endpoint.py::test_saved_ollama_selection_still_uses_ollama` | passed | 0.004 |  |
| `tests/test_default_llm_endpoint.py::test_pre_allowlist_override_naming_only_the_ollama_url_still_uses_ollama` | passed | 0.004 |  |
| `tests/test_default_llm_endpoint.py::test_legacy_single_endpoint_ollama_config_is_unchanged` | passed | 0.002 |  |
| `tests/test_default_llm_endpoint.py::test_docs_explain_how_to_disable_the_default_ollama` | passed | 0.000 |  |
| `tests/test_editable_llm_rules.py::EditableRuleTests::test_apply_persists_and_increments_revision` | passed | 0.004 |  |
| `tests/test_editable_llm_rules.py::EditableRuleTests::test_conflict_keeps_current_rules` | passed | 0.000 |  |
| `tests/test_editable_llm_rules.py::EditableRuleTests::test_default_activation_uses_board_for_steps_and_processes` | passed | 0.000 |  |
| `tests/test_editable_llm_rules.py::EditableRuleTests::test_defaults_fill_empty_dataclass` | passed | 0.000 |  |
| `tests/test_editable_llm_rules.py::EditableRuleTests::test_snapshot_and_defaults_are_exposed_separately` | passed | 0.000 |  |
| `tests/test_editable_llm_rules.py::EditableRuleTests::test_validation_rejects_blank_and_overlong_content` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_the_rule_asks_for_a_complete_sentence_of_at_most_fifteen_characters` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_simple_and_auto_replies_carry_the_rule[auto]` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_simple_and_auto_replies_carry_the_rule[simple]` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_simple_and_auto_replies_carry_the_rule[None]` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_board_speech_is_exempt_from_the_rule[zh-TW]` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_board_speech_is_exempt_from_the_rule[en-US]` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_saved_custom_rules_cannot_drop_it_and_it_follows_them` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_the_board_speech_example_is_not_shortened_to_the_rule` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_the_default_speech_rule_does_not_ask_for_a_longer_first_sentence` | passed | 0.000 |  |
| `tests/test_first_sentence_rule.py::test_english_sessions_get_the_limit_in_words` | passed | 0.000 |  |
| `tests/test_gemma_e2b.py::test_e2b_answer_turns_thinking_off_and_uses_the_plain_reply_grammar` | passed | 0.003 |  |
| `tests/test_gemma_e2b.py::test_lfm_keeps_its_bounded_thinking_envelope` | passed | 0.001 |  |
| `tests/test_gemma_e2b.py::test_local_routing_is_constrained_to_the_route_schema_without_thinking` | passed | 0.003 |  |
| `tests/test_gemma_e2b.py::test_routing_reads_a_decision_wrapped_in_a_fence_or_thought_channel` | passed | 0.009 |  |
| `tests/test_gemma_e2b.py::test_routing_treats_null_fields_as_empty` | passed | 0.003 |  |
| `tests/test_gemma_e2b.py::test_routing_still_rejects_text_that_is_not_a_decision` | passed | 0.011 |  |
| `tests/test_gemma_e2b.py::test_other_providers_keep_plain_json_mode` | passed | 0.003 |  |
| `tests/test_llamacpp.py::CudaLibraryDiscoveryTests::test_build_server_env_puts_cuda_dir_on_ld_path` | passed | 0.001 |  |
| `tests/test_llamacpp.py::CudaLibraryDiscoveryTests::test_includes_directory_that_has_libcudart` | passed | 0.002 |  |
| `tests/test_llamacpp.py::CudaLibraryDiscoveryTests::test_skips_directory_without_cuda_runtime` | passed | 0.001 |  |
| `tests/test_llamacpp.py::GpuLayerPlanningTests::test_cpu_only_when_no_free_vram` | passed | 0.000 |  |
| `tests/test_llamacpp.py::GpuLayerPlanningTests::test_external_server_offloading_all_layers_uses_the_same_sentinel` | passed | 0.000 |  |
| `tests/test_llamacpp.py::GpuLayerPlanningTests::test_fits_all_layers_when_vram_is_enough` | passed | 0.000 |  |
| `tests/test_llamacpp.py::GpuLayerPlanningTests::test_partial_offload_when_vram_is_tight` | passed | 0.000 |  |
| `tests/test_llamacpp.py::GpuLayerPlanningTests::test_reads_qwen_block_count` | skipped | 0.000 | Qwen3.8-27B-Q4_K_M.gguf is not installed |
| `tests/test_llamacpp.py::StopLlamaOnPortTests::test_refuses_to_kill_unrelated_process` | passed | 0.001 |  |
| `tests/test_llamacpp.py::StopLlamaOnPortTests::test_stops_leftover_llama_server` | passed | 0.001 |  |
| `tests/test_llamacpp.py::ShutdownOwnedServerTests::test_shutdown_does_not_discover_or_kill_external_server` | passed | 0.000 |  |
| `tests/test_llamacpp.py::ShutdownOwnedServerTests::test_shutdown_stops_only_owned_process_and_is_idempotent` | passed | 0.000 |  |
| `tests/test_llamacpp.py::LlamaServerLaunchEnvTests::test_llama_server_loads_with_discovered_cuda_libs` | passed | 0.227 |  |
| `tests/test_llamacpp.py::ModelInfoCacheTests::test_loading_another_model_replaces_the_cached_context_size` | passed | 0.002 |  |
| `tests/test_llamacpp.py::FullGpuStartupTests::test_cpu_only_build_is_refused_by_default` | passed | 0.001 |  |
| `tests/test_llamacpp.py::FullGpuStartupTests::test_each_launch_is_marked_in_the_shared_log` | passed | 0.002 |  |
| `tests/test_llamacpp.py::FullGpuStartupTests::test_explicit_partial_offload_launches_and_reports_not_full` | passed | 0.002 |  |
| `tests/test_llamacpp.py::FullGpuStartupTests::test_full_gpu_launch_uses_all_layers` | passed | 0.001 |  |
| `tests/test_llamacpp.py::FullGpuStartupTests::test_gemma_e2b_launches_without_thinking_and_with_its_vision_projector` | passed | 0.002 |  |
| `tests/test_llamacpp.py::FullGpuStartupTests::test_refuses_partial_offload_and_names_vram_need_and_holders` | passed | 0.001 |  |
| `tests/test_llamacpp.py::FullGpuStartupTests::test_server_that_finds_no_usable_gpu_is_stopped` | passed | 0.001 |  |
| `tests/test_llamacpp.py::StartupOrderTests::test_gpu_shortfall_keeps_the_console_reachable` | passed | 0.002 |  |
| `tests/test_llamacpp.py::StartupOrderTests::test_llama_server_starts_before_the_avatar_model` | passed | 0.001 |  |
| `tests/test_llm_endpoints.py::test_existing_install_without_endpoints_keeps_its_current_server` | passed | 0.000 |  |
| `tests/test_llm_endpoints.py::test_invalid_endpoint_definitions_are_rejected[bad0]` | passed | 0.000 |  |
| `tests/test_llm_endpoints.py::test_invalid_endpoint_definitions_are_rejected[bad1]` | passed | 0.000 |  |
| `tests/test_llm_endpoints.py::test_invalid_endpoint_definitions_are_rejected[bad2]` | passed | 0.000 |  |
| `tests/test_llm_endpoints.py::test_invalid_endpoint_definitions_are_rejected[bad3]` | passed | 0.000 |  |
| `tests/test_llm_endpoints.py::test_invalid_endpoint_definitions_are_rejected[bad4]` | passed | 0.000 |  |
| `tests/test_llm_endpoints.py::test_provider_is_explicit_and_not_guessed_from_the_port` | passed | 0.000 |  |
| `tests/test_llm_endpoints.py::test_profile_uses_named_endpoint_and_its_own_key_only` | passed | 0.004 |  |
| `tests/test_llm_endpoints.py::test_store_rejects_profiles_that_do_not_name_a_configured_endpoint[<lambda>0]` | passed | 0.006 |  |
| `tests/test_llm_endpoints.py::test_store_rejects_profiles_that_do_not_name_a_configured_endpoint[<lambda>1]` | passed | 0.007 |  |
| `tests/test_llm_endpoints.py::test_store_rejects_profiles_that_do_not_name_a_configured_endpoint[<lambda>2]` | passed | 0.006 |  |
| `tests/test_llm_endpoints.py::test_store_rejects_profiles_that_do_not_name_a_configured_endpoint[<lambda>3]` | passed | 0.007 |  |
| `tests/test_llm_endpoints.py::test_legacy_profiles_map_to_the_endpoint_with_the_same_url` | passed | 0.010 |  |
| `tests/test_llm_endpoints.py::test_legacy_profile_with_unlisted_url_is_refused_on_apply` | passed | 0.009 |  |
| `tests/test_llm_endpoints.py::test_greeting_preview_cannot_send_the_key_to_an_unlisted_host[llm_change0]` | passed | 0.063 |  |
| `tests/test_llm_endpoints.py::test_greeting_preview_cannot_send_the_key_to_an_unlisted_host[llm_change1]` | passed | 0.057 |  |
| `tests/test_llm_endpoints.py::test_greeting_preview_rejects_a_legacy_external_base_url` | passed | 0.061 |  |
| `tests/test_llm_endpoints.py::test_greeting_preview_reaches_only_the_named_endpoint` | passed | 0.065 |  |
| `tests/test_llm_endpoints.py::test_validate_profile_never_returns_a_url` | passed | 0.001 |  |
| `tests/test_llm_endpoints.py::test_model_catalog_lists_endpoints_without_keys` | passed | 0.001 |  |
| `tests/test_llm_endpoints.py::test_global_switch_accepts_only_configured_endpoints` | passed | 0.001 |  |
| `tests/test_llm_endpoints.py::test_loaded_config_freezes_endpoints_and_persists_only_the_selection` | passed | 0.007 |  |
| `tests/test_llm_endpoints.py::test_default_config_offers_both_local_servers` | passed | 0.005 |  |
| `tests/test_llm_endpoints.py::test_switching_away_from_ollama_drops_ollama_only_request_fields[remote]` | passed | 0.001 |  |
| `tests/test_llm_endpoints.py::test_switching_away_from_ollama_drops_ollama_only_request_fields[local]` | passed | 0.001 |  |
| `tests/test_llm_quality_eval.py::test_a_complete_reply_passes_every_check` | passed | 0.002 |  |
| `tests/test_llm_quality_eval.py::test_board_reply_is_parsed_and_board_text_is_checked_for_simplified_characters` | passed | 0.000 |  |
| `tests/test_llm_quality_eval.py::test_truncated_or_malformed_replies_fail_the_format_check` | passed | 0.000 |  |
| `tests/test_llm_quality_eval.py::test_spoken_length_counts_visible_characters_against_the_cap` | passed | 0.000 |  |
| `tests/test_llm_quality_eval.py::test_traditional_text_with_shared_characters_is_not_flagged_as_simplified` | passed | 0.000 |  |
| `tests/test_llm_quality_eval.py::test_run_asks_every_question_through_the_production_routing_and_answer_path` | passed | 1.053 |  |
| `tests/test_llm_quality_eval.py::test_report_puts_both_models_side_by_side_and_flags_weaker_routing` | passed | 0.633 |  |
| `tests/test_llm_quality_eval.py::test_report_does_not_flag_equal_routing` | passed | 0.641 |  |
| `tests/test_llm_quality_eval.py::test_command_line_runs_a_server_and_writes_the_report` | passed | 0.763 |  |
| `tests/test_llm_quality_eval.py::test_wrong_mode_and_missing_terms_are_reported` | passed | 0.001 |  |
| `tests/test_llm_quality_eval.py::test_fixed_set_has_thirty_questions_across_the_four_categories` | passed | 0.001 |  |
| `tests/test_llm_quality_eval.py::test_first_sentence_must_be_complete_and_at_most_fifteen_characters` | passed | 0.001 |  |
| `tests/test_llm_quality_eval.py::test_english_first_sentence_counts_words` | passed | 0.001 |  |
| `tests/test_llm_quality_eval.py::test_first_fragment_replays_the_stream_through_the_production_fragmenter` | passed | 0.001 |  |
| `tests/test_llm_quality_eval.py::test_first_fragment_comparison_replays_chunks_or_interpolates_older_runs` | passed | 0.000 |  |
| `tests/test_llm_quality_eval.py::test_runs_record_first_sentence_and_first_fragment_for_both_reports` | passed | 0.633 |  |
| `tests/test_llm_quality_eval.py::test_routing_set_covers_every_member_every_direct_pair_followups_and_mixed_topics` | passed | 0.002 |  |
| `tests/test_llm_quality_eval.py::test_routing_set_is_asked_among_its_own_five_roles_without_answers` | passed | 0.559 |  |
| `tests/test_llm_quality_eval.py::test_routing_report_summarises_one_run_per_category_with_every_miss` | passed | 0.558 |  |
| `tests/test_llm_quality_eval.py::test_question_sets_reject_unknown_roles_and_targets` | passed | 0.001 |  |
| `tests/test_llm_router.py::RuleRouterTests::test_board_queries` | passed | 0.002 |  |
| `tests/test_llm_router.py::RuleRouterTests::test_edge_cases` | passed | 0.000 |  |
| `tests/test_llm_router.py::RuleRouterTests::test_performance_sub_two_milliseconds` | passed | 0.001 |  |
| `tests/test_llm_router.py::RuleRouterTests::test_simple_queries` | passed | 0.001 |  |
| `tests/test_llm_router.py::LLMFallbackClassifierTests::test_classify_board_token` | passed | 0.001 |  |
| `tests/test_llm_router.py::LLMFallbackClassifierTests::test_classify_exception_falls_back_to_simple` | passed | 0.001 |  |
| `tests/test_llm_router.py::LLMFallbackClassifierTests::test_classify_simple_token` | passed | 0.001 |  |
| `tests/test_llm_router.py::LLMFallbackClassifierTests::test_classify_unrecognized_output_falls_back_to_simple` | passed | 0.001 |  |
| `tests/test_llm_router.py::ReplyRouterOrchestrationTests::test_ambiguous_triggers_llm_fallback` | passed | 0.001 |  |
| `tests/test_llm_router.py::ReplyRouterOrchestrationTests::test_disabled_router_falls_back_to_simple` | passed | 0.000 |  |
| `tests/test_llm_router.py::ReplyRouterOrchestrationTests::test_forced_mode` | passed | 0.000 |  |
| `tests/test_llm_text_normalizer.py::TextNormalizerTests::test_disabled_or_other_locale_is_unchanged` | passed | 0.000 |  |
| `tests/test_llm_text_normalizer.py::TextNormalizerTests::test_identity_guard_only_handles_self_identification` | passed | 0.000 |  |
| `tests/test_llm_text_normalizer.py::TextNormalizerTests::test_response_pipeline_normalizes_speech_board_and_history` | passed | 0.002 |  |
| `tests/test_llm_text_normalizer.py::TextNormalizerTests::test_unsolicited_identity_is_removed_but_identity_answer_is_preserved` | passed | 0.001 |  |
| `tests/test_llm_text_normalizer.py::TextNormalizerTests::test_zh_tw_conversion_preserves_english_and_code` | passed | 0.000 |  |
