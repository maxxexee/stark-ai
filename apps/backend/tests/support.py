"""A throwaway account on the real database, for tests that store something.

The stores take an account id now, because accounts are real: every row belongs to
somebody. Tests do not care about that, they care about the receipt they just wrote,
so this binds the id once and lets the test call the store the way it always did.

Each account is created fresh (`test_<random>`) and deleted with `close()`, which
cascades through receipts, wallet and identities. So tests share a database without
sharing data — and without a second schema, a fixture file, or a local Postgres
container pretending to be the one the app actually uses.

The cost is honest and worth stating: these tests need `DATABASE_URL` and a network,
and each store call is a ~250 ms round trip.
"""

from __future__ import annotations

import secrets
from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from app.app_module import AppModule
from app.modules.agent import agent as agent_layer
from app.modules.agent.account_toolbox import AccountToolbox
from app.modules.settings.settings_service import DEFAULT_FEES_NGN
from app.database import neon
from app.decorators.auth_user import auth_guard
from app.main import create_app
from app.modules.account.account import Account
from app.modules.payment import payment_service
from app.modules.receipt import receipt_repository
from app.shared.services.api_config_service import ApiConfigService
from tests.regex_model import RegexModel

# The store methods that are scoped to an account. Everything else (`close`) is not.
_ACCOUNT_SCOPED = frozenset({
    "create", "update", "get", "by_request_id", "has_pending", "find_pending",
    "recent", "count", "wallet", "set_wallet", "record_deposit",
    "record_debit", "added_this_month", "finish", "drop_hold", "replace_all",
    "held_for_bills",
})


class BoundStore:
    """A `ReceiptRepository` with the account id filled in.

    Exists so a test can say `store.wallet()` rather than `store.wallet(ACCOUNT)`
    on every line, while the store itself stays unaware of who is calling.
    """

    def __init__(self, store: receipt_repository.ReceiptRepository, user_id: str) -> None:
        self.raw = store
        self.user_id = user_id

    def __getattr__(self, name: str):
        attribute = getattr(self.raw, name)
        if name not in _ACCOUNT_SCOPED:
            return attribute

        def scoped(*args: Any, **kwargs: Any):
            return attribute(self.user_id, *args, **kwargs)

        return scoped


class BoundPayments:
    """A `PaymentService` with the account id filled in."""

    def __init__(self, service: payment_service.PaymentService, user_id: str) -> None:
        self.raw = service
        self.user_id = user_id

    def pay(self, bill: dict, amount_ngn: int, **kwargs: Any) -> dict:
        return self.raw.pay(self.user_id, bill, amount_ngn, **kwargs)

    def recent(self, limit: int = 20) -> list[dict]:
        return self.raw.recent(self.user_id, limit)

    def wallet(self) -> dict[str, int]:
        return self.raw.wallet(self.user_id)


class TempAccount:
    """A real account row, a bound store, and a cleanup that leaves no trace."""

    def __init__(self, *, balance_ngn: int = 0, spent_ngn: int = 0,
                 db: neon.Database | None = None) -> None:
        self.db = db or neon.open_database()
        self.id = f"test_{secrets.token_hex(8)}"
        self.db.query(
            "INSERT INTO accounts (id, auth_user_id, email, name, created_at)"
            " VALUES ($1, $2, $3, $4, $5)",
            [self.id, f"auth-{self.id}", f"{self.id}@test.invalid", "Test Account",
             "2026-10-26T00:00:00Z"],
        )
        self.store = BoundStore(receipt_repository.ReceiptRepository(self.db), self.id)
        if balance_ngn or spent_ngn:
            self.store.set_wallet(balance_ngn, spent_ngn)

    def payments(self, gateway) -> BoundPayments:
        return BoundPayments(
            payment_service.PaymentService(self.store.raw, gateway), self.id
        )

    def close(self) -> None:
        self.db.query("DELETE FROM accounts WHERE id = $1", [self.id])


class ApiHarness:
    """The real app on the real database, signed in as a `TempAccount`.

    Routes run exactly as a client sees them (DTOs, error filter, status codes);
    only the auth guard is swapped, so no Neon Auth session is needed. `opened`
    says whether the account counts as already opened, which is what the session
    lookup normally reports: a new account is opened (₦0 wallet) on first sight.
    """

    def __init__(self, account: TempAccount, *, opened: bool = True,
                 fees: dict[str, int] | None = None, live_limits: bool = False,
                 **config: Any) -> None:
        settings = replace(ApiConfigService.from_env(), reminders_enabled=False, **config)
        self.account = account
        self.opened = opened
        self.module = AppModule(settings, account.db)
        # Fees are global settings in the shared database, so tests never read or
        # write the real row: each harness charges only the fees it names.
        named = {**dict.fromkeys(DEFAULT_FEES_NGN, 0), **(fees or {})}
        self.module.settings_service.fees = lambda: named
        # Operator limits are global too: a harness keeps them in memory, starting at
        # their defaults, unless the test is about the stored rows themselves.
        if not live_limits:
            self.module.operator_limits.db = None
        # No test holds a signer for real money: the treasury key signs USDC on
        # mainnet whatever STARK_NETWORK says, and dev secrets carry one.
        self.module.crypto_withdrawals.treasury = None
        # Every agent this app builds talks to the scripted model, never NEAR AI.
        self.module.accounts.build_agent = lambda account_id, limits: agent_layer.Agent(
            model=RegexModel(), toolbox=AccountToolbox(account_id, self.module),
            limits=limits)
        app = create_app(self.module)
        app.dependency_overrides[auth_guard] = self._sign_in
        self.client = TestClient(app)

    def _sign_in(self) -> Account:
        self.module.accounts.state(self.account.id, opened=self.opened)
        return Account(id=self.account.id, email=f"{self.account.id}@test.invalid",
                       name="Test Account")

    def state(self):
        """This account's in-process state (bills, caps, agent)."""
        return self.module.accounts.state(self.account.id, opened=self.opened)

    def restart(self) -> None:
        """Forget the in-process copy, as a fresh server process would."""
        self.module.accounts.forget(self.account.id)

    def sell_with(self, bills: "FakeBills") -> None:
        """Buy through a fake Flutterwave, as a keyed app would through the real one."""
        self.module.floats.flutterwave = bills
        self.module.bill_payments.payments.gateway.client = bills


