"""Each account's bills, caps and agent, loaded on first sight and kept warm.

Loading is a no-op once the account is cached. That matters more than it looks:
rebuilding on every request handed each request its own copy of the bills, so a
duplicate check passed and a bill added a second ago was missing.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from app.common.clock import Clock
from app.modules.account.account import AccountState
from app.modules.account.account_repository import AccountRepository
from app.modules.agent.toolbox import Limits
from app.modules.auth.auth_service import AuthService
from app.modules.receipt.receipt_repository import ReceiptRepository


class AccountService:
    # Every account starts with these caps until it sets its own. ₦10,000, not the
    # ₦5,000 the first draft used: a mid-range DStv bouquet costs more than ₦5,000,
    # so a ₦5,000 per-payment cap would make the TV bill unpayable.
    MONTHLY_CAP_NGN = 30_000
    PER_PAYMENT_CAP_NGN = 10_000

    def __init__(self, auth: AuthService, accounts: AccountRepository,
                 receipts: ReceiptRepository,
                 build_agent: Callable[[str, Limits], object]) -> None:
        self.auth = auth
        self.accounts = accounts
        self.receipts = receipts
        self.build_agent = build_agent
        self._states: dict[str, AccountState] = {}
        self._lock = threading.Lock()

    def state(self, account_id: str, *, opened: bool = False) -> AccountState:
        """This account's state, loading it (and opening a new account) on first sight.

        `opened` is what the session lookup already knows; passing it saves the
        extra query that would otherwise check whether the account needs opening.
        """
        with self._lock:
            loaded = self._states.get(account_id)
        if loaded is not None:
            return loaded

        bills = self.accounts.bills(account_id)
        state = AccountState(bills=bills, limits=self._limits_for(account_id, bills),
                             paused_at=self.accounts.paused_at(account_id))
        with self._lock:
            # Two first requests can race here; the first one in wins.
            state = self._states.setdefault(account_id, state)
        if state.agent is None:
            state.agent = self.build_agent(account_id, state.limits)
        if not opened and self.auth.needs_opening(account_id):
            self._open(account_id)
        return state

    def forget(self, account_id: str) -> None:
        with self._lock:
            self._states.pop(account_id, None)

    def rebuild_limits(self, account_id: str, *, monthly_cap_ngn: Optional[int] = None,
                       per_payment_cap_ngn: Optional[int] = None) -> Limits:
        """Replace this account's caps (and the agent's copy), storing any new cap.

        The meter allowlist is always re-derived from the bills, so adding or
        removing a bill re-scopes what the agent may pay in the very next turn.
        """
        state = self.state(account_id)
        previous = state.limits
        state.limits = Limits(
            monthly_cap_ngn=(previous.monthly_cap_ngn if monthly_cap_ngn is None
                             else monthly_cap_ngn),
            per_payment_cap_ngn=(previous.per_payment_cap_ngn if per_payment_cap_ngn is None
                                 else per_payment_cap_ngn),
            allowed_meters=self._meters(state.bills),
        )
        state.agent.limits = state.limits
        if monthly_cap_ngn is not None or per_payment_cap_ngn is not None:
            self.accounts.set_limits(account_id, state.limits.monthly_cap_ngn,
                                     state.limits.per_payment_cap_ngn)
        return state.limits

    def _limits_for(self, account_id: str, bills: dict[str, dict]) -> Limits:
        stored = self.accounts.limits(account_id)
        monthly, per = stored or (self.MONTHLY_CAP_NGN, self.PER_PAYMENT_CAP_NGN)
        return Limits(monthly_cap_ngn=monthly, per_payment_cap_ngn=per,
                                  allowed_meters=self._meters(bills))

    @staticmethod
    def _meters(bills: dict[str, dict]) -> frozenset:
        """What may be paid: every saved reference."""
        return frozenset(str(b["reference"]) for b in bills.values()
                         if b.get("reference"))

    def _open(self, account_id: str) -> None:
        """Give a brand-new account an empty ₦0 wallet, exactly once.

        It used to be handed the artboard's three bills, ₦64,200 and six receipts,
        so a real person's first screen was somebody else's meter. `seeded_at`
        marks the account as opened.
        """
        self.receipts.set_wallet(account_id, 0, 0)
        self.auth.mark_seeded(account_id, Clock.now_iso())
