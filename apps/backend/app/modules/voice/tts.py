"""Text to speech: ElevenLabs when keyed, otherwise silence.

`synthesize` returns `(wav, reason)` on every path, so a caller can never
mistake "nothing happened" for audio.

ElevenLabs Flash (`ELEVENLABS_API_KEY`) answers a Stark-length reply in well
under a second, and it says `₦5,000`, "Ikeja" and dates correctly. Raw 24 kHz
mono PCM comes back and is wrapped in a WAV here, because the rest of the
system (the dashboard's `data:` URL, `ffmpeg` for Telegram, the `/v1/speak`
contract) is spoken to in WAV.

With no key, or with ElevenLabs refusing, the result is `(None, reason)` and
the caller replies in plain text. Voice never gates a reply: `stt.py` refuses
to invent a transcript, this refuses to invent audio.

`voice_note` adds the step Telegram needs: ffmpeg encodes the WAV to
OGG/Opus, the only container `sendVoice` accepts. No ffmpeg means `None`, and
the reply goes as text.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import re
import wave

from app.common.keep_alive import KeepAlive
from app.modules.voice import audio

ELEVENLABS_API = "https://api.elevenlabs.io/v1"
# Flash is the fast one. The default voice must be a **premade** one: a free
# key gets HTTP 402 `paid_plan_required` on library/cloned voices over the API
# (measured 2026-10-24, against Rachel `21m00Tcm4TlvDq8ikWAM`).
ELEVENLABS_MODEL = "eleven_flash_v2_5"
ELEVENLABS_VOICE = "onwK4e9ZLuTAKqWW03F9"   # Daniel — steady broadcaster (premade)
ELEVENLABS_PCM_RATE = 24000

OK = "ok"
NO_KEY = "no_key"
FAILED = "failed"
ELEVENLABS_FAILED = "elevenlabs_failed"

# The naira sign is not in the voice's pronunciation dictionary. Measured
# 2026-10-24 by synthesising a real reply and transcribing the clip back:
# ElevenLabs said the letter N ("₦64,200" came back as "N64200"), so an amount the user hears has to be written the way a person
# says it: the number, then the word "naira". The text on screen keeps the
# sign; only the voice is spelled to.
_AMOUNT = re.compile(r"₦\s*(\d[\d,]*(?:\.\d+)?)")


def speakable(text: str) -> str:
    """What the voice is asked to say. Never used to change screen copy.

    `₦64,200` → `64,200 naira`; a stray `₦` with no number → `naira`. Everything
    else is passed through untouched, because the reply is already written to
    be read aloud.
    """
    return _AMOUNT.sub(r"\1 naira", text).replace("₦", "naira")


def _pcm_to_wav(pcm: bytes, rate: int = ELEVENLABS_PCM_RATE) -> bytes:
    """Raw 16-bit mono PCM → a WAV, since nothing here accepts loose PCM."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def synthesize(text: str, *, timeout: float = 10.0) -> tuple[bytes | None, str]:
    """Text in, 24 kHz mono WAV out. `(wav, reason)` on every path.

    Reads config at call time (like `stt.transcribe`), so a key can appear
    without a restart and tests can point it elsewhere. The timeout is short on
    purpose: a slow voice must give way to the text reply rather than hold it
    hostage.
    """
    if not text or not text.strip():
        return None, FAILED
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return None, NO_KEY
    base = os.environ.get("ELEVENLABS_API_URL") or ELEVENLABS_API
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID") or ELEVENLABS_VOICE
    model_id = os.environ.get("ELEVENLABS_MODEL_ID") or ELEVENLABS_MODEL

    body = json.dumps({
        "text": speakable(text).strip(),
        "model_id": model_id,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
    }).encode()
    # A kept connection: the handshake to this host is 0.39s from Lagos, paid on
    # every spoken reply when it was opened fresh.
    pool = KeepAlive.for_base(base, timeout=timeout)
    try:
        status, pcm = pool.send(
            "POST", f"/text-to-speech/{voice_id}?output_format=pcm_24000", body,
            {"Content-Type": "application/json", "xi-api-key": key})
    except (http.client.HTTPException, TimeoutError, OSError):
        return None, ELEVENLABS_FAILED
    if status >= 400:
        return None, ELEVENLABS_FAILED

    if not pcm or len(pcm) < 2:
        return None, ELEVENLABS_FAILED
    return _pcm_to_wav(pcm), OK


# Where a spoken reply is cut so the first words need not wait for the last.
# Whitespace after a full stop, question or exclamation: an amount like `0.5`
# has no space in it, so a decimal never splits.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    """The reply in the units the voice is asked for, largest that still starts soon."""
    return [part.strip() for part in _SENTENCE.split(speakable(text).strip())
            if part.strip()]


def stream_elevenlabs(text: str, *, base: str | None = None,
                      timeout: float = 20.0):
    """Yield MP3 chunks as ElevenLabs produces them — a generator, not bytes.

    The point is time-to-first-sound: the buffered path waits the whole ~1.4s
    for synthesis before the client can start playing, this sends whatever has
    arrived and lets the player start on the first few kilobytes. No key, or a
    refusal, yields nothing at all and the caller falls back to a whole reply.
    """
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key or not text or not text.strip():
        return
    text = speakable(text)
    base = base or os.environ.get("ELEVENLABS_API_URL") or ELEVENLABS_API
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID") or ELEVENLABS_VOICE
    model_id = os.environ.get("ELEVENLABS_MODEL_ID") or ELEVENLABS_MODEL

    body = json.dumps({
        "text": text.strip(),
        "model_id": model_id,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
    }).encode()
    pool = KeepAlive.for_base(base, timeout=timeout)
    try:
        wire, res = pool.hold(
            "POST", f"/text-to-speech/{voice_id}/stream?output_format=mp3_44100_128",
            body, {"Content-Type": "application/json", "xi-api-key": key})
    except (http.client.HTTPException, TimeoutError, OSError):
        return  # the caller falls back; a refusal here is not an error to 500 on

    finished = False
    try:
        if res.status >= 400:
            return
        # read1, not read: `read` fills the whole buffer before returning and
        # would sit on the socket until the clip was finished — the one thing
        # this function exists to avoid.
        reader = getattr(res, "read1", None) or res.read
        while True:
            chunk = reader(16384)
            if not chunk:
                break
            yield chunk
        finished = True
    except (TimeoutError, OSError):  # a dropped stream plays what it already said
        return
    finally:
        reusable = finished and not res.will_close
        res.close()
        if reusable:
            pool.release(wire)
        else:
            pool.drop(wire)


def voice_note(text: str, *, timeout: float = 10.0) -> bytes | None:
    """Text in, OGG/Opus voice-note bytes out, or `None` so the caller sends
    text instead. Every refusal lands here: no key, ElevenLabs down, empty
    audio, no ffmpeg."""
    wav, _why = synthesize(text, timeout=timeout)
    if wav is None:
        return None
    return audio.encode_opus(wav)
