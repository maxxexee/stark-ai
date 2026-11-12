"""The Telegram door, wired to this server: one bot, speaking for any linked chat.

A chat speaks for the account whose link code it spent, so every read, payment and
reminder is scoped to that account. There is no bot owner: operator alerts live on
the admin page (`OperatorAlerts`), not in anyone's chat. It refuses every update
until both Telegram secrets are set (fail closed).
"""

from __future__ import annotations

import json
import logging
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

log = logging.getLogger("stark.telegram")


class TelegramService:
    def __init__(self, config: ApiConfigService, db: neon.Database,
                 identities: IdentityRepository, accounts: AccountService,
                 controls: ControlService) -> None:
        self.config = config
        self.db = db
        self.accounts = accounts
        self.identities = identities
        self.adapter = telegram.TelegramAdapter(
            agent=self,
            identities=identities,
            controls=controls,
            bot_token=config.telegram_bot_token,
            secret=config.telegram_webhook_secret,
            # The adapter transcodes Telegram's OGG to WAV before this is called, so the
            # clip is sent as the WAV it is. Labelling it audio/ogg made Whisper reject
            # every voice note ("I cannot hear voice notes right now").
            transcribe=stt.transcribe,
            on_turn=self.log_turn,
            log=log.info,
        )

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

    def linked_chats(self, account_id: str) -> list[dict[str, Any]]:
        """The chats that speak for this account, as the Connect screen lists them.

        `chat_hint` keeps only the last four digits for display. The full id comes
        back too, because it is what Remove names; it is this account's own chat.
        """
        return [
            {
                "channel": ident["channel"],
                "channel_user_id": ident["channel_user_id"],
                "chat_hint": f"•••• {ident['channel_user_id'][-4:]}",
                "display_name": ident["display_name"],
                "linked_at": ident["linked_at"],
            }
            for ident in self.identities.identities_for(account_id)
        ]

    def unlink_chat(self, account_id: str, channel: str, channel_user_id: str) -> dict[str, Any]:
        """Remove a chat from this account, from the app. Another account's chat is
        `unknown_identity`, exactly like one that does not exist."""
        if not self.identities.unlink_for(account_id, channel, channel_user_id):
            raise ApiError(404, "unknown_identity", "No linked chat with that id.")
        return {"unlinked": True, "channel": channel, "channel_user_id": channel_user_id}

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
        account_id = turn.get("account_id")
        TurnLogger.turn(
            # The linked chat's account only: an unlinked chat's turn is nobody's.
            account_id=account_id,
            agent=self.accounts.state(account_id).agent if account_id else None,
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
