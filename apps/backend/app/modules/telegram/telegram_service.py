"""The Telegram door, wired to this server: one bot, speaking for any linked chat.

A chat speaks for the account whose link code it spent,
so every read and payment is scoped to that account. `STARK_TG_OWNER_EMAIL` is
only a fallback for a code minted without an account (the reminder loop's own
nudges); it is no longer what decides whose money a chat can move. It refuses
every update until both Telegram secrets are set (fail closed).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.common.api_error import ApiError
from app.database import neon
from app.modules.account.account_service import AccountService
from app.modules.control.control_service import ControlService
from app.modules.telegram import telegram
from app.modules.telegram.identity_repository import IdentityRepository
from app.modules.turnlog.turn_logger import TurnLogger
from app.modules.voice import stt
from app.shared.services.api_config_service import ApiConfigService


class TelegramService:
    def __init__(self, config: ApiConfigService, db: neon.Database,
                 identities: IdentityRepository, accounts: AccountService,
                 controls: ControlService) -> None:
        self.config = config
        self.db = db
        self.accounts = accounts
        self._owner_id: Optional[str] = None
        self.adapter = telegram.TelegramAdapter(
            agent=self,
            identities=identities,
            controls=controls,
            bot_token=config.telegram_bot_token,
            secret=config.telegram_webhook_secret,
            owner_user_id=self.owner_account_id,
            # Voice notes go through the same Whisper the web door uses; OGG is
            # Telegram's own format.
            transcribe=lambda clip: stt.transcribe(clip, mime="audio/ogg"),
            on_turn=self.log_turn,
            log=lambda line: print(f"  [tg] {line}"),
        )

    def owner_account_id(self) -> str:
        """The bot's account, looked up by email. Only a hit is cached, so an owner
        who signs up after boot is found on the next update."""
        if self._owner_id is None and self.config.telegram_owner_email:
            row = self.db.one("SELECT id FROM accounts WHERE lower(email) = $1",
                              [self.config.telegram_owner_email])
            self._owner_id = row["id"] if row else None
        return self._owner_id or ""

    def tell(self, account_id: str, text: str) -> int:
        """Send `text` to every Telegram chat linked to this account; returns how many
        took it. Without a bot token nothing is sent."""
        token = self.adapter.bot_token
        if not token:
            return 0
        sent = 0
        for ident in self.adapter.identities.identities_for(account_id):
            if ident["channel"] != telegram.CHANNEL:
                continue
            try:
                chat_id = int(ident["channel_user_id"])
            except ValueError:
                continue
            sent += telegram.send_message(chat_id, text, bot_token=token)
        return sent

    def tell_owner(self, text: str) -> int:
        """Operator alerts: the bot owner's (`STARK_TG_OWNER_EMAIL`) linked chats."""
        owner = self.owner_account_id()
        return self.tell(owner, text) if owner else 0

    def respond(self, user_id: str, said: str, thread: str) -> Any:
        """The linked account's agent — the same `Agent.respond` every door uses."""
        return self.accounts.state(user_id).agent.respond(said, thread=thread)

    def link_code(self, account_id: str) -> dict[str, Any]:
        try:
            payload = self.adapter.link_code(account_id)
        except telegram.TelegramError as err:
            raise ApiError(err.status, err.code, err.message) from err
        payload["user_id"] = account_id
        return payload

    def webhook(self, raw: bytes, secret_header: Optional[str]) -> dict[str, Any]:
        """Verified before parsing: the secret check runs on exactly what was sent."""
        try:
            self.adapter.verify_secret(secret_header)
        except telegram.TelegramError as err:
            raise ApiError(err.status, err.code, err.message) from err
        try:
            update = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "bad_update", "Body is not JSON.") from None
        return self.adapter.handle_update(update)

    def log_turn(self, turn: dict) -> None:
        """Write one Telegram exchange to the same log `/v1/voice` writes to, plus
        `channel`, so both doors read back the same way."""
        result = turn.get("result")
        owner = turn.get("account_id") or self.owner_account_id()
        TurnLogger.turn(
            agent=self.accounts.state(owner).agent if owner else None,
            outcome=turn.get("outcome") or "answered",
            clip=None, mime=None,
            heard=turn.get("heard") or "",
            said=turn.get("said"),
            payload={
                "reply": getattr(result, "reply", None) or turn.get("reply"),
                "actions": getattr(result, "actions", None),
                "code": getattr(result, "code", None),
                "receipt_id": getattr(result, "receipt_id", None),
                "token": getattr(result, "token", None),
            },
            speak=None,
            conversation=getattr(result, "conversation", None),
            channel=telegram.CHANNEL,
        )
