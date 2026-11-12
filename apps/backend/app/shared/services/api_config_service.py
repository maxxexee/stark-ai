"""Every setting the HTTP layer reads, parsed once at boot.

The library modules (vending, voice, chain, telegram) still read their own
variables: each one documents and tests what it does when its key is absent, and
routing all of that through here would only add a hop. This holds what the app
itself decides on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from app.shared.services.money_config import MoneyConfig


@dataclass(frozen=True)
class ApiConfigService:
    host: str
    port: int
    version: str
    stub_reset_enabled: bool
    reminders_enabled: bool
    reminder_tick_seconds: int
    telegram_bot_token: Optional[str]
    telegram_webhook_secret: Optional[str]
    telegram_owner_email: str
    telegram_owner_account_id: Optional[str]
    admin_key: Optional[str]
    money: MoneyConfig

    @classmethod
    def from_env(cls) -> "ApiConfigService":
        return cls(
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8000")),
            version="0.4.0",
            stub_reset_enabled=os.environ.get("STARK_STUB_RESET") == "1",
            reminders_enabled=os.environ.get("STARK_REMINDERS", "1") != "0",
            reminder_tick_seconds=int(os.environ.get("STARK_REMINDER_TICK", "300")),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            telegram_webhook_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET"),
            telegram_owner_email=(os.environ.get("STARK_TG_OWNER_EMAIL") or "").strip().lower(),
            telegram_owner_account_id=(os.environ.get("STARK_TG_OWNER_ACCOUNT_ID") or "").strip()
            or None,
            admin_key=_admin_key(os.environ.get("STARK_ADMIN_KEY")),
            money=MoneyConfig.from_env(),
        )


ADMIN_KEY_MIN_LENGTH = 32


def _admin_key(raw: Optional[str]) -> Optional[str]:
    """A short admin key is refused at boot rather than accepted: it is the only
    thing between the internet and every balance Stark holds."""
    key = (raw or "").strip()
    if not key:
        return None
    if len(key) < ADMIN_KEY_MIN_LENGTH:
        raise ValueError(
            f"STARK_ADMIN_KEY must be at least {ADMIN_KEY_MIN_LENGTH} characters "
            "(openssl rand -hex 32)"
        )
    return key
