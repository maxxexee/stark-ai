"""A payment, in the order it actually happens.

    policy check  →  THIS  →  receipt

Inside "this", in order:

0. **Can it be paid at all?** Stark's Flutterwave balance must cover it (`FloatService`), and
   the user's vault must authorise it (`VaultService` signs `pay`, or `pay_approved`
   for an amount the owner approved over the caps). Either refusal leaves nothing
   recorded or bought. A retry of a pending purchase skips this: it
   was authorised the first time, and signing again would spend twice onchain.
1. **Hold the money and record it before buying.** One statement takes the amount
   out of the balance and writes the receipt with a `request_id` and status
   `pending`, *before* the vendor is called — or refuses if the balance is short. So
   two payments at the same moment cannot both spend the same naira, and if the
   process dies mid-purchase the id survives and the purchase can be re-queried
   instead of duplicated (Flutterwave refuses a reused bill `reference`).
2. **Settle on the vendor's answer.** `delivered` turns the hold into spend; `failed`
   puts it back in the balance and gives the vault its money and allowance back
   (`refund`). Both are one statement that only moves a receipt still `pending`, so
   a retry and the background check (`settle`, from the money loop) can race on the
   same purchase and only one of them settles it.

A held amount is not spend: the monthly cap counts only delivered payments.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from app.common.clock import Clock
from app.modules.liquidity.float_service import FloatService
from app.modules.receipt import receipt_repository as receipts_mod
from app.modules.vault.vault_service import AuthorisationFailed, VaultService
from app.modules.vending import vending as vending_mod
from app.modules.receipt.receipt_repository import ReceiptRepository
from app.modules.vending.vending import VendingGateway, VendingOutcome

# Errors the HTTP layer turns into a response.
VENDOR_FAILED = "vendor_failed"
INSUFFICIENT_BALANCE = "insufficient_balance"
AUTHORISATION_FAILED = "authorisation_failed"
# A purchase Flutterwave never answered is given up after this long. It leaves the
# user uncharged whichever way it went; if it did land, Stark paid for it.
NO_ANSWER_MINUTES = 30


class SpendError(Exception):
    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class PaymentService:
    def __init__(
        self,
        store: ReceiptRepository,
        gateway: VendingGateway,
        *,
        vaults: VaultService | None = None,
        floats: FloatService | None = None,
        clock: Callable[[], str] = _now_iso,
    ):
        """`vaults` and `floats` are None only in tests that exercise the vendor
        path alone; the app always passes both (a `VaultService` with no chain
        configured authorises nothing and refuses nothing)."""
        self.store = store
        self.gateway = gateway
        self.vaults = vaults
        self.floats = floats
        self.clock = clock

    def pay(self, user_id: str, bill: dict, amount_ngn: int, *,
            approved: bool = False, fee_ngn: int = 0) -> dict:
        """Book a payment for one account. Returns the stored receipt row.

        `fee_ngn` is Stark's service fee: it is held, authorised onchain and refunded
        with the amount, but only `amount_ngn` is bought from the vendor.
        """
        total_ngn = amount_ngn + fee_ngn
        token_required = bill["kind"] == "electricity"
        pending = self.store.find_pending(user_id, bill["id"], amount_ngn)
        if pending is not None:
            return self.settle(user_id, pending, token_required=token_required)

        if self.floats is not None:
            self.floats.ensure_can_cover(amount_ngn)
        try:
            receipt, _ = self.store.record_debit(user_id, {
                "id": f"rcpt_{uuid.uuid4().hex[:6]}",
                "request_id": f"bill_{uuid.uuid4().hex[:20]}",
                "bill_id": bill["id"],
                "bill_label": bill["label"],
                "meter": str(bill.get("reference") or ""),
                "amount_ngn": amount_ngn,
                "fee_ngn": fee_ngn,
                "units": None,
                "token": None,
                "tx_hash": None,
                "status": vending_mod.PENDING,
                "vendor": None,
                "vendor_code": None,
                "vendor_message": None,
                "created_at": self.clock(),
            }, total_ngn)
        except ValueError:
            raise SpendError(INSUFFICIENT_BALANCE,
                             "There isn't enough in your balance for that.",
                             {"amount_ngn": total_ngn}) from None

        if self.vaults is not None:
            try:
                authorisation = self.vaults.authorise_payment(
                    user_id, str(bill.get("reference") or ""), total_ngn, approved=approved
                )
            except AuthorisationFailed as err:
                self.store.drop_hold(user_id, receipt["id"])
                raise SpendError(AUTHORISATION_FAILED, err.message) from err
            if authorisation is not None:  # None: no chain configured
                receipt = self.store.update(user_id, receipt["id"],
                                            tx_hash=authorisation.tx_hash)
                if authorisation.payment_id is not None:
                    self.vaults.record_payment(user_id, receipt["id"],
                                               authorisation.payment_id)

        outcome = self.gateway.buy(bill, amount_ngn, receipt["request_id"])
        return self._apply(user_id, receipt, outcome)

    def settle(self, user_id: str, pending: dict, *, token_required: bool) -> dict:
        """Ask the vendor about a pending purchase and settle it if it has an answer.

        Called by a retry of the same intent and by the money loop. A purchase the
        vendor never acknowledged is given up after `NO_ANSWER_MINUTES`.
        """
        if pending["vendor_ref"] is not None:
            outcome = self.gateway.requery(pending["vendor_ref"], pending["amount_ngn"],
                                           token_required=token_required)
        elif pending["created_at"] > Clock.ago(minutes=NO_ANSWER_MINUTES):
            return pending
        else:
            outcome = VendingOutcome(status=vending_mod.FAILED, code="no_answer",
                                     message="That payment didn't go through. "
                                             "Nothing was charged.")
        return self._apply(user_id, pending, outcome)

    def _apply(self, user_id: str, receipt: dict, outcome: VendingOutcome) -> dict:
        common = {
            "vendor": outcome.vendor,
            "vendor_code": outcome.code,
            "vendor_ref": outcome.vendor_ref,
            "vendor_message": outcome.message,
        }

        if outcome.status == vending_mod.FAILED:
            if self.store.finish(user_id, receipt["id"], vending_mod.FAILED,
                                 **common) is not None:
                self._give_back(user_id, receipt["id"])
            raise SpendError(VENDOR_FAILED, outcome.message, {"code": outcome.code})

        # A metered product that reports delivered with no token is not something to
        # charge for: it stays in flight for the next check. Airtime and TV
        # legitimately have no token, so they skip this.
        missing_token = outcome.token_required and not outcome.token
        if not outcome.ok or missing_token:
            return self.store.update(user_id, receipt["id"], **common)  # type: ignore[return-value]

        settled = self.store.finish(user_id, receipt["id"], vending_mod.DELIVERED,
                                    token=outcome.token, units=outcome.units, **common)
        if settled is None:  # the other caller settled it first
            return self.store.get(user_id, receipt["id"])  # type: ignore[return-value]
        if self.floats is not None:
            self.floats.check_level()
        return settled

    def _give_back(self, user_id: str, receipt_id: str) -> None:
        """The vendor did not deliver: return the vault's money and allowance."""
        if self.vaults is not None:
            self.vaults.refund_receipt(user_id, receipt_id)

    # --- read side -----------------------------------------------------------

    def recent(self, user_id: str, limit: int = 20) -> list[dict]:
        return [receipts_mod.api_shape(row) for row in self.store.recent(user_id, limit)]

    def wallet(self, user_id: str) -> dict[str, int]:
        return self.store.wallet(user_id) or {"balance_ngn": 0, "spent_ngn": 0}
