"""Withdrawing as crypto: the treasury's USDC, swapped by 1Click into what the user wants.

    quote (USDC on NEAR → asset, to the user's address) → hold the naira
    → sign the treasury's transfer and store it → broadcast → `processing`
    → 1Click `SUCCESS` (`paid`) or `REFUNDED`/`FAILED` (the money comes back)

The naira is converted at Stark's selling rate (Paycrest's market rate plus the
spread, see `usdc_rate`), rounded down, so Stark never sends
more USDC than the naira covers. What arrives is `amountOutFormatted` of the asset,
after 1Click's swap; a refund returns the USDC to the treasury and the naira to the
user.

**Caps.** The treasury key can move real money, so every request is checked against
`STARK_CRYPTO_WITHDRAW_MAX_NGN` (one withdrawal), `STARK_CRYPTO_WITHDRAW_MAX_USDC`
(the same withdrawal in USDC, so a bad rate cannot multiply what leaves),
`STARK_CRYPTO_WITHDRAW_USER_DAILY_NGN` (one account, so one user cannot use up the
day for everyone) and `STARK_CRYPTO_WITHDRAW_DAILY_NGN` (all users), each daily one
counting what was not returned in the last 24 hours, before anything is quoted or
held. The daily checks and the hold run under one lock, so two requests cannot both
squeeze under a limit; the lock is per process, so several replicas would each
allow the full amount. The shared ledger (`WithdrawalService.hold`) also refuses
while the account is paused and keeps card money on hold out.

**Never twice.** The signed transfer is written to the row before it is broadcast.
A timeout or crash is retried with the same bytes, and a failed broadcast is checked
against the chain before anything is re-signed: a new signature only happens when
the old transaction provably cannot land (expired, or its nonce was spent elsewhere).
"""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.database import neon
from app.modules.chain import near_tx
from app.modules.chain.treasury_chain import SignedTransfer, TreasuryChain
from app.modules.intents import one_click
from app.modules.intents.one_click import OneClickClient, OneClickError
from app.modules.liquidity.usdc_rate import RateUnavailable, UsdcRate
from app.modules.vault.vault_service import VaultService
from app.modules.wallet.deposit_service import DepositService
from app.modules.wallet.withdrawal_service import WithdrawalService, shape

MIN_CRYPTO_WITHDRAWAL_NGN = 1_000
QUOTE_MINUTES = 60
# A rejected broadcast whose transaction can never land, so a fresh signature is safe.
NEVER_LANDS = ("Expired", "InvalidNonce")


@dataclass(frozen=True)
class CryptoPayoutSettings:
    usdc_rate: UsdcRate
    max_ngn: int
    max_usdc: Decimal
    daily_ngn: int
    user_daily_ngn: int


