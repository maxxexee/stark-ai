"""Who is talking to us — channel identity linking and webhook dedupe.

The rules this file exists to enforce (HANDOFF §8A):

- **An unknown sender never creates a wallet and never pays.** A Telegram chat that
  has not been linked gets link instructions and nothing else — the agent is never
  called for it.
- **Linking is the only way a channel can claim an account.** A `user_id` in a
  message or a webhook body is never trusted; the only claim that counts is a
  6-digit code issued by the app and redeemed here.
- **One identity maps to exactly one user**; one user may have many identities.
- **Link attempts are rate-limited** and codes expire, are single-use, and are
  stored hashed.

Telegram keys on the numeric chat/user id. Nothing here keys on a display name.

The tables live in the same database as the receipts, next to `neon_auth.*`. A
`user_id` here is the **app account id** (`accounts.id`), not the auth provider's —
`auth_service.py` maps between them, so unlinking and relinking a channel never touches the
login the person uses.

Unlike the money paths in `receipt_repository.py`, consuming a link code is a handful of
statements rather than one. Neon's HTTP endpoint gives no transaction to open, so the
order is chosen to fail safe: the identity is bound **before** the code is marked
used, and a crash in between leaves a code that can be redeemed once more rather
than a chat bound to the wrong account.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.database import neon

CODE_TTL_SECONDS = 600        # 10 minutes, per the handoff design.
MAX_LINK_ATTEMPTS = 5         # per identity per window.
ATTEMPT_WINDOW_SECONDS = 600  # sliding window on failed link attempts.


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(code: str) -> str:
    # Unkeyed hash is fine here: the code is 6 random digits, short-lived and
    # rate-limited. A leak of the table is not a leak of a usable identity.
    return hashlib.sha256(code.encode()).hexdigest()


class IdentityRepository:
    def __init__(self, db: neon.Database | None = None) -> None:
        self.db = db or neon.open_database()

    # --- link codes ----------------------------------------------------------

    def issue_code(self, user_id: str, ttl_seconds: int = CODE_TTL_SECONDS) -> str:
        """Mint a single-use code for `user_id`. Returns the plaintext once."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = _now()
        self.db.query("DELETE FROM link_codes WHERE expires_at < $1", [_iso(now)])
        self.db.query(
            "INSERT INTO link_codes (code_hash, user_id, created_at, expires_at)"
            " VALUES ($1, $2, $3, $4)",
            [_hash(code), user_id, _iso(now),
             _iso(now + timedelta(seconds=ttl_seconds))],
        )
        return code

    def consume_code(self, code: str, channel: str, channel_user_id: str,
                     display_name: str | None = None) -> str | None:
        """Redeem a code: binds the identity to its user and returns the user_id.

        Fails (returns None) when the code is unknown, expired, already used, or
        the sender has burned through its attempt budget.
        """
        code = (code or "").strip()
        if not code:
            return None
        now = _now()
        row = self.db.one(
            "SELECT user_id, expires_at, used_at FROM link_codes WHERE code_hash = $1",
            [_hash(code)],
        )
        if row is None or row["used_at"] or row["expires_at"] < _iso(now):
            self._record_failed_attempt(channel, channel_user_id, now)
            return None
        if self._attempts(channel, channel_user_id, now) >= MAX_LINK_ATTEMPTS:
            return None

        self.db.query(
            "INSERT INTO channel_identities"
            " (channel, channel_user_id, user_id, display_name, linked_at, last_seen_at)"
            " VALUES ($1, $2, $3, $4, $5, $5)"
            " ON CONFLICT (channel, channel_user_id) DO UPDATE SET"
            "  user_id = EXCLUDED.user_id, display_name = EXCLUDED.display_name,"
            "  last_seen_at = EXCLUDED.last_seen_at",
            [channel, channel_user_id, row["user_id"], display_name, _iso(now)],
        )
        self.db.query(
            "UPDATE link_codes SET used_at = $1 WHERE code_hash = $2", [_iso(now), _hash(code)]
        )
        self.db.query(
            "DELETE FROM link_attempts WHERE channel = $1 AND channel_user_id = $2",
            [channel, channel_user_id],
        )
        return str(row["user_id"])

    def _attempts(self, channel: str, channel_user_id: str, now: datetime) -> int:
        row = self.db.one(
            "SELECT attempts, window_start FROM link_attempts"
            " WHERE channel = $1 AND channel_user_id = $2",
            [channel, channel_user_id],
        )
        if row is None:
            return 0
        if row["window_start"] < _iso(now - timedelta(seconds=ATTEMPT_WINDOW_SECONDS)):
            self.db.query(
                "DELETE FROM link_attempts WHERE channel = $1 AND channel_user_id = $2",
                [channel, channel_user_id],
            )
            return 0
        return int(row["attempts"])

    def _record_failed_attempt(self, channel: str, channel_user_id: str,
                               now: datetime) -> None:
        """Count a failed link attempt against this sender, inside its window."""
        attempts = self._attempts(channel, channel_user_id, now)
        self.db.query(
            "INSERT INTO link_attempts (channel, channel_user_id, attempts, window_start)"
            " VALUES ($1, $2, 1, $3)"
            " ON CONFLICT (channel, channel_user_id) DO UPDATE SET"
            "  attempts = link_attempts.attempts + 1,"
            "  window_start = CASE WHEN link_attempts.window_start < $4"
            "                      THEN $3 ELSE link_attempts.window_start END",
            [channel, channel_user_id, _iso(now),
             _iso(now - timedelta(seconds=ATTEMPT_WINDOW_SECONDS))],
        )

    # --- identity ------------------------------------------------------------

    def resolve(self, channel: str, channel_user_id: str) -> str | None:
        """The user this channel identity is bound to, or None."""
        row = self.db.one(
            "SELECT user_id FROM channel_identities"
            " WHERE channel = $1 AND channel_user_id = $2",
            [channel, channel_user_id],
        )
        if row is None:
            return None
        self.db.query(
            "UPDATE channel_identities SET last_seen_at = $1"
            " WHERE channel = $2 AND channel_user_id = $3",
            [_iso(_now()), channel, channel_user_id],
        )
        return str(row["user_id"])

    def is_linked(self, channel: str, channel_user_id: str) -> bool:
        return self.resolve(channel, channel_user_id) is not None

    def unlink(self, channel: str, channel_user_id: str) -> bool:
        row = self.db.one(
            "DELETE FROM channel_identities"
            " WHERE channel = $1 AND channel_user_id = $2 RETURNING 1 AS removed",
            [channel, channel_user_id],
        )
        return row is not None

    def identities_for(self, user_id: str) -> list[dict]:
        return self.db.query(
            "SELECT channel, channel_user_id, display_name, linked_at"
            " FROM channel_identities WHERE user_id = $1 ORDER BY linked_at",
            [user_id],
        )

    def clear(self) -> None:
        """Wipe identities, codes, attempts and dedupe — for `_stub/reset` only."""
        for table in ("channel_identities", "link_codes", "link_attempts",
                      "processed_messages"):
            self.db.query(f"DELETE FROM {table}")

    # --- dedupe --------------------------------------------------------------

    def claim_message(self, channel: str, message_id: str) -> bool:
        """True when this message has not been processed before.

        Telegram re-delivers updates; processing one twice would double-pay or
        double-reply, so every adapter call claims the id first. The claim is the
        insert itself: the primary key decides, not a read-then-write.
        """
        row = self.db.one(
            "INSERT INTO processed_messages (channel, message_id, processed_at)"
            " VALUES ($1, $2, $3) ON CONFLICT DO NOTHING RETURNING 1 AS claimed",
            [channel, message_id, _iso(_now())],
        )
        return row is not None
