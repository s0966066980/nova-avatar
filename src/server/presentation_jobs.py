# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Persistent, cancellable asset preparation and offline MuseTalk production."""
from __future__ import annotations

import gc
import json
import os
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from fractions import Fraction

from src.avatars import presentation as assets

_events = {}
_lock = threading.RLock()


def root():
    path = assets.avatars_root().parent / "presentation_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def status(job_id):
    import re
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise assets.PresentationError("無效的工作 ID")
    with _lock:
        path = root() / f"{job_id}.json"
        if not path.exists():
            raise assets.PresentationError("找不到工作")
        value = json.loads(path.read_text())
        if value["status"] in {"queued", "running"} and job_id not in _events:
            value.update(status="failed", error="程序已重啟，工作中斷；已用素材保持完整")
            import re
            source = value.get("temporary_source", "")
            if re.fullmatch(r"[0-9a-f]{32}\.upload", source):
                temporary = root() / source
                if value.get("kind") == "record" and temporary.exists():
                    _preserve_record_source(temporary, value)
                    (assets.avatars_root().parent / "records" / f"record_{job_id}.mp4").unlink(missing_ok=True)
                else:
                    temporary.unlink(missing_ok=True)
            destination = value.get("temporary_asset", "")
            if re.fullmatch(r"[0-9a-f]{32}\.mp4", destination):
                try:
                    (assets.folder(value["avatar_id"]) / destination).unlink(missing_ok=True)
                except assets.PresentationError:
                    pass
            _save(value)
        return value


def recover_pending():
    """Run once at process startup, before new jobs can be accepted."""
    from src.utils.logging import logger
    for path in root().glob("*.json"):
        try:
            status(path.stem)
        except (assets.PresentationError, ValueError, OSError):
            logger.warning("無法恢復素材工作 %s", path.name)
    for path in root().glob("*.tmp"):
        path.unlink(missing_ok=True)


def _save(value):
    path = root() / f"{value['id']}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    os.replace(temporary, path)


def cancel(job_id):
    value = status(job_id)
    event = _events.get(job_id)
    if event:
        event.set()
    return value


def submit(kind, *, config, avatar_id="", slot="talking", source=None, text="", source_suffix=".webm"):
    from src.server.state import state
    from src.server.runtime_settings import _SWITCH_LOCK
    gpu = kind == "generate"
    from src.server.import_jobs import _WORKER_LOCK
    if gpu and (state.avatar_streams or state.pcs):
        raise assets.PresentationError("請先斷開控制台與舞台，再製作說話素材")
    if gpu and not _SWITCH_LOCK.acquire(blocking=False):
        raise assets.PresentationError("正在製作或切換數位人，請稍候")
    if gpu and not _WORKER_LOCK.acquire(blocking=False):
        _SWITCH_LOCK.release()
        raise assets.PresentationError("已有角色正在製作，請稍後再試")
    if gpu:
        state.switching = True
    job_id = uuid.uuid4().hex
    value = {"id": job_id, "kind": kind, "avatar_id": avatar_id, "slot": slot,
             "status": "queued", "progress": 0, "error": ""}
    event = threading.Event()
    if source:
        value["temporary_source"] = Path(source).name
        value["source_suffix"] = source_suffix
    try:
        settings = deepcopy(config)
        with _lock:
            _save(value)
            _events[job_id] = event
    except BaseException:
        if source:
            Path(source).unlink(missing_ok=True)
        if gpu:
            state.switching = False
            _WORKER_LOCK.release()
            _SWITCH_LOCK.release()
        raise

    def progress(amount):
        if event.is_set():
            raise InterruptedError("已取消")
        with _lock:
            value["progress"] = int(amount)
            _save(value)

    def run():
        destination = None
        try:
            value["status"] = "running"
            progress(1)
            if kind == "record":
                destination = assets.avatars_root().parent / "records" / f"record_{job_id}.mp4"
                destination.parent.mkdir(parents=True, exist_ok=True)
                transcode_record(Path(source), destination, progress, event.is_set)
                result = {"filename": destination.name, "url": f"/download/{destination.name}"}
            else:
                destination = assets.folder(avatar_id) / f"{uuid.uuid4().hex}.mp4"
                value["temporary_asset"] = destination.name
                progress(1)
                if gpu:
                    state.model = state.avatar = None
                    state.model_ready = False
                    _release()
                    result = generate(settings, avatar_id, text, destination, progress, event.is_set)
                else:
                    result = assets.normalize(Path(source), destination, progress, event.is_set)
                result["url"] = f"/api/presentation/{avatar_id}/media/{destination.name}"
                if event.is_set():
                    raise InterruptedError("已取消")
                assets.candidate(avatar_id, slot, result)
            value.update(result=result, status="done", progress=100)
        except InterruptedError as exc:
            value.update(status="cancelled", error=str(exc))
            if destination:
                destination.unlink(missing_ok=True)
        except Exception as exc:
            from src.utils.logging import logger
            logger.exception("Presentation job failed")
            value.update(status="failed", error=str(exc))
            if destination:
                destination.unlink(missing_ok=True)
        finally:
            if kind == "record" and source and Path(source).exists() and value["status"] != "done":
                _preserve_record_source(Path(source), value)
            if source:
                Path(source).unlink(missing_ok=True)
            if gpu:
                _release()
                try:
                    from src.avatars.factory import prepare_avatar_model
                    state.model, state.avatar = prepare_avatar_model(state.config)
                    state.model_ready = True
                except Exception as exc:
                    state.model_ready = False
                    value["warning"] = f"請重新套用數位人：{exc}"
                finally:
                    state.switching = False
                    _WORKER_LOCK.release()
                    _SWITCH_LOCK.release()
            with _lock:
                value.pop("temporary_source", None)
                value.pop("temporary_asset", None)
                try:
                    _save(value)
                finally:
                    _events.pop(job_id, None)
    try:
        threading.Thread(target=run, name=f"presentation-{kind}", daemon=True).start()
    except BaseException:
        with _lock:
            _events.pop(job_id, None)
        if source:
            Path(source).unlink(missing_ok=True)
        if gpu:
            state.switching = False
            _WORKER_LOCK.release()
            _SWITCH_LOCK.release()
        value.update(status="failed", error="工作無法啟動")
        _save(value)
        raise
    return {**value}


