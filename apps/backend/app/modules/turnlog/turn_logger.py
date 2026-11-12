"""Writes one conversation turn per exchange — voice and Telegram alike.

Every exit from a voice turn is logged: a turn Stark refused to hear and a turn it
answered are exactly the two a person wants to compare afterwards. `conversation`
is present only when the agent ran, and carries the whole exchange (prompt,
account and all), so "why did it say that" has an answer.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from app.modules.turnlog import turnlog


class TurnLogger:
    @staticmethod
    def ms(since: float) -> int:
        """Whole milliseconds since `since` — the log is read by humans."""
        return int((time.perf_counter() - since) * 1000)

    @staticmethod
    def timings(started: float, *, has_clip: bool, stt_ms: int = 0) -> dict[str, int]:
        """Stage timings, with `stt` only when there was a clip to transcribe.

        A missing key means "this stage did not run"; `0` would read as "instant",
        and the two are different complaints.
        """
        ms = {"total": TurnLogger.ms(started)}
        if has_clip:
            ms["stt"] = stt_ms
        return ms

    @staticmethod
    def model_name(agent: Any) -> Optional[str]:
        """Which model answered. Defensive: `model` sits behind a protocol."""
        model = getattr(agent, "model", None)
        return getattr(model, "model", None) or getattr(model, "name", None)

    @staticmethod
    def turn(*, account_id: Optional[str], agent: Any, outcome: str,
             clip: Optional[bytes], mime: Optional[str],
             heard: str = "", said: Optional[str] = None, stt: Optional[str] = None,
             payload: Optional[dict] = None, speak: Optional[bool] = True,
             ms: Optional[dict[str, int]] = None,
             conversation: Optional[list[dict]] = None, channel: str = "voice") -> None:
        result = payload or {}
        turnlog.record(turnlog.turn(
            outcome=outcome, heard=heard, said=said, stt=stt,
            reply=result.get("reply"), actions=result.get("actions"),
            code=result.get("code"), receipt_id=result.get("receipt_id"),
            token=result.get("token"), speak=speak, model=TurnLogger.model_name(agent),
            ms=ms, conversation=conversation, channel=channel, account_id=account_id,
        ), clip=clip, mime=mime)