class CryptoWithdrawalService:
    def __init__(self, db: neon.Database, ledger: WithdrawalService, vaults: VaultService,
                 deposits: DepositService, one_click_client: OneClickClient,
                 treasury: Optional[TreasuryChain], settings: CryptoPayoutSettings,
                 *, sandbox_naira: bool = False) -> None:
        self.db = db
        self.ledger = ledger
        self.vaults = vaults
        self.deposits = deposits
        self.one_click = one_click_client
        self.treasury = treasury
        self.settings = settings
        # The naira balance can hold money nobody paid (a Flutterwave test key's
        # checkouts), so it must never become mainnet USDC.
        self.sandbox_naira = sandbox_naira
        self._lock = threading.Lock()

    def available(self) -> bool:
        return self.treasury is not None and not self.sandbox_naira

    # --- the withdrawal -----------------------------------------------------------

    def request(self, account_id: str, amount_ngn: int, asset_id: str,
                address: str) -> dict[str, Any]:
        if not self.available():
            raise ApiError(501, "not_available",
                           "Withdrawing as crypto isn't set up yet. Nothing was taken.")
        assert self.treasury is not None
        if amount_ngn < MIN_CRYPTO_WITHDRAWAL_NGN:
            raise ApiError(400, "bad_amount",
                           f"Withdraw at least ₦{MIN_CRYPTO_WITHDRAWAL_NGN:,} as crypto.")
        if amount_ngn > self.settings.max_ngn:
            raise ApiError(400, "over_limit",
                           f"Send at most ₦{self.settings.max_ngn:,} as crypto at a time.")
        token = self.deposits.crypto_token(asset_id)
        if token is None:
            raise ApiError(400, "bad_asset", "Stark can't send that.")
        address = address.strip()
        if not address or len(address) > 128 or any(c.isspace() for c in address):
            raise ApiError(400, "bad_address",
                           f"That doesn't look like a {token['symbol']} address.")

        try:
            rate = self.settings.usdc_rate.selling()
        except RateUnavailable as err:
            raise ApiError(502, "provider_failed",
                           "Couldn't get a price for that right now. Nothing was taken.") \
                from err
        usdc_in = math.floor(Decimal(amount_ngn) / rate * 10 ** one_click.USDC_DECIMALS)
        if usdc_in > self.settings.max_usdc * 10 ** one_click.USDC_DECIMALS:
            raise ApiError(400, "over_limit",
                           "That's more than Stark sends as crypto at once right now. "
                           "Try a smaller amount. Nothing was taken.")
        withdrawal_id = f"wd_{uuid.uuid4().hex[:16]}"
        with self._lock:
            everyone, yours = self._sent_today(account_id)
            if yours + amount_ngn > self.settings.user_daily_ngn:
                raise ApiError(409, "daily_limit",
                               f"You can send at most ₦{self.settings.user_daily_ngn:,} as "
                               "crypto in a day. Try a smaller amount, or try again "
                               "tomorrow. Nothing was taken.")
            if everyone + amount_ngn > self.settings.daily_ngn:
                raise ApiError(409, "daily_limit",
                               "Crypto withdrawals are full for today. Try a bank "
                               "withdrawal, or try again tomorrow. Nothing was taken.")
            quote = self._quote(token, usdc_in, address)
            now = Clock.now_iso()
            self.ledger.hold(account_id, {
                "id": withdrawal_id, "user_id": account_id, "method": "crypto",
                "amount_ngn": amount_ngn, "status": "sending", "asset_id": asset_id,
                "asset_symbol": token["symbol"], "asset_chain": token["blockchain"],
                "address": address, "deposit_address": quote["depositAddress"],
                "usdc_in": str(usdc_in), "amount_out_formatted": quote["amountOutFormatted"],
                "created_at": now, "updated_at": now,
            }, label=f"As {token['symbol']}",
                source=f"{token['symbol']} on {token['blockchain']} ····{address[-4:]}",
                vendor="near-intents")
        self._send(self._row(withdrawal_id))
        return shape(self._row(withdrawal_id))

    def _quote(self, token: dict[str, Any], usdc_in: int, address: str) -> dict[str, Any]:
        assert self.treasury is not None
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=QUOTE_MINUTES)) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            return self.one_click.quote_withdrawal(
                destination_asset=token["assetId"], usdc_in=usdc_in, recipient=address,
                treasury=self.treasury.account_id, deadline=deadline,
            )["quote"]
        except OneClickError as err:
            if err.status != 400:
                raise ApiError(502, "provider_failed",
                               "Couldn't get a price for that right now. Nothing was taken.") \
                    from err
            if "amount" in err.message.lower():
                raise ApiError(400, "bad_amount",
                               f"That's too little to send as {token['symbol']}.") from err
            raise ApiError(400, "bad_address",
                           f"That isn't a {token['symbol']} address on "
                           f"{token['blockchain']}.") from err

    def _sent_today(self, account_id: str) -> tuple[int, int]:
        """Crypto not returned in the last 24 hours: across everyone, and this account's."""
        row = self.db.one(
            "SELECT COALESCE(SUM(amount_ngn), 0) AS everyone,"
            " COALESCE(SUM(amount_ngn) FILTER (WHERE user_id = $2), 0) AS yours"
            " FROM withdrawals"
            " WHERE method = 'crypto' AND status <> 'returned' AND created_at > $1",
            [Clock.ago(days=1), account_id],
        )
        assert row is not None
        return int(row["everyone"]), int(row["yours"])

    # --- moving it along ------------------------------------------------------------

    def advance(self) -> None:
        """The money loop's pass: send what is held, then follow each swap to the end."""
        if self.treasury is None:
            return
        for row in self.db.query(
            "SELECT * FROM withdrawals WHERE method = 'crypto'"
            " AND status IN ('sending', 'processing') ORDER BY created_at LIMIT 50"
        ):
            if row["status"] == "sending":
                self._send(row)
            else:
                self._follow(row)

    def _send(self, row: dict[str, Any]) -> None:
        assert self.treasury is not None
        # Idempotent on the reference: catches up a crash between the hold and here.
        self.vaults.debit(row["user_id"], int(row["amount_ngn"]), row["id"])
        if row["signed_tx"] is None:
            try:
                transfer = self.treasury.sign_usdc_transfer(row["deposit_address"],
                                                            int(row["usdc_in"]))
            except near_tx.NearRpcError:
                return  # the next pass signs it
            self.db.query(
                "UPDATE withdrawals SET signed_tx = $2, tx_hash = $3, updated_at = $4"
                " WHERE id = $1",
                [row["id"], transfer.encoded, transfer.tx_hash, Clock.now_iso()],
            )
        else:
            transfer = SignedTransfer(row["signed_tx"], row["tx_hash"])

        try:
            self.treasury.send(transfer)
        except near_tx.ContractRefused as err:
            self.ledger.give_back(row, f"the transfer was refused: {err.message}")
            return
        except near_tx.NearRpcError as err:
            self._after_failed_broadcast(row, transfer, err)
            return
        self._sent(row, transfer)

    def _after_failed_broadcast(self, row: dict[str, Any], transfer: SignedTransfer,
                                err: near_tx.NearRpcError) -> None:
        """A broadcast that errored may still have landed: ask the chain before acting."""
        assert self.treasury is not None
        try:
            outcome = self.treasury.outcome(transfer)
        except near_tx.NearRpcError:
            return
        if outcome is None:
            if any(reason in f"{err} {err.detail}" for reason in NEVER_LANDS):
                self.db.query(
                    "UPDATE withdrawals SET signed_tx = NULL, tx_hash = NULL,"
                    " updated_at = $2 WHERE id = $1", [row["id"], Clock.now_iso()],
                )
            return
        try:
            near_tx.success_value(outcome)
        except near_tx.ContractRefused as refused:
            self.ledger.give_back(row, f"the transfer was refused: {refused.message}")
            return
        self._sent(row, transfer)

    def _sent(self, row: dict[str, Any], transfer: SignedTransfer) -> None:
        self.db.query(
            "UPDATE withdrawals SET status = 'processing', updated_at = $2"
            " WHERE id = $1 AND status = 'sending'", [row["id"], Clock.now_iso()],
        )
        try:
            self.one_click.submit_deposit(row["deposit_address"], transfer.tx_hash, None)
        except OneClickError:
            pass  # optional: it only gets the swap noticed sooner

    def _follow(self, row: dict[str, Any]) -> None:
        try:
            report = self.one_click.status(row["deposit_address"], None)
        except OneClickError:
            return
        details = report.get("swapDetails") or {}
        if report["status"] == "SUCCESS":
            if details.get("amountOutFormatted"):
                self.db.query(
                    "UPDATE withdrawals SET amount_out_formatted = $2 WHERE id = $1",
                    [row["id"], details["amountOutFormatted"]],
                )
            self.ledger.mark_paid(row)
        elif report["status"] in ("REFUNDED", "FAILED"):
            self.ledger.give_back(row, details.get("refundReason")
                                  or f"the swap {report['status'].lower()}")

    def _row(self, withdrawal_id: str) -> dict[str, Any]:
        return self.db.one("SELECT * FROM withdrawals WHERE id = $1",
                           [withdrawal_id])  # type: ignore[return-value]
