"""Voice-note normalisation: whatever Telegram sends → 16 kHz mono WAV.

Whisper wants 16 kHz mono; Telegram voice notes are OGG/Opus, voice messages
from other channels can be MP3 or M4A. `ffmpeg` is the only decoder that reads
all of them, and it is already on this machine (9.0.2, verified 2026-10-22).

The rules that keep this safe:

- **Bounded input.** A file over `max_input_bytes` or `max_seconds` is refused
  before decoding, so a hostile upload cannot eat the process.
- **Failure is loud and cheap.** A decode that fails returns a reason; nothing
  is guessed, no audio is forwarded, and temp files live in a TemporaryDirectory
  that cleans itself up.
- **Only audio containers, only local files.** An upload is attacker-chosen bytes,
  and ffmpeg will happily open a playlist (HLS, concat) that names other files or
  URLs. `INPUT_FLAGS` pins the input to the containers voice actually arrives in
  and to the `file` protocol, and every run has a wall-clock `TIMEOUT_SECONDS`.
- **ffmpeg may be absent.** Then `transcode` says so and the caller replies
  plainly ("send it as text") instead of pretending it heard something.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

FFMPEG = shutil.which("ffmpeg")

MAX_INPUT_BYTES = 5 * 1024 * 1024   # Telegram voice notes are well under this.
MAX_SECONDS = 60                    # One minute of speech is plenty for a bill.

# Demuxer names, not extensions: `matroska` covers WebM, `mov` covers MP4/M4A.
INPUT_FLAGS = (
    "-nostdin",
    "-protocol_whitelist", "file",
    "-format_whitelist", "ogg,matroska,webm,mov,mp4,m4a,wav,mp3,aac,flac",
)
TIMEOUT_SECONDS = 20                # A minute of speech decodes in well under a second.

OK = "ok"
TOO_LARGE = "too_large"
DECODE_FAILED = "decode_failed"
NO_FFMPEG = "no_ffmpeg"


def ffmpeg_available() -> bool:
    return FFMPEG is not None


def _run(args: list[str]) -> int | None:
    """ffmpeg's exit code, or None when it outran `TIMEOUT_SECONDS` (it is killed)."""
    try:
        return subprocess.run([FFMPEG, "-v", "error", "-y", *INPUT_FLAGS, *args],
                              capture_output=True, timeout=TIMEOUT_SECONDS).returncode
    except subprocess.TimeoutExpired:
        return None


def encode_opus(wav: bytes, *, max_input_bytes: int = MAX_INPUT_BYTES,
                max_seconds: int = MAX_SECONDS) -> bytes | None:
    """16 kHz mono s16 WAV → OGG/Opus mono, the container Telegram's
    `sendVoice` accepts. The mirror of `transcode`, same rules: bounded input,
    loud failure, temp files that clean themselves up, `None` (never a partial
    file) when ffmpeg is absent or the encode fails."""
    if len(wav) < 44 or len(wav) > max_input_bytes:
        return None
    if FFMPEG is None:
        return None

    with tempfile.TemporaryDirectory(prefix="stark_audio_") as tmp:
        src = Path(tmp) / "in.wav"
        dst = Path(tmp) / "out.ogg"
        src.write_bytes(wav)
        code = _run([
            "-i", str(src),
            "-t", str(max_seconds),
            "-ac", "1", "-ar", "16000",
            "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", str(dst),
        ])
        out = dst.read_bytes() if dst.exists() else b""
        if code != 0 or not out.startswith(b"OggS"):
            return None
        return out


def transcode(raw: bytes, *, filename: str = "voice.ogg",
              max_input_bytes: int = MAX_INPUT_BYTES,
              max_seconds: int = MAX_SECONDS) -> tuple[bytes | None, str]:
    """Decode `raw` to 16 kHz mono s16 WAV. Returns `(wav, reason)`.

    On failure `wav` is None and `reason` is one of `NO_FFMPEG`, `TOO_LARGE`,
    `DECODE_FAILED`. Nothing is ever partially returned.
    """
    if not raw:
        return None, DECODE_FAILED
    if len(raw) > max_input_bytes:
        return None, TOO_LARGE
    if FFMPEG is None:
        return None, NO_FFMPEG

    with tempfile.TemporaryDirectory(prefix="stark_audio_") as tmp:
        src = Path(tmp) / (Path(filename).name or "voice")
        dst = Path(tmp) / "out.wav"
        src.write_bytes(raw)
        # To a file, not a pipe: ffmpeg cannot seek a pipe and then writes
        # 0xFFFFFFFF sizes into the WAV header, which some decoders reject.
        code = _run([
            "-i", str(src),
            "-t", str(max_seconds),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-f", "wav", str(dst),
        ])
        wav = dst.read_bytes() if dst.exists() else b""
        if code != 0 or len(wav) < 44:
            return None, DECODE_FAILED
        return wav, OK
