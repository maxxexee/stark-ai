"""Short-lived tickets for `GET /v1/speak/stream`, the one route an `<audio>` plays.

An `<audio>` element cannot send `Authorization`, and putting the session token in
its URL put a key to every route into access logs. A ticket opens exactly one
thing: speaking the text it was issued for, for `TTL_SECONDS`.

The ticket is random and the text stays here, so neither the token nor the words
(often a balance) travel in a URL. It is not single-use: a browser may request the
same `src` twice (Safari probes with a range request first), and a second play of
the same words within two minutes gives nothing away. The app runs as one process,
so the store lives in memory; a restart only expires the tickets early.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.common.api_error import ApiError


@dataclass(frozen=True)
class SpeakTicket:
    account_id: str
    text: str
    expires_at: float


class SpeakTickets:
    TTL_SECONDS = 120

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._tickets: dict[str, SpeakTicket] = {}
        self._lock = threading.Lock()

    def issue(self, account_id: str, text: str) -> str:
        now = self.clock()
        ticket = secrets.token_urlsafe(32)
        with self._lock:
            # Expired tickets are dropped here, so the store never outgrows what the
            # speak rate limit lets one account issue in two minutes.
            for stale in [k for k, t in self._tickets.items() if t.expires_at <= now]:
                del self._tickets[stale]
            self._tickets[ticket] = SpeakTicket(account_id, text, now + self.TTL_SECONDS)
        return ticket

    def redeem(self, ticket: str) -> SpeakTicket:
        """The ticket's account and text, or `unauthorized`: an unknown or expired
        ticket is refused exactly like a missing session."""
        with self._lock:
            found = self._tickets.get(ticket)
        if found is None or found.expires_at <= self.clock():
            raise ApiError(401, "unauthorized", "That voice link has expired.")
        return found
