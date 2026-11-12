"""Paying a saved bill: the contract's checks, then the purchase.

Shared by `POST /v1/payments` and the agent, so both refuse with the same codes in
the same order: the per-payment cap first, then the monthly cap, then the balance.
The purchase itself, and the charge that only follows a delivery, happen in
`PaymentService`, which records the intent before it calls the vendor.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.modules.account.account_service import AccountService
from app.modules.agent import policy
from app.modules.bill.bill_service import BillService
from app.modules.payment import payment_service
from app.modules.payment.payment_service import PaymentService
from app.modules.receipt import receipt_repository
from app.modules.settings.settings_service import SettingsService
from app.modules.wallet.wallet_service import WalletService

log = logging.getLogger("stark.payments")
# A purchase that came back pending is first re-read this long after it was made.
SETTLE_AFTER_MINUTES = 1


class BillPaymentService:
    def __init__(self, accounts: AccountService, bills: BillService,
                 wallet: WalletService, payments: PaymentService,
                 settings: SettingsService) -> None:
        self.accounts = accounts
        self.bills = bills
        self.wallet = wallet
        self.payments = payments
        self.settings = settings

    def pay(self, account_id: str, bill_id: str, amount: int, *,
            approved: bool = False) -> dict[str, Any]:
        """`approved` is the owner lifting the caps for this one payment (see
        `ApprovalService`); the pause and the balance still apply, and the vault
        is signed through its owner-only `pay_approved`."""
        bill = self.bills.get(account_id, bill_id)
        if bill.get("needs_confirmation"):
            raise ApiError(409, "bill_unconfirmed",
                           f"Confirm {bill['label']} in the app before paying it.")
        state = self.accounts.state(account_id)
        if state.paused_at is not None:
            raise ApiError(423, policy.PAUSED, policy.MESSAGES[policy.PAUSED])
        if amount <= 0:
            raise ApiError(400, "bad_amount", "amount_ngn must be positive")

        # The limits and the balance cover what the user actually pays: the bill
        # and Stark's fee on it.
        fee = self.settings.fee_for(bill["kind"])
        total = amount + fee
        limits = state.limits
        wallet = self.wallet.balance(account_id)
        spent, balance = wallet["spent_ngn"], wallet["balance_ngn"]
        if not approved and total > limits.per_payment_cap_ngn:
            raise ApiError(409, "over_per_payment_cap",
                           "That's over the most you allow in one go.",
                           {"amount_ngn": total, "cap_ngn": limits.per_payment_cap_ngn})
        if not approved and spent + total > limits.monthly_cap_ngn:
            raise ApiError(409, "over_cap", "That would go over your monthly limit.", {
                "cap_ngn": limits.monthly_cap_ngn,
                "spent_ngn": spent,
                "remaining_ngn": max(limits.monthly_cap_ngn - spent, 0),
            })
        if total > balance:
            raise ApiError(409, "insufficient_balance",
                           "Not enough in your wallet. Add money first.",
                           {"balance_ngn": balance, "amount_ngn": total})

        try:
            receipt = self.payments.pay(account_id, bill, amount, approved=approved,
                                        fee_ngn=fee)
        except payment_service.SpendError as err:
            status = 409 if err.code == payment_service.INSUFFICIENT_BALANCE else 502
            raise ApiError(status, err.code, err.message, err.detail) from err

        if receipt.get("status") == "delivered":
            self.bills.apply_delivery(account_id, receipt)
        return receipt_repository.api_shape(receipt)

    def settle_pending(self) -> None:
        """Settle purchases that came back pending, without waiting for a retry.

        Run by the money loop. Each one is settled exactly as a retry would settle
        it; a delivery also updates its bill. One account failing does not stop the
        rest.
        """
        for receipt in self.payments.store.pending_purchases(
                Clock.ago(minutes=SETTLE_AFTER_MINUTES)):
            account_id = receipt["user_id"]
            try:
                bill = self.bills.get(account_id, receipt["bill_id"])
                settled = self.payments.settle(
                    account_id, receipt, token_required=bill["kind"] == "electricity")
            except payment_service.SpendError:
                continue  # failed at the vendor: the hold is back in the balance
            except Exception:
                log.exception("settling %s for %s failed", receipt["id"], account_id)
                continue
            if settled["status"] == "delivered":
                self.bills.apply_delivery(account_id, settled)

    def record_declined(self, account_id: str, bill_id: str, bill_label: str,
                        amount: int, reason: str) -> dict[str, Any]:
        """An activity row for a payment Stark refused or the owner denied.

        It never touches the wallet: `declined` is not a charge and not a spend.
        """
        return receipt_repository.api_shape(self.payments.store.create(account_id, {
            "id": f"rcpt_{uuid.uuid4().hex[:6]}",
            "request_id": f"dec_{uuid.uuid4().hex[:12]}",
            "bill_id": bill_id,
            "bill_label": bill_label,
            "meter": None,
            "amount_ngn": amount,
            "units": None,
            "token": None,
            "tx_hash": None,
            "status": "declined",
            "entry_type": "bill",
            "source": "Stark",
            "vendor": None,
            "vendor_code": None,
            "vendor_message": reason,
            "created_at": Clock.now_iso(),
        }))

    def recent(self, account_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.payments.recent(account_id, limit)
