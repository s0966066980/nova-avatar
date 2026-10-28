# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Conversation attachment APIs; no caller-supplied paths or shared file IDs."""
import asyncio
from aiohttp import web

from src.server.attachments import AttachmentError, MAX_FILE_BYTES, MAX_REFERENCES, vision_ready
from src.server.state import state


def get_session(request, *, writing=False):
    session = state.voice_sessions.get(int(request.match_info['sessionid']))
    if session is None or session._closed:
        raise web.HTTPNotFound(text='session_reset')
    if writing and session._presenter == 'stage' and not getattr(state.config.stage, 'composer_enabled', False):
        raise web.HTTPConflict(text='composer_disabled')
    return session


async def listing(request):
    session = get_session(request)
    ready = await asyncio.to_thread(vision_ready, state.config)
    return web.json_response({'code': 0, 'data': {**session.attachments.snapshot(),
                                               'vision_ready': ready, 'reason': '' if ready else 'vision_unavailable'}})


async def upload(request):
    session = get_session(request, writing=True)
    session._attachment_busy += 1
    session.note_interaction()
    generation = session.attachments.generation
    try:
        if not await asyncio.to_thread(vision_ready, state.config):
            raise AttachmentError('vision_unavailable')
        reader = await request.multipart()
        values = []
        while (part := await reader.next()) is not None:
            if not part.filename or len(values) >= MAX_REFERENCES:
                raise AttachmentError('reference_limit')
            data = bytearray()
            while chunk := await part.read_chunk():
                data.extend(chunk)
                if len(data) > MAX_FILE_BYTES:
                    raise AttachmentError('file_size')
            values.append((part.filename, bytes(data)))
        added = await asyncio.to_thread(session.attachments.add_batch, values, generation)
        # Settings may have changed while parsing/uploading.
        try:
            get_session(request, writing=True)
        except web.HTTPException:
            for item in added:
                session.attachments.remove(item['id'])
            raise
        return web.json_response({'code': 0, 'data': added})
    except (AttachmentError, ValueError) as exc:
        return web.json_response({'code': -1, 'msg': str(exc)}, status=400)
    finally:
        session._attachment_busy -= 1
        session.note_interaction()


async def selection(request):
    session = get_session(request, writing=True)
    try:
        data = await request.json()
        session.attachments.select(data.get('selection'))
        session.note_interaction()
        return web.json_response({'code': 0, 'data': session.attachments.snapshot()})
    except (AttachmentError, ValueError, AttributeError) as exc:
        return web.json_response({'code': -1, 'msg': str(exc)}, status=400)


async def remove(request):
    session = get_session(request, writing=True)
    try:
        session.attachments.remove(request.match_info['identity'])
        session.note_interaction()
        return web.json_response({'code': 0, 'data': session.attachments.snapshot()})
    except AttachmentError as exc:
        return web.json_response({'code': -1, 'msg': str(exc)}, status=404)


async def interaction(request):
    session = get_session(request, writing=True)
    data = await request.json()
    session._composer_editing = bool(data.get('editing'))
    session.note_interaction()
    session._refresh_gate()
    return web.json_response({'code': 0})


def register(app):
    root = r'/api/conversations/{sessionid:\d+}'
    app.router.add_get(root + '/attachments', listing)
    app.router.add_post(root + '/attachments', upload)
    app.router.add_post(root + '/attachments/selection', selection)
    app.router.add_delete(root + '/attachments/{identity}', remove)
    app.router.add_post(root + '/interaction', interaction)
