# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Central pytest classification for Nova Avatar's product-area suites."""

from __future__ import annotations

from collections.abc import Iterable

import pytest


AREA_BY_FILE = {
    "test_conversation_attachments.py": "conversation",
    "test_conversation_settings.py": "conversation",
    "test_pc_conversations.py": "conversation",
    "test_avatar_import.py": "runtime",
    "test_avatar_profiles.py": "runtime",
    "test_cwa_weather.py": "conversation",
    "test_weather_context.py": "conversation",
    "test_role_media.py": "avatar",
    "test_role_coordinator.py": "conversation",
    "test_reverse_role_handoff.py": "conversation",
    "test_answer_board.py": "conversation",
    "test_assistant_profile.py": "llm",
    "test_auto_response_protocol.py": "conversation",
    "test_avatar_transition.py": "avatar",
    "test_branding_compliance.py": "governance",
    "test_cosyvoice_tts.py": "speech",
    "test_edge_connection.py": "speech",
    "test_edge_endpoint.py": "speech",
    "test_edge_resilience.py": "speech",
    "test_edge_tts_worker.py": "speech",
    "test_event_loop_blocking.py": "runtime",
    "test_editable_llm_rules.py": "llm",
    "test_frontend_serving.py": "runtime",
    "test_funasr.py": "speech",
    "test_health_route.py": "runtime",
    "test_integration_check.py": "governance",
    "test_kiosk_launcher.py": "runtime",
    "test_live_llm_board_contract.py": "conversation",
    "test_llamacpp.py": "llm",
    "test_llm_endpoints.py": "llm",
    "test_llm_router.py": "llm",
    "test_llm_text_normalizer.py": "llm",
    "test_media_fencing.py": "conversation",
    "test_mouth_continuity.py": "avatar",
    "test_mouth_quality.py": "avatar",
    "test_musetalk_preprocessing.py": "avatar",
    "test_musetalk_acceleration.py": "avatar",
    "test_optional_runtime_extras.py": "runtime",
    "test_pinned_resources.py": "runtime",
    "test_playback_commit.py": "conversation",
    "test_ragflow_integration.py": "ragflow",
    "test_reply_streaming.py": "conversation",
    "test_reply_latency.py": "conversation",
    "test_realtime_avatar.py": "conversation",
    "test_response_protocol.py": "conversation",
    "test_route_access.py": "runtime",
    "test_runtime_settings.py": "runtime",
    "test_deferred_settings.py": "runtime",
    "test_dependency_lock.py": "governance",
    "test_scene_background.py": "avatar",
    "test_server_shutdown.py": "runtime",
    "test_sovits_tts.py": "speech",
    "test_speech_timing.py": "conversation",
    "test_idle_greetings.py": "conversation",
    "test_stage_idle_reset.py": "conversation",
    "test_stage_presentation.py": "conversation",
    "test_startup_scripts.py": "runtime",
    "test_turn_lifecycle.py": "conversation",
    "test_vad.py": "speech",
    "test_voice_library.py": "speech",
    "test_voice_session.py": "conversation",
    "test_webrtc_lifecycle.py": "conversation",
    "test_voice_test_history.py": "conversation",
    "test_whisper_asr.py": "speech",
}

LIVE_FILES = frozenset({"test_live_llm_board_contract.py"})

SLOW_TESTS = frozenset(
    {
        "tests/test_edge_tts_worker.py::EdgeTTSWorkerTests::test_prefetch_keeps_only_the_next_fragment_in_flight",
        "tests/test_edge_tts_worker.py::EdgeTTSWorkerTests::test_first_fragment_pcm_does_not_wait_for_the_next_edge_request",
        "tests/test_edge_tts_worker.py::EdgeTTSWorkerTests::test_flush_talk_drops_prefetched_fragment_audio",
        "tests/test_funasr.py::FunASRLocalModelTests::test_model_load_disables_network_update_check",
        "tests/test_media_fencing.py::MuseTalkEnvelopePropagationTests::test_batch_cancelled_during_gpu_inference_cannot_publish_results",
        "tests/test_reply_streaming.py::BaselineReplayHarnessTests::test_fake_replay_is_reproducible_content_free_and_judges_slos",
    }
)


def _matching_markers(item: pytest.Item) -> Iterable[str]:
    file_name = item.path.name
    area = AREA_BY_FILE.get(file_name)
    if area:
        yield area
    if file_name in LIVE_FILES:
        yield "live"
    if item.nodeid.replace("\\", "/") in SLOW_TESTS:
        yield "slow"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    unclassified = set()
    for item in items:
        if item.path.name.startswith("test_") and item.path.name not in AREA_BY_FILE:
            unclassified.add(item.path.name)
            continue
        for marker in _matching_markers(item):
            item.add_marker(marker)

    if unclassified:
        names = ", ".join(sorted(unclassified))
        raise pytest.UsageError(
            f"Unclassified test modules: {names}. Add them to tests/conftest.py."
        )
