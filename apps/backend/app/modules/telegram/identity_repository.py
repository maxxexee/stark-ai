"""Who is talking to us — channel identity linking and webhook dedupe.

The rules this file exists to enforce (HANDOFF §5, Doors and identity):

- **An unknown sender never creates a wallet and never pays.** A Telegram chat that
  has not been linked gets link instructions and nothing else — the agent is never
  called for it.
- **Linking is the only way a channel can claim an account.** A `user_id` in a
  message or a webhook body is never trusted; the only claim that counts is a
  6-digit code issued by the app and redeemed here.
- **One identity maps to exactly one user**; one user may have many identities.
- **Link attempts are rate-limited** per sender and across every sender, and codes
  expire, are single-use, are stored hashed, and an account holds one live code at
  a time.

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
# Failed redeems from every sender together, per window. The per-sender budget
# alone did not bound guessing: each new Telegram account is a fresh sender. Past
# this, every redeem is refused until the window rolls over — a burst of wrong
# codes can hold linking up for ten minutes, which beats a guessed code binding a
# stranger's chat to someone's wallet. Twenty guesses at six digits, with two codes
# live, is one hit in about 25,000 windows: half a year of nonstop guessing.
MAX_GLOBAL_FAILED_ATTEMPTS = 20
# The `link_attempts` row that counts every sender's failures together. No Telegram
# id is "*", so it cannot collide with a real sender.
EVERY_SENDER = ("*", "*")
# Telegram retries an update for at most a day; a dedupe row older than this can
# never be claimed again, so it is dropped.
PROCESSED_RETENTION_SECONDS = 2 * 24 * 3600


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
        """Mint a single-use code for `user_id`. Returns the plaintext once.

        Minting cancels the account's earlier codes. Otherwise every tap of "Get
        another code" left one more live code for a guesser to hit.
        """
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = _now()
        self.db.query("DELETE FROM link_codes WHERE user_id = $1 OR expires_at < $2",
                      [user_id, _iso(now)])
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
        the sender — or every sender together — has burned through its attempt
        budget. A budget that is spent refuses even the right code, so a guess
        that lands after the limit is worth nothing.
        """
        code = (code or "").strip()
        if not code:
            return None
        now = _now()
        if (self._attempts(channel, channel_user_id, now) >= MAX_LINK_ATTEMPTS
                or self._attempts(*EVERY_SENDER, now) >= MAX_GLOBAL_FAILED_ATTEMPTS):
            return None
        row = self.db.one(
            "SELECT user_id, expires_at, used_at FROM link_codes WHERE code_hash = $1",
            [_hash(code)],
        )
        if row is None or row["used_at"] or row["expires_at"] < _iso(now):
            self._record_failed_attempt(channel, channel_user_id, now)
            self._record_failed_attempt(*EVERY_SENDER, now)
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

    def unlink_for(self, user_id: str, channel: str, channel_user_id: str) -> bool:
        """Unlink a chat on behalf of the account it speaks for — the app's Remove.

        Scoped to `user_id`, so one account can never unlink another's chat by
        naming its id.
        """
        row = self.db.one(
            "DELETE FROM channel_identities"
            " WHERE channel = $1 AND channel_user_id = $2 AND user_id = $3"
            " RETURNING 1 AS removed",
            [channel, channel_user_id, user_id],
        )
        return row is not None

    def linked_accounts(self, channel: str) -> list[str]:
        """Every account with at least one chat linked on `channel`."""
        return [row["user_id"] for row in self.db.query(
            "SELECT DISTINCT user_id FROM channel_identities WHERE channel = $1", [channel])]

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
        insert itself: the primary key decides, not a read-then-write. The caller
        passes an id that is unique across the whole bot (Telegram's `update_id`),
        never a per-chat one.

        Rows past `PROCESSED_RETENTION_SECONDS` are dropped in the same statement,
        so the table stays a few days deep instead of growing forever.
        """
        now = _now()
        row = self.db.one(
            "WITH pruned AS (DELETE FROM processed_messages WHERE processed_at < $4)"
            " INSERT INTO processed_messages (channel, message_id, processed_at)"
            " VALUES ($1, $2, $3) ON CONFLICT DO NOTHING RETURNING 1 AS claimed",
            [channel, message_id, _iso(now),
             _iso(now - timedelta(seconds=PROCESSED_RETENTION_SECONDS))],
        )
        return row is not None
