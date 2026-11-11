"""Withdrawing to a bank, through Flutterwave transfers.

    resolve the account name → hold the money → transfer
    → `transfer.completed` SUCCESSFUL (done) or FAILED (money comes back)

The money leaves the balance the moment the withdrawal is asked for (one
statement: debit plus the activity entry), and the vault is debited with the same
reference. Holding it first is what stops a user spending money that is already on
its way to their bank.

The withdrawal id is the transfer's `reference`. A transfer that timed out may still
have gone through, so every send first asks Flutterwave whether it holds that
reference, and a refusal only returns the money once Flutterwave confirms it doesn't.
Until Flutterwave has taken it, the withdrawal is `sending`; the money loop retries
those, and re-reads `processing` ones in case a webhook was missed.

Returning money is the mirror image of taking it: a credit keyed `<withdrawal>-r`,
and a vault `fund` with the same reference, so a repeated failure event returns it
once.

`hold`, `mark_paid` and `give_back` are the ledger every withdrawal shares; a
crypto payout (`crypto_withdrawal_service.py`) uses them too, so both methods
take and return money by exactly the same rules.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Optional

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.database import neon
from app.modules.flutterwave.flutterwave import FlutterwaveClient, FlutterwaveError
from app.modules.receipt.receipt_repository import ReceiptRepository
from app.modules.vault.vault_service import VaultService

log = logging.getLogger("stark.withdrawals")

MIN_WITHDRAWAL_NGN = 100
UNIQUE_VIOLATION = "23505"


class WithdrawalService:
    def __init__(self, db: neon.Database, receipts: ReceiptRepository, vaults: VaultService,
                 flutterwave: Optional[FlutterwaveClient]) -> None:
        self.db = db
        self.receipts = receipts
        self.vaults = vaults
        self.flutterwave = flutterwave
        self._banks: Optional[tuple[float, list[dict[str, str]]]] = None
        self._banks_lock = threading.Lock()

    # --- helping the user fill the form -----------------------------------------

    def banks(self) -> list[dict[str, str]]:
        """Flutterwave's Nigerian banks, kept for an hour."""
        with self._banks_lock:
            if self._banks is not None and time.monotonic() - self._banks[0] < 3600:
                return self._banks[1]
        try:
            banks = [{"name": bank["name"], "code": bank["code"]}
                     for bank in self._flutterwave().banks()]
        except FlutterwaveError as err:
            raise ApiError(502, "provider_failed", "Couldn't load the banks right now.") \
                from err
        banks.sort(key=lambda bank: bank["name"])
        with self._banks_lock:
            self._banks = (time.monotonic(), banks)
        return banks

    def resolve(self, bank_code: str, account_number: str) -> dict[str, Any]:
        _check_account_number(account_number)
        try:
            resolved = self._flutterwave().resolve_account(bank_code, account_number)
        except FlutterwaveError as err:
            if err.transient:
                raise ApiError(502, "provider_failed", "Couldn't check that account.") \
                    from err
            raise ApiError(400, "bad_account",
                           "That account number doesn't match the bank you picked.") from err
        return {"account_name": resolved["account_name"], "account_number": account_number,
                "bank_code": bank_code}

    # --- the withdrawal -----------------------------------------------------------

    def request(self, account_id: str, amount_ngn: int, bank_code: str,
                account_number: str) -> dict[str, Any]:
        self._flutterwave()
        if amount_ngn < MIN_WITHDRAWAL_NGN:
            raise ApiError(400, "bad_amount",
                           f"Withdraw at least ₦{MIN_WITHDRAWAL_NGN:,}.")
        account = self.resolve(bank_code, account_number)
        bank_name = next((bank["name"] for bank in self.banks() if bank["code"] == bank_code),
                         bank_code)

        withdrawal_id = f"wd_{uuid.uuid4().hex[:16]}"
        receipt_id = self.hold(
            account_id, withdrawal_id, amount_ngn, label=f"To {account['account_name']}",
            source=f"{bank_name} ····{account_number[-4:]}", vendor="flutterwave",
        )
        now = Clock.now_iso()
        self.db.query(
            "INSERT INTO withdrawals (id, user_id, method, amount_ngn, bank_code,"
            " account_number, account_name, bank_name, receipt_id, status, created_at,"
            " updated_at)"
            " VALUES ($1, $2, 'bank', $3, $4, $5, $6, $7, $8, 'sending', $9, $9)",
            [withdrawal_id, account_id, amount_ngn, bank_code, account_number,
             account["account_name"], bank_name, receipt_id, now],
        )
        self.vaults.debit(account_id, amount_ngn, withdrawal_id)
        self._send(self._row(withdrawal_id))
        return shape(self._row(withdrawal_id))

    def hold(self, account_id: str, withdrawal_id: str, amount_ngn: int, *, label: str,
             source: str, vendor: str) -> str:
        """Take the money out of the balance before it is sent anywhere.

        One statement debits the wallet and writes the activity entry, or refuses if
        the balance is short. Returns the entry's id. The caller then mirrors the
        debit into the vault with the withdrawal id as the reference.
        """
        try:
            receipt, _ = self.receipts.record_debit(account_id, {
                "id": f"rcpt_{uuid.uuid4().hex[:6]}",
                "request_id": withdrawal_id,
                "bill_id": "wallet",
                "bill_label": label,
                "meter": None,
                "amount_ngn": amount_ngn,
                "units": None,
                "token": None,
                "tx_hash": None,
                "status": "processing",
                "entry_type": "withdrawal",
                "source": source,
                "vendor": vendor,
                "vendor_code": None,
                "vendor_message": None,
                "created_at": Clock.now_iso(),
            }, amount_ngn)
        except ValueError:
            raise ApiError(409, "insufficient_balance",
                           "There isn't that much in your wallet.") from None
        return receipt["id"]

    def recent(self, account_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return [shape(row) for row in self.db.query(
            "SELECT * FROM withdrawals WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
            [account_id, limit],
        )]

    # --- moving it along ------------------------------------------------------------

    def advance(self) -> None:
        """The money loop's pass: send what has not gone out yet, and re-read what has."""
        for row in self.db.query(
            "SELECT * FROM withdrawals WHERE method = 'bank'"
            " AND status IN ('sending', 'processing') ORDER BY created_at LIMIT 50"
        ):
            if row["status"] == "sending":
                self._send(row)
            else:
                self._reread(row)

    def _send(self, row: dict[str, Any]) -> None:
        assert self.flutterwave is not None
        try:
            transfer = self.flutterwave.find_transfer(row["id"]) \
                or self.flutterwave.create_transfer(
                    bank_code=row["bank_code"], account_number=row["account_number"],
                    amount_ngn=int(row["amount_ngn"]), reference=row["id"], narration="Stark",
                )
        except FlutterwaveError as err:
            if err.transient:
                return  # the next pass asks again
            try:
                transfer = self.flutterwave.find_transfer(row["id"])
            except FlutterwaveError:
                return  # returning money that may be on its way would pay it twice
            if transfer is None:
                self.give_back(row, err.message)
                return
        self._set(row["id"], "processing", str(transfer["id"]), None)

    def _reread(self, row: dict[str, Any]) -> None:
        assert self.flutterwave is not None
        try:
            transfer = self.flutterwave.get_transfer(row["payout_id"])
        except FlutterwaveError:
            return
        self.on_transfer(row["id"], transfer["status"], transfer.get("complete_message"))

    def on_transfer(self, reference: str, status: str, message: Optional[str]) -> bool:
        """A transfer's outcome, from the webhook or a re-read. False if it isn't ours."""
        row = self.db.one("SELECT * FROM withdrawals WHERE id = $1 AND method = 'bank'",
                          [reference])
        if row is None:
            return False
        if status == "SUCCESSFUL":
            if row["status"] == "returned":
                log.critical("withdrawal %s was paid after its money was returned", reference)
            elif row["status"] != "paid":
                self.mark_paid(row)
        elif status == "FAILED":
            self.give_back(row, message or "the bank transfer failed")
        return True

    def mark_paid(self, row: dict[str, Any]) -> None:
        self._set(row["id"], "paid", None, None)
        self.receipts.update(row["user_id"], row["receipt_id"], status="sent")

    def give_back(self, row: dict[str, Any], reason: str) -> None:
        """Return a withdrawal's money to the balance, once, and to the vault with it."""
        if row["status"] == "returned":
            return
        reference = f"{row['id']}-r"
        amount = int(row["amount_ngn"])
        try:
            self.receipts.record_deposit(row["user_id"], {
                "id": f"rcpt_{uuid.uuid4().hex[:6]}",
                "request_id": reference,
                "bill_id": "wallet",
                "bill_label": "Withdrawal returned",
                "meter": None,
                "amount_ngn": amount,
                "units": None,
                "token": None,
                "tx_hash": None,
                "status": "received",
                "entry_type": "deposit",
                "source": "Returned from bank" if row["method"] == "bank"
                else f"Returned, not sent as {row['asset_symbol']}",
                "vendor": "flutterwave" if row["method"] == "bank" else "near-intents",
                "vendor_code": None,
                "vendor_message": reason[:200],
                "created_at": Clock.now_iso(),
            }, amount)
        except neon.DatabaseError as err:
            if err.code != UNIQUE_VIOLATION:
                raise
        self.receipts.update(row["user_id"], row["receipt_id"], status="failed",
                             vendor_message=reason[:200])
        self.vaults.credit(row["user_id"], amount, reference)
        self._set(row["id"], "returned", None, reason)

    # --- plumbing -----------------------------------------------------------------------

    def _flutterwave(self) -> FlutterwaveClient:
        if self.flutterwave is None:
            raise ApiError(501, "not_available",
                           "Withdrawing to a bank isn't set up yet. Nothing was taken.")
        return self.flutterwave

    def _row(self, withdrawal_id: str) -> dict[str, Any]:
        return self.db.one("SELECT * FROM withdrawals WHERE id = $1",
                           [withdrawal_id])  # type: ignore[return-value]

    def _set(self, withdrawal_id: str, status: str, payout_id: Optional[str],
             note: Optional[str]) -> None:
        self.db.query(
            "UPDATE withdrawals SET status = $2, payout_id = COALESCE($3, payout_id),"
            " note = $4, updated_at = $5 WHERE id = $1",
            [withdrawal_id, status, payout_id, note, Clock.now_iso()],
        )


def _check_account_number(account_number: str) -> None:
    if not (account_number.isdigit() and len(account_number) == 10):
        raise ApiError(400, "bad_account", "A Nigerian account number has 10 digits.")


def shape(row: dict[str, Any]) -> dict[str, Any]:
    """The `Withdrawal` the API returns. `crypto` is set only for a crypto payout."""
    crypto = None
    if row["method"] == "crypto":
        crypto = {
            "asset": row["asset_symbol"],
            "chain": row["asset_chain"],
            "address": row["address"],
            "amount": row["amount_out_formatted"],
            "tx_hash": row["tx_hash"],
        }
    return {
        "id": row["id"],
        "method": row["method"],
        "amount_ngn": int(row["amount_ngn"]),
        "status": row["status"],
        "note": row.get("note"),
        "crypto": crypto,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
