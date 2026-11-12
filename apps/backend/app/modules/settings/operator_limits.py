"""Operator limits: the caps, thresholds and rate settings the owner sets on the admin page.

Each limit has a default, its environment variable when that is set, else the
built-in value below. The owner can override any of them from the admin page. An
override is a `limit:<key>` row in the `settings` table, beside the fees, so a
change applies without a deploy.

Consumers ask at decision time (`limits.get("withdraw_daily_ngn")`), never at boot.
The stored overrides are kept for 15 seconds, so a change reaches every process
within that; the process that saved it sees it at once.

Every value is a whole number. `usdc_rate_max_move_pct` is a percentage; its
variable was a fraction before (`STARK_USDC_RATE_MAX_MOVE=0.15`), so a value under 1
there is read as one.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.database import neon

log = logging.getLogger("stark.limits")

CACHE_SECONDS = 15.0
PREFIX = "limit:"


@dataclass(frozen=True)
class Limit:
    key: str
    label: str
    unit: str
    env: str
    default: int
    minimum: int
    maximum: int


# The admin page shows them in this order.
LIMITS = (
    Limit("withdraw_daily_ngn", "Bank withdrawals per account per day", "₦",
          "STARK_WITHDRAW_DAILY_NGN", 200_000, 0, 50_000_000),
    Limit("bank_lookups_per_day", "Bank name lookups per account per day", "count",
          "STARK_BANK_LOOKUPS_PER_DAY", 20, 1, 1_000),
    Limit("crypto_withdraw_max_ngn", "Largest single crypto withdrawal", "₦",
          "STARK_CRYPTO_WITHDRAW_MAX_NGN", 200_000, 1_000, 50_000_000),
    Limit("crypto_withdraw_max_usdc", "Largest single crypto withdrawal in USDC", "USDC",
          "STARK_CRYPTO_WITHDRAW_MAX_USDC", 200, 1, 100_000),
    Limit("crypto_withdraw_daily_ngn", "Crypto withdrawals per day, all accounts", "₦",
          "STARK_CRYPTO_WITHDRAW_DAILY_NGN", 1_000_000, 0, 500_000_000),
    Limit("crypto_withdraw_user_daily_ngn", "Crypto withdrawals per account per day", "₦",
          "STARK_CRYPTO_WITHDRAW_USER_DAILY_NGN", 200_000, 0, 50_000_000),
    Limit("card_hold_hours", "Hold on card deposits before withdrawal", "hours",
          "STARK_CARD_HOLD_HOURS", 72, 0, 720),
    Limit("usdc_rate_min", "Lowest USDC rate accepted", "₦ per USDC",
          "STARK_USDC_RATE_MIN", 500, 1, 100_000),
    Limit("usdc_rate_max", "Highest USDC rate accepted", "₦ per USDC",
          "STARK_USDC_RATE_MAX", 5_000, 1, 100_000),
    Limit("usdc_rate_max_move_pct", "Largest USDC rate move accepted", "%",
          "STARK_USDC_RATE_MAX_MOVE", 15, 1, 100),
    Limit("usdc_spread_ngn", "Stark's spread on each USDC conversion", "₦ per USDC",
          "STARK_USDC_NGN_SPREAD", 10, 0, 1_000),
    Limit("usdc_rate_pinned", "Pinned USDC rate (0 = use Paycrest)", "₦ per USDC",
          "STARK_USDC_NGN_RATE", 0, 0, 100_000),
    Limit("float_low_ngn", "Alert when the Flutterwave balance is under", "₦",
          "STARK_FLOAT_LOW_NGN", 100_000, 0, 1_000_000_000),
    Limit("treasury_low_usdc", "Alert when the treasury holds less than", "USDC",
          "STARK_TREASURY_LOW_USDC", 100, 0, 10_000_000),
    Limit("speak_per_minute", "Speech requests per account per minute", "count",
          "STARK_SPEAK_PER_MINUTE", 30, 1, 1_000),
    Limit("telemetry_per_minute", "Meter readings per account per minute", "count",
          "STARK_TELEMETRY_PER_MINUTE", 120, 1, 10_000),
)
BY_KEY = {limit.key: limit for limit in LIMITS}


class OperatorLimits:
    def __init__(self, db: Optional[neon.Database],
                 env: Mapping[str, str] = os.environ) -> None:
        """`db` is None only for `fixed`, which keeps its values in memory."""
        self.db = db
        self.defaults = {limit.key: _env_default(limit, env) for limit in LIMITS}
        self._stored: dict[str, int] = {}
        self._read_at: Optional[float] = None
        self._lock = threading.Lock()

    @classmethod
    def fixed(cls, **values: int) -> OperatorLimits:
        """In memory, for tests: each named limit as given, the rest at the built-in
        default. The environment is not read, so a test means the same on every box."""
        unknown = sorted(set(values) - BY_KEY.keys())
        if unknown:
            raise KeyError(f"no such limit: {', '.join(unknown)}")
        limits = cls(None, env={})
        limits._stored = dict(values)
        return limits

    # --- reading --------------------------------------------------------------

    def get(self, key: str) -> int:
        """The owner's value, else the default. An unknown key is a KeyError: it is
        a typo in the code, not something a request can send."""
        return self.stored().get(key, self.defaults[key])

    def stored(self) -> dict[str, int]:
        """The owner's overrides, read from the database at most every 15 seconds.

        Read under the lock, so a burst of requests after the cache runs out makes
        one query, not one each."""
        with self._lock:
            fresh = self._read_at is not None \
                and time.monotonic() - self._read_at < CACHE_SECONDS
            if self.db is None or fresh:
                return self._stored
            rows = self.db.query(
                "SELECT key, value FROM settings WHERE key LIKE 'limit:%'"
            )
            # A row an older release wrote for a limit that no longer exists is ignored.
            self._stored = {
                key: int(row["value"]) for row in rows
                if (key := row["key"].removeprefix(PREFIX)) in BY_KEY
            }
            self._read_at = time.monotonic()
            return self._stored

    def all(self) -> list[dict[str, Any]]:
        """Every limit for the admin page, in `LIMITS` order."""
        stored = self.stored()
        return [
            {"key": limit.key, "label": limit.label, "unit": limit.unit,
             "value": stored.get(limit.key, self.defaults[limit.key]),
             "default": self.defaults[limit.key], "minimum": limit.minimum,
             "maximum": limit.maximum, "overridden": limit.key in stored}
            for limit in LIMITS
        ]

    # --- the owner's changes ----------------------------------------------------

    def set(self, changes: Mapping[str, Optional[int]]) -> list[dict[str, Any]]:
        """Save the owner's changes. `None` drops the override, so the default
        applies again. Everything is checked before anything is saved: a refused
        change saves nothing."""
        unknown = sorted(set(changes) - BY_KEY.keys())
        if unknown:
            raise ApiError(400, "unknown_limit",
                           f"There is no limit called {', '.join(unknown)}.")
        for key, value in changes.items():
            limit = BY_KEY[key]
            if value is not None and not limit.minimum <= value <= limit.maximum:
                raise ApiError(400, "bad_limit",
                               f"{limit.label} must be between {limit.minimum:,} and "
                               f"{limit.maximum:,}.")
        self._forget()
        before = {key: self.get(key) for key in BY_KEY}
        after = {**before, **{key: self.defaults[key] if value is None else value
                              for key, value in changes.items()}}
        if after["usdc_rate_min"] >= after["usdc_rate_max"]:
            raise ApiError(400, "bad_limit",
                           "The lowest USDC rate accepted must be under the highest.")
        for key, value in changes.items():
            self._save(key, value)
            log.info("operator limit %s changed from %s to %s%s", key, before[key],
                     after[key], " (default)" if value is None else "")
        self._forget()
        return self.all()

    def _save(self, key: str, value: Optional[int]) -> None:
        if self.db is None:
            if value is None:
                self._stored.pop(key, None)
            else:
                self._stored[key] = value
            return
        if value is None:
            self.db.query("DELETE FROM settings WHERE key = $1", [PREFIX + key])
            return
        self.db.query(
            "INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, $3)"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,"
            " updated_at = EXCLUDED.updated_at",
            [PREFIX + key, value, Clock.now_iso()],
        )

    def _forget(self) -> None:
        with self._lock:
            self._read_at = None


def _env_default(limit: Limit, env: Mapping[str, str]) -> int:
    """The variable when set, else the built-in default. A fractional value is
    truncated to a whole number, except the move limit's old fraction form."""
    raw = (env.get(limit.env) or "").strip()
    if not raw:
        return limit.default
    value = Decimal(raw)
    if limit.key == "usdc_rate_max_move_pct" and value < 1:
        value *= 100
    return int(value)
