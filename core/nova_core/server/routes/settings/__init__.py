# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""執行時設定 API：各功能的路由在同資料夾的模組，這裡只有總覽（get_settings）並重新匯出所有處理函式。"""
from __future__ import annotations

import asyncio
from nova_core.server.runtime_settings import current_snapshot
from nova_core.server.deferred_settings import snapshot as pending_snapshot
from nova_core.server.state import state
from nova_core.server.routes.settings.shared import _json, _active_session_count
from nova_core.server.routes.settings.llm import (  # noqa: F401
    get_llm_rules,
    set_llm_rules,
    list_llm_models,
    set_llm_behavior,
    set_llm_model,
)
from nova_core.server.routes.settings.speech import (  # noqa: F401
    get_vad_settings,
    set_vad_settings,
    get_speech_settings,
    set_stt_settings,
    list_tts_voices,
    tts_voice_audio,
    breezyvoice_status,
    preview_voice,
    _FieldTooLong,
    _read_field,
    upload_tts_voice,
    _voice_in_use,
    _archive_unused_voice,
    delete_tts_voice,
    _archive_unused_voice_model,
    delete_tts_voice_model,
)
from nova_core.server.routes.settings.stage import (  # noqa: F401
    get_stage_settings,
    set_stage_settings,
    get_backgrounds,
    upload_background,
    select_background,
    background_preview,
    delete_background,
    archived_backgrounds,
    restore_archived_background,
)
from nova_core.server.routes.settings.avatar import (  # noqa: F401
    set_avatar,
    set_video_output,
    set_mouth_quality,
    avatar_preview,
    avatar_scene_preview,
    delete_avatar,
    archived_avatars,
    restore_archived_avatar,
    delete_archived_avatar_permanently,
    _avatar_replace_conflict,
    import_avatar,
    import_avatar_status,
    uuid4_name,
)


async def get_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    # The snapshot scans avatars, voices and models on disk.
    data = await asyncio.to_thread(current_snapshot, state.config, tts=state.tts, avatars=state.avatar_service)
    data["pending_settings"] = pending_snapshot()
    data["session_count"] = _active_session_count()
    data["switching"] = bool(state.switching or state.settings_applying)
    data["ready"] = bool(state.server_ready)
    data["model_ready"] = bool(getattr(state, "model_ready", False))
    roles = getattr(state, "roles", None)
    data["roles"] = roles.snapshot() if roles else None
    return _json({"code": 0, "data": data})
