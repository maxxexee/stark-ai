"""The push half of reminders: say so first when a renewal is close.

When an account has a bill inside its renewal window and a Telegram chat linked,
Stark nudges that account's chats instead of waiting to be asked. Every linked
account, each about its own bills. The same facts are
always in `/v1/state` and the agent's snapshot, so nothing depends on this loop.
"""

from __future__ import annotations

import logging
import threading

from app.modules.account.account_service import AccountService
from app.modules.reminder import reminders
from app.modules.telegram import telegram
from app.modules.telegram.telegram_service import TelegramService

log = logging.getLogger("stark.reminders")


class ReminderService:
    def __init__(self, accounts: AccountService, telegram_service: TelegramService) -> None:
        self.accounts = accounts
        self.telegram = telegram_service
        self.log = reminders.NotifyLog()

    def push_due(self, account_id: str) -> list[str]:
        """Nudge this account's linked Telegram chats about unclaimed renewals.

        Without a bot token nothing is claimed and nothing is sent — the caller (or
        a test) can still read what *would* go out. With one, each renewal is
        claimed before it is sent, so a chat is never nudged twice for one date.
        """
        state = self.accounts.state(account_id)
        # A paused Stark offering to pay would only be refused; stay quiet instead.
        if state.paused_at is not None:
            return []
        bills = state.bills.values()
        adapter = self.telegram.adapter
        if not adapter.bot_token:
            return [reminders.push_text(item) for item in reminders.due_soon(bills)]

        sent: list[str] = []
        for item in reminders.due_for_push(bills, log=self.log):
            text = reminders.push_text(item)
            self.telegram.tell(account_id, text)
            adapter.log(f"reminder: {text}")
            sent.append(text)
        return sent

    def push_all(self) -> int:
        """One pass over every account with a linked chat. One account failing (a
        bad bill, a database blip) does not stop the others. Returns how many
        nudges went out."""
        try:
            accounts = self.telegram.identities.linked_accounts(telegram.CHANNEL)
        except Exception:
            log.exception("reminder pass could not list linked accounts")
            return 0
        sent = 0
        for account_id in accounts:
            try:
                sent += len(self.push_due(account_id))
            except Exception:
                log.exception("reminders failed for account=%s", account_id)
        return sent

    def start(self, tick_seconds: int) -> threading.Event:
        """A daemon thread pushing every linked account's reminders; returns its stop
        event.

        Started by the app's lifespan, never on import, so a unit test does not
        inherit a background loop.
        """
        stop = threading.Event()

        def run() -> None:
            while not stop.wait(tick_seconds):
                self.push_all()

        threading.Thread(target=run, daemon=True, name="reminders").start()
        return stop