def _preserve_record_source(source, value):
    suffix = value.get("source_suffix", ".webm")
    suffix = suffix if suffix in {".mp4", ".webm"} else ".bin"
    original = assets.avatars_root().parent / "records" / f"original_{value['id']}{suffix}"
    original.parent.mkdir(parents=True, exist_ok=True)
    source.replace(original)
    value["original"] = {"filename": original.name, "url": f"/download/{original.name}"}


def _release():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


class PCMCollector:
    def __init__(self, cancelled):
        self.frames = []
        self.cancelled = cancelled
        self.failure = ""
        self.sample_rate = 16000
        self.chunk = 320

    def put_audio_frame(self, frame, datainfo=None):
        if self.cancelled():
            raise InterruptedError("已取消")
        import numpy as np
        self.frames.append(np.asarray(frame, dtype=np.float32).copy())
        return True

    def accepts_media(self, *args):
        return not self.cancelled()

    def fragment_playback_committed(self, *args):
        return False

    def fragment_playback_ended(self, *args):
        return True

    def notify_fragment_synthesis_failed(self, event, reason):
        self.failure = str(reason)

    def observe_tts_onset_preroll_ms(self, *args):
        pass

    def observe_tts_retry(self, **kwargs):
        pass

    def mark_stage_end(self, *args):
        pass