# --- Flutterwave, faked at its client ------------------------------------------------


def catalogue_row(biller_code: str, name: str, item_code: str, item_name: str, amount: int,
                  *, airtime: bool = False) -> dict[str, Any]:
    """One `GET /v3/bill-categories` row, in the shape Flutterwave answers with."""
    return {"biller_code": biller_code, "name": name, "item_code": item_code,
            "biller_name": item_name, "short_name": item_name, "amount": amount,
            "is_airtime": airtime, "country": "NG", "label_name": "Mobile Number",
            "fee": 0}


# A slice of the catalogue the test API returned on 2026-11-03: one biller of each
# kind, plus the second Glo airtime item and a repeated row, which the real one has.
CATALOGUE = [
    catalogue_row("BIL099", "MTN VTU", "AT099", "AIRTIME", 0, airtime=True),
    catalogue_row("BIL102", "GLO NIGERIA", "AT133", "GLO VTU", 0, airtime=True),
    catalogue_row("BIL102", "GLO NIGERIA", "AT102", "GLO VTU", 0, airtime=True),
    catalogue_row("BIL103", "9MOBILE NIGERIA", "AT103", "9MOBILE VTU", 0, airtime=True),
    catalogue_row("BIL104", "MTN DATA BUNDLE", "MD107", "MTN 1.5 GB", 1000),
    catalogue_row("BIL104", "MTN DATA BUNDLE", "MD108", "MTN 3.5 GB", 2000),
    catalogue_row("BIL104", "MTN DATA BUNDLE", "MD107", "MTN 1.5 GB", 1000),
    catalogue_row("BIL119", "DSTV", "CB140", "DSTV Premium", 14600),
    catalogue_row("BIL119", "DSTV", "CB141", "DSTV Access", 1800),
    catalogue_row("BIL123", "STARTIMES", "CB260", "BASIC - One Month", 1700),
    catalogue_row("BIL113", "IKEJA DISCO ELECTRICITY BILLS", "UB159", "IKEDC  PREPAID", 0),
    catalogue_row("BIL113", "IKEJA DISCO ELECTRICITY BILLS", "UB160", "IKEDC  POSTPAID", 0),
    # Live mode (2026-11-12) names discos differently, and Jos says "Prepaid" only in
    # the item name.
    catalogue_row("BIL112", "EKEDC PREPAID TOPUP", "UB157", "EKEDC PREPAID TOPUP", 0),
    catalogue_row("BIL116", "PHC DISCO  PREPAID TOPUP", "UB633", "PHC DISCO  PREPAID TOPUP", 0),
    catalogue_row("BIL215", "JOS DISCO ELECTRICITY BILLS", "UB676", "JOS DISCO Prepaid", 0),
    catalogue_row("BIL140", "BEDC Prepaid Payment", "UB300", "BEDC Prepaid Payment", 0),
    catalogue_row("BIL141", "PORT HARCOURT DISCO ELECTRICITY BILLS", "UB301", "PHED PREPAID", 0),
    catalogue_row("BIL130", "Federal Inland Revenue Service", "TP214", "FIRS Tax", 0),
]


class FakeBills:
    """Flutterwave's bill endpoints. `outcome` is what the status read says next."""

    test_mode = True

    def __init__(self, outcome: str = "successful",
                 extra: str | None = "TOKEN11472398570712345678") -> None:
        from app.modules.flutterwave.flutterwave import FlutterwaveError

        self.error = FlutterwaveError
        self.outcome = outcome
        self.extra = extra
        self.paid: list[dict[str, Any]] = []
        self.read: list[str] = []
        self.placed: set[str] = set()
        self.refuse: Any = None
        # The order is placed but its answer never arrives (a timeout).
        self.lose_answer = False
        # Raised by every status read, e.g. Flutterwave unreachable.
        self.refuse_reads: Any = None

    def ngn_balance(self) -> int:
        return 500_000

    def pay_bill(self, **order: Any) -> dict[str, Any]:
        if self.refuse is not None:
            raise self.refuse
        self.paid.append(order)
        # A purchase reads back by Flutterwave's `tx_ref` or by our `reference`.
        self.placed.update({f"CF-FLYAPI-{order['reference']}", order["reference"]})
        if self.lose_answer:
            raise self.error(0, "Could not reach Flutterwave: timed out")
        return {"tx_ref": f"CF-FLYAPI-{order['reference']}", "reference": "247891569224",
                "amount": order["amount_ngn"], "code": "200"}

    def bill_status(self, tx_ref: str) -> dict[str, Any]:
        self.read.append(tx_ref)
        if self.refuse_reads is not None:
            raise self.refuse_reads
        if tx_ref not in self.placed:
            raise self.error(400, "Transaction not found")
        delivered = self.outcome == "successful"
        return {"status": self.outcome, "code": "200" if delivered else "400",
                "extra": self.extra if delivered else None, "tx_ref": tx_ref}


def use_catalogue() -> None:
    from app.modules.vending.catalog import CATALOG

    CATALOG.use(lambda: CATALOGUE)


use_catalogue()
