"""Speech to text: NEAR AI's Whisper, or an honest refusal.

`GET cloud-api.near.ai/v1/models` confirmed `openai/whisper-large-v3` is hosted
there and `POST /v1/audio/transcriptions` exists (2026-10-22). The endpoint was
called live on 2026-10-22 with real speech and returned real transcripts, so the
request shape and the parsing are verified — for WAV. The MIME-named file part
(2026-10-24) is covered against a loopback server in `test_live_paths.py`, not
against NEAR AI itself. NEAR AI refuses WebM, so `hear` decodes it to WAV with
ffmpeg first; on 2026-10-24 the same sentence came back right as WAV, OGG and WebM.

No key configured → `transcribe` returns `(None, "no_key")` and the caller
answers with a plain sentence. It never invents a transcript, because a
hallucinated one would be read back as something the user "said".
"""

from __future__ import annotations

import http.client
import json
import os
import uuid

from app.common.keep_alive import KeepAlive
from app.modules.voice import audio

NEAR_AI_BASE = os.environ.get("NEAR_AI_BASE_URL") or "https://cloud-api.near.ai"
NEAR_AI_STT_MODEL = os.environ.get("NEAR_AI_STT_MODEL") or "openai/whisper-large-v3"

OK = "ok"
NO_KEY = "no_key"
FAILED = "failed"

_BOUNDARY = f"----stark{uuid.uuid4().hex}"

# Whisper sniffs the bytes, but the filename and part type should not lie
# about them — a Telegram OGG and a browser WebM arrive here too.
_EXT = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
        "audio/ogg": "ogg", "audio/webm": "webm", "audio/mpeg": "mp3",
        "audio/mp4": "m4a", "audio/aac": "aac"}


def _multipart(fields: dict[str, str], file_field: str, filename: str,
               data: bytes, content_type: str = "audio/wav") -> bytes:
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (f"--{_BOUNDARY}\r\n"
             f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
             f"{value}\r\n").encode()
        )
    parts.append(
        (f"--{_BOUNDARY}\r\n"
         f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
         f"Content-Type: {content_type}\r\n\r\n").encode()
        + data + b"\r\n"
    )
    parts.append(f"--{_BOUNDARY}--\r\n".encode())
    return b"".join(parts)


# What this provider actually reads. WAV and OGG/Opus come back transcribed;
# WebM (Chrome's MediaRecorder) and MP4 (Safari) were measured on 2026-10-24
# returning 400 "Audio could not be processed" whatever filename they were
# given — the container itself is refused, not the name. So a browser clip is
# decoded to 16 kHz mono WAV before it is sent, the same ffmpeg step a Telegram
# OGG takes (`audio.transcode`). Without ffmpeg the clip goes up unchanged: a
# format the provider can read on its own (mp3) still works, and one it cannot
# fails honestly instead of being guessed at.
# An unlabelled clip is decoded too: guessing "probably WAV" is exactly the
# assumption that made a WebM fail, and re-encoding a real WAV costs ~50ms.
WHISPER_READY = {"audio/wav", "audio/x-wav", "audio/wave", "audio/ogg"}


def hear(clip: bytes, *, api_key: str | None = None, mime: str | None = None,
         timeout: float = 30.0) -> tuple[str | None, str]:
    """Whatever a client recorded → `(transcript, reason)`.

    The one entry point the server should call: it knows which containers the
    provider refuses and decodes only those. `transcribe` stays the raw wire
    call so its tests can prove exactly what is posted.
    """
    kind = (mime or "").split(";")[0].strip().lower()
    if kind not in WHISPER_READY:
        wav, _why = audio.transcode(clip)
        if wav is not None:
            return transcribe(wav, api_key=api_key, timeout=timeout, mime="audio/wav")
    return transcribe(clip, api_key=api_key, timeout=timeout, mime=mime)


def transcribe(wav: bytes, *, api_key: str | None = None,
               timeout: float = 30.0, mime: str | None = None) -> tuple[str | None, str]:
    """Audio in, transcript out. `(text, reason)` on every path.

    Defaults to 16 kHz mono WAV; `mime` names what the clip really is
    (audio/ogg from Telegram, audio/webm from the browser's MediaRecorder).
    """
    key = api_key if api_key is not None else os.environ.get("NEAR_AI_API_KEY")
    if not key:
        return None, NO_KEY

    kind = (mime or "audio/wav").split(";")[0].strip().lower() or "audio/wav"
    body = _multipart({"model": NEAR_AI_STT_MODEL}, "file",
                      f"audio.{_EXT.get(kind, 'bin')}", wav, content_type=kind)
    # The connection is kept: the TLS handshake to this host costs 0.43s from
    # Lagos, and a voice turn that found a fresh one every time spent most of
    # its 0.9s of listening on it.
    pool = KeepAlive.for_base(NEAR_AI_BASE, timeout=timeout)
    try:
        status, raw = pool.send("POST", "/v1/audio/transcriptions", body, {
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={_BOUNDARY}",
        })
    except (http.client.HTTPException, OSError):
        return None, FAILED
    if status >= 400:
        return None, FAILED
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return None, FAILED

    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None, FAILED
    return text.strip(), OK
