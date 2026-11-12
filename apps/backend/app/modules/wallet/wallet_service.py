"""The wallet: what the balance is, and test-money top-ups.

Real money arrives through `DepositService` and leaves through `WithdrawalService`.
Test money exists for local runs and demos, and only while no payment rail is
configured: with Flutterwave keyed or a treasury key set, `POST /v1/wallet/topup`
refuses, so a deployed app cannot mint balance, and minted balance can never be
withdrawn as real USDC. A test top-up still credits the vault, so the two ledgers
agree even in a demo.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.modules.account.account_service import AccountService
from app.modules.receipt import receipt_repository
from app.modules.receipt.receipt_repository import ReceiptRepository
from app.modules.vault.vault_service import VaultService
from app.modules.wallet.dtos.top_up_dto import TopUpDto


class WalletService:
    def __init__(self, accounts: AccountService, receipts: ReceiptRepository,
                 vaults: VaultService, *, test_money: bool) -> None:
        self.accounts = accounts
        self.receipts = receipts
        self.vaults = vaults
        self.test_money = test_money

    def balance(self, account_id: str) -> dict[str, int]:
        """A missing wallet reads ₦0: the account has simply not been opened yet."""
        return self.receipts.wallet(account_id) or {"balance_ngn": 0, "spent_ngn": 0}

    def summary(self, account_id: str) -> dict[str, Any]:
        wallet = self.balance(account_id)
        cap = self.accounts.state(account_id).limits.monthly_cap_ngn
        return {
            "currency": "NGN",
            "balance_ngn": wallet["balance_ngn"],
            "spent_ngn": wallet["spent_ngn"],
            "monthly_cap_ngn": cap,
            "remaining_cap_ngn": max(cap - wallet["spent_ngn"], 0),
            "added_this_month_ngn": self.receipts.added_this_month(account_id),
        }

    def top_up(self, account_id: str, dto: TopUpDto) -> tuple[int, dict[str, Any]]:
        """Add test money. There is no payment provider yet, so nothing is collected:
        the entry says so in its source (a `source` in the body is ignored), and the
        app labels it as test money. Returns 200 for a repeated `request_id`."""
        if not self.test_money:
            raise ApiError(501, "not_available",
                           "Test money is off here. Add money by bank, card or crypto.")
        if dto.amount_ngn <= 0:
            raise ApiError(400, "bad_amount", "amount_ngn must be positive")
        request_id = dto.request_id or f"dep_{uuid.uuid4().hex[:12]}"
        existing = self.receipts.by_request_id(account_id, request_id)
        if existing is not None:
            return 200, {"wallet": self.summary(account_id),
                         "entry": receipt_repository.api_shape(existing)}
        entry, _ = self.receipts.record_deposit(account_id, {
            "id": f"rcpt_{uuid.uuid4().hex[:6]}",
            "request_id": request_id,
            "bill_id": "wallet",
            "bill_label": "Added money",
            "meter": None,
            "amount_ngn": dto.amount_ngn,
            "units": None,
            "token": None,
            "tx_hash": None,
            "status": "received",
            "entry_type": "deposit",
            "source": "Test money",
            "vendor": "ledger",
            "vendor_code": "000",
            "vendor_message": "deposit",
            "created_at": Clock.now_iso(),
        }, dto.amount_ngn)
        self.vaults.credit(account_id, dto.amount_ngn, request_id)
        return 201, {"wallet": self.summary(account_id),
                     "entry": receipt_repository.api_shape(entry)}