def generate(config, avatar_id, text, destination, progress, cancelled):
    import av
    import numpy as np
    import torch
    from src.tts.factory import create_tts_engine
    from src.avatars.musetalk.avatar import load_model, load_avatar, MuseTalkAvatar
    collector = PCMCollector(cancelled)
    tts = create_tts_engine(config.tts.type, config, collector)
    tts.txt_to_audio((text, {}))
    if cancelled():
        raise InterruptedError("已取消")
    if collector.failure or not collector.frames:
        raise assets.PresentationError(collector.failure or "沒有取得語音，請重試")
    pcm = np.concatenate(collector.frames)
    starts = np.flatnonzero(np.abs(pcm) > 0.0001)
    if not starts.size or starts[-1] - starts[0] + 1 < 80000:
        raise assets.PresentationError("文字的有效語音不足五秒，請增加文字")
    pcm = pcm[starts[0]:starts[0] + 80000]
    progress(10)
    model = avatar = owner = None
    try:
        # Deliberately do not inherit Tiny VAE or optional decoder engines.
        model = load_model()
        avatar = load_avatar(avatar_id)
        vae, unet, pe, timesteps, processor = model
        with torch.inference_mode():
            features = processor.audio2feat(pcm)
        chunks = processor.feature2chunks(features, fps=25, batch_size=125)
        if len(chunks) < 125:
            raise assets.PresentationError("嘴型音訊特徵不足五秒")
        owner = MuseTalkAvatar.__new__(MuseTalkAvatar)
        owner.config = config
        (owner.frame_list_cycle, owner.mask_list_cycle, owner.coord_list_cycle,
         owner.mask_coords_list_cycle, latents) = avatar
        height, width = owner.frame_list_cycle[0].shape[:2]
        with av.open(str(destination), "w") as output, torch.inference_mode():
            stream = output.add_stream("libx264", rate=25)
            stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
            stream.options = {"crf": "18", "preset": "fast"}
            batch = max(1, min(int(config.model.batch_size), 8))
            for start in range(0, 125, batch):
                if cancelled():
                    raise InterruptedError("已取消")
                end = min(125, start + batch)
                indices = [i % len(latents) for i in range(start, end)]
                audio = torch.from_numpy(np.stack(chunks[start:end])).to(device=unet.device, dtype=unet.model.dtype)
                latent = torch.cat([latents[i] for i in indices]).to(device=unet.device, dtype=unet.model.dtype)
                predicted = unet.model(latent, timesteps, encoder_hidden_states=pe(audio)).sample
                decoded = vae.decode_latents(predicted)
                for offset, image in enumerate(decoded):
                    frame = av.VideoFrame.from_ndarray(owner.paste_back_frame(image, indices[offset]), format="bgr24")
                    frame.pts, frame.time_base = start + offset, Fraction(1, 25)
                    for packet in stream.encode(frame):
                        output.mux(packet)
                progress(15 + end * 80 // 125)
            for packet in stream.encode():
                output.mux(packet)
        return {"name": destination.name, "width": width, "height": height,
                "fps": 25, "frames": 125, "duration": 5.0, "audio": False, "quality": "full"}
    finally:
        del owner, avatar, model
        _release()


def transcode_record(source, destination, progress, cancelled):
    """Preserve capture timestamps when exporting a browser recording as MP4."""
    import av
    with Path(source).open("rb") as source_io, av.open(source_io) as incoming, av.open(str(destination), "w") as output:
        if not incoming.streams.video or not incoming.streams.audio:
            raise assets.PresentationError("錄影須包含場景影像與回答音軌")
        original = incoming.streams.video[0]
        original_audio = incoming.streams.audio[0]
        if original.codec_context.name == "h264":
            # Native browser MP4 is already the deliverable codec. Copy packets
            # to preserve every captured frame without another costly encode.
            video = output.add_stream_from_template(original)
            copy_audio = original_audio.codec_context.name == "aac"
            audio = output.add_stream_from_template(original_audio) if copy_audio else output.add_stream("aac", rate=48000)
            if not copy_audio:
                audio.layout = "stereo"
            resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
            count = 0
            for packet in incoming.demux(original, original_audio):
                if cancelled():
                    raise InterruptedError("已取消")
                if packet.dts is None:
                    continue
                if packet.stream.type == "video" or copy_audio:
                    packet.stream = video if packet.stream.type == "video" else audio
                    output.mux(packet)
                else:
                    for frame in packet.decode():
                        for converted in resampler.resample(frame):
                            for encoded in audio.encode(converted):
                                output.mux(encoded)
                count += 1
                if count % 100 == 0:
                    progress(min(94, max(2, source_io.tell() * 90 // Path(source).stat().st_size)))
            if not copy_audio:
                for converted in resampler.resample(None):
                    for packet in audio.encode(converted):
                        output.mux(packet)
                for packet in audio.encode():
                    output.mux(packet)
            progress(95)
            return
        video = output.add_stream("libx264", rate=25)
        video.width, video.height, video.pix_fmt = original.width, original.height, "yuv420p"
        video.codec_context.time_base = Fraction(1, 90000)
        video.codec_context.thread_count = 2
        video.options = {"crf": "20", "preset": "fast"}
        audio = output.add_stream("aac", rate=48000)
        audio.layout = "stereo"
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        frame_count = 0
        for frame in incoming.decode():
            if cancelled():
                raise InterruptedError("已取消")
            if isinstance(frame, av.VideoFrame):
                frame.pts = round(max(0, frame.time or 0) * 90000)
                frame.time_base = Fraction(1, 90000)
                packets = video.encode(frame)
            else:
                packets = [packet for converted in resampler.resample(frame) for packet in audio.encode(converted)]
            for packet in packets:
                output.mux(packet)
            frame_count += 1
            if frame_count % 100 == 0:
                progress(min(94, max(2, source_io.tell() * 90 // Path(source).stat().st_size)))
        for converted in resampler.resample(None):
            for packet in audio.encode(converted):
                output.mux(packet)
        for target in (video, audio):
            for packet in target.encode():
                output.mux(packet)
        progress(95)
