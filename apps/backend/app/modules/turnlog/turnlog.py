"""One JSON line per conversation turn: what was said, heard, answered, cost.

An observation tool, not a product feature — nothing at runtime reads it back.
It exists so a person can answer, after a real conversation, "what did Stark
actually hear, what did it do with that, and where did the time go" — instead
of guessing from memory.

Opt in with `STARK_TURN_LOG`: a directory to write into, or `1` for
`<backend>/logs/turns`. Off by default, so tests, smoke runs and demos leave
nothing behind.

Three rules:

- **A log never breaks a request.** Every public function swallows its own
  failure: a full disk or an unwritable path must not turn a spoken question
  into a 500.
- **One file for the words.** `turns.jsonl`, one JSON object per line, appended
  under a lock — the HTTP server is threaded. A clip is binary, so it lands in
  `audio/` beside the log and the line describing it carries a relative path.
  No base64 in the log: it would make the file unreadable within a session.
- **Config read at call time**, like `stt` and `tts`, so the flag can be
  flipped without rebuilding the server.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.modules.voice import tts

DEFAULT_DIRNAME = "logs/turns"
LOG_NAME = "turns.jsonl"
AUDIO_DIRNAME = "audio"

_OFF = {"", "0", "false", "no", "off"}
_ON = {"1", "true", "yes", "on"}

# Threads share the sequence counter and the append; not reentrant by design.
_lock = threading.RLock()
_seq = 0

# What a browser or Telegram actually uploads. The extension is decoration for
# whoever opens the folder by hand — the log line carries the mime too.
_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/flac": ".flac",
}


def enabled() -> bool:
    """Is logging on? Read every call, so the flag needs no restart."""
    return str(os.environ.get("STARK_TURN_LOG") or "").strip().lower() not in _OFF


def log_dir() -> Path:
    """Where the log lives. `STARK_TURN_LOG=1` means the default directory."""
    raw = str(os.environ.get("STARK_TURN_LOG") or "").strip()
    if raw.lower() in _ON:
        return Path(__file__).resolve().parents[3] / DEFAULT_DIRNAME
    return Path(raw).expanduser()


def turn(*, outcome: str, heard: str = "", said: str | None = None,
         stt: str | None = None, reply: str | None = None,
         actions: list[str] | None = None, code: str | None = None,
         receipt_id: str | None = None, token: str | None = None,
         speak: bool | None = None, model: str | None = None,
         ms: dict[str, int] | None = None,
         conversation: list[dict] | None = None,
         channel: str | None = None,
         account_id: str | None = None) -> dict[str, Any]:
    """The entry shape for one spoken exchange. Pure — nothing is written.

    - `heard`: the transcript as the recognizer produced it, verbatim.
    - `said`: what the wake gate passed on (the transcript minus the address),
      `None` when the turn was never handed to the agent.
    - `outcome`: `answered`, `asleep` (wake gate refused) or `unheard` (STT
      failed — no transcript, no agent, no guess).
    - `actions`/`code`/`receipt_id`/`token`: what the agent *did*, so a reply
      that sounds right can be checked against what actually happened.
    - `ms`: stage timings in whole milliseconds — `total`, `stt`, `agent`,
      `tts`.
    - `conversation`: the whole exchange with the model — system prompt and
      account snapshot first, then each user, assistant and tool message in
      order. Present only on a turn that reached the agent. It is what makes
      "why did it say that" answerable instead of arguable: the reply alone
      never shows what the model was looking at.
    - `channel`: where it came from — `voice`, `telegram`. Absent on entries
      written before 2026-10-25, when only `/v1/voice` logged at all.
    - `account_id`: whose turn it was. The log is one file for every account, so
      this is what lets an operator read one person's turns and nobody else's.
      Absent on entries written before 2026-11-12.
    """
    entry = {
        "kind": "turn",
        "outcome": outcome,
        "heard": heard,
        "said": said,
        "stt": stt,
        "reply": reply,
        "actions": list(actions or []),
        "code": code,
        "receipt_id": receipt_id,
        "token": token,
        "speak_requested": speak,
        "model": model,
        "ms": dict(ms or {}),
    }
    if conversation:
        entry["conversation"] = [dict(m) for m in conversation]
    if channel:
        entry["channel"] = channel
    if account_id:
        entry["account_id"] = account_id
    return entry


def speak(*, text: str, ms: int, reason: str, stream: bool,
          provider: str | None = None) -> dict[str, Any]:
    """The entry shape for one synthesis — the voice half of the exchange.

    `ms` is time to the first audio byte on the stream (what the ear waits for)
    and whole-synthesis time on the buffered route. `spoken` is the string the
    provider was actually given, after `tts.speakable`, so a pronunciation
    complaint can be checked against the exact input.
    """
    return {
        "kind": "speak",
        "text": text,
        "spoken": tts.speakable(text),
        "stream": stream,
        "provider": provider,
        "tts": reason,
        "ms": int(ms),
    }



def record(entry: dict, *, clip: bytes | None = None,
           mime: str | None = None) -> None:
    """Append `entry` to the log, saving `clip` first when there is one.

    Returns None whether it worked or not — see the module docstring.
    """
    if not enabled() or not entry:
        return
    try:
        line = dict(entry)
        stamp = datetime.now(timezone.utc)
        line.setdefault("ts", stamp.isoformat(timespec="milliseconds"))
        if mime:
            line["mime"] = mime
        if clip:
            line["audio"] = _save_clip(clip, mime, stamp)
            line["audio_bytes"] = len(clip)
        _append(line)
    except Exception:
        pass


def _save_clip(clip: bytes, mime: str | None, stamp: datetime) -> str:
    """Write the clip under `audio/` and return its path relative to the log."""
    global _seq
    kind = (mime or "").split(";")[0].strip().lower()
    ext = _EXTENSIONS.get(kind, ".bin")
    with _lock:
        _seq += 1
        name = f"{stamp.strftime('%Y%m%dT%H%M%S')}-{_seq:04d}-in{ext}"
        folder = log_dir() / AUDIO_DIRNAME
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(clip)
    return f"{AUDIO_DIRNAME}/{name}"


def _append(line: dict) -> None:
    target = log_dir()
    target.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(line, ensure_ascii=False, default=str)
    with _lock:
        with (target / LOG_NAME).open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")


def lines(path: Path | None = None) -> list[dict]:
    """Everything logged so far, oldest first. For scripts and tests.

    `path` may be the log directory or the file itself — callers usually have
    the folder, and asking them to know the filename is a papercut.
    """
    source = path or log_dir()
    if source.is_dir():
        source = source / LOG_NAME
    if not source.exists():
        return []
    out: list[dict] = []
    for raw in source.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out
