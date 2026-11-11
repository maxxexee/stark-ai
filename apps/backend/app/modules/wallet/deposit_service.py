"""Adding money: one deposit, two rails, one way to credit it.

| `method` | Rail | The user | Confirmed by |
|---|---|---|---|
| `bank` | Flutterwave checkout | opens a hosted page: bank transfer, card or USSD | `charge.completed` webhook, the redirect back, or a due check verifying the `tx_ref` |
| `crypto` | NEAR Intents (1Click) | sends the quoted amount of what they hold to a one-off address | a due check reading `/v0/status`, or the user reopening the deposit |

Either way the credit is the same three writes, and each is safe to repeat:

1. the wallet and an activity entry, in one statement keyed on the deposit id
   (`UNIQUE (user_id, request_id)` — a second webhook cannot credit twice);
2. the vault's `fund(amount, deposit id)` through the outbox;
3. the deposit row marked `credited`.

The money is spendable the moment step 1 lands: Stark fronts the naira from its
Flutterwave balance until Flutterwave settles the charge into it.

A bank deposit is only ever credited from Flutterwave's own verify call, never from
a webhook body or the redirect's query string: the charge must be `successful`, in
NGN, for at least the amount asked.

**Due checks, not a scan.** 1Click has no webhook and a Flutterwave webhook can be
missed, so each deposit in flight carries its own `next_check_at`, half its age from
now (one minute at least, fifteen at most). One thread sleeps until the earliest of
those, so with nothing in flight it makes no calls at all. `/tx` pulls the check in.

A crypto deposit is credited at the rate locked when it was quoted
(`STARK_USDC_NGN_RATE`, naira per USDC — Stark's buying rate), and never for more
than the naira the user asked for.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any, Optional

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.database import neon
from app.modules.flutterwave.flutterwave import FlutterwaveClient, FlutterwaveError, whole_naira
from app.modules.intents import one_click
from app.modules.intents.one_click import OneClickClient, OneClickError
from app.modules.receipt.receipt_repository import ReceiptRepository
from app.modules.vault.vault_service import VaultService

log = logging.getLogger("stark.deposits")

MIN_DEPOSIT_NGN = 100
MAX_DEPOSIT_NGN = 5_000_000
WINDOW_MINUTES = 60
MIN_CHECK_SECONDS = 60
MAX_CHECK_SECONDS = 15 * 60
SOON_SECONDS = 30
UNIQUE_VIOLATION = "23505"


@dataclass(frozen=True)
class FundingSettings:
    app_url: Optional[str]
    treasury_account: Optional[str]
    usdc_ngn_rate: Optional[Decimal]


class DepositService:
    def __init__(self, db: neon.Database, receipts: ReceiptRepository, vaults: VaultService,
                 flutterwave: Optional[FlutterwaveClient], one_click_client: OneClickClient,
                 settings: FundingSettings) -> None:
        self.db = db
        self.receipts = receipts
        self.vaults = vaults
        self.flutterwave = flutterwave
        self.one_click = one_click_client
        self.settings = settings
        self._tokens: Optional[tuple[float, list[dict[str, Any]]]] = None
        self._tokens_lock = threading.Lock()
        self._wake = threading.Event()
        self._watching = False

    # --- what can be used -----------------------------------------------------

    def methods(self) -> dict[str, bool]:
        return {"bank": self.flutterwave is not None and self.settings.app_url is not None,
                "crypto": self._crypto_ready()}

    def crypto_assets(self) -> list[dict[str, Any]]:
        if not self._crypto_ready():
            return []
        return [
            {"asset_id": t["assetId"], "symbol": t["symbol"], "chain": t["blockchain"]}
            for t in self._token_list()
        ]

    def crypto_token(self, asset_id: str) -> Optional[dict[str, Any]]:
        """One listed 1Click token, or None. Withdrawals pay out to the same list."""
        return next((t for t in self._token_list() if t["assetId"] == asset_id), None)

    # --- starting a deposit -----------------------------------------------------

    def start(self, account_id: str, amount_ngn: int, method: str,
              asset_id: Optional[str]) -> dict[str, Any]:
        if not MIN_DEPOSIT_NGN <= amount_ngn <= MAX_DEPOSIT_NGN:
            raise ApiError(400, "bad_amount",
                           f"Add between ₦{MIN_DEPOSIT_NGN:,} and ₦{MAX_DEPOSIT_NGN:,}.")
        if method == "bank":
            return self._start_bank(account_id, amount_ngn)
        if method == "crypto":
            if not asset_id:
                raise ApiError(400, "bad_asset", "Pick what you're paying with.")
            return self._start_crypto(account_id, amount_ngn, asset_id)
        raise ApiError(400, "bad_method", "method must be bank or crypto")

    def _start_bank(self, account_id: str, amount_ngn: int) -> dict[str, Any]:
        if self.flutterwave is None or self.settings.app_url is None:
            raise ApiError(501, "not_available",
                           "Adding money by bank or card isn't set up yet. Nothing was taken.")
        account = self.db.one("SELECT email, name FROM accounts WHERE id = $1", [account_id])
        assert account is not None
        deposit_id = f"dep_{uuid.uuid4().hex[:16]}"
        try:
            link = self.flutterwave.create_checkout(
                tx_ref=deposit_id, amount_ngn=amount_ngn, email=account["email"],
                name=account["name"] or account["email"],
                redirect_url=f"{self.settings.app_url.rstrip('/')}/wallet/add?deposit={deposit_id}",
                meta={"account_id": account_id, "deposit_id": deposit_id},
            )
        except FlutterwaveError as err:
            raise ApiError(502, "provider_failed",
                           "Couldn't start that payment. Nothing was taken.") from err
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=WINDOW_MINUTES)) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        row = self.db.one(
            "INSERT INTO deposits (id, user_id, method, amount_ngn, status, provider_ref,"
            " checkout_url, expires_at, next_check_at, created_at, updated_at)"
            " VALUES ($1, $2, 'bank', $3, 'open', $1, $4, $5, $6, $7, $7) RETURNING *",
            [deposit_id, account_id, amount_ngn, link, expires_at,
             _in_seconds(MIN_CHECK_SECONDS), Clock.now_iso()],
        )
        self._wake.set()
        return shape(row)

    def _start_crypto(self, account_id: str, amount_ngn: int, asset_id: str) -> dict[str, Any]:
        if not self._crypto_ready():
            raise ApiError(501, "not_available",
                           "Adding money with crypto isn't set up yet. Nothing was taken.")
        token = self.crypto_token(asset_id)
        if token is None:
            raise ApiError(400, "bad_asset", "That isn't something Stark accepts.")
        rate = self.settings.usdc_ngn_rate
        assert rate is not None and self.settings.treasury_account
        # Round the USDC up, so the credit at the locked rate covers the naira asked.
        usdc_out = math.ceil(Decimal(amount_ngn) / rate * 10 ** one_click.USDC_DECIMALS)
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=WINDOW_MINUTES)) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            quoted = self.one_click.quote(
                origin_asset=asset_id, usdc_out=usdc_out,
                recipient=self.settings.treasury_account, deadline=deadline,
            )
        except OneClickError as err:
            raise ApiError(502, "provider_failed",
                           "Couldn't get a price for that right now. Nothing was taken.") \
                from err
        quote = quoted["quote"]
        deposit_id = f"dep_{uuid.uuid4().hex[:16]}"
        row = self.db.one(
            "INSERT INTO deposits (id, user_id, method, amount_ngn, status, provider_ref,"
            " deposit_address, deposit_memo, asset_id, asset_symbol, asset_chain,"
            " amount_in, amount_in_formatted, usdc_out, rate_ngn_per_usdc, expires_at,"
            " next_check_at, created_at, updated_at)"
            " VALUES ($1, $2, 'crypto', $3, 'open', $4, $4, $5, $6, $7, $8, $9, $10, $11,"
            " $12, $13, $14, $15, $15) RETURNING *",
            [deposit_id, account_id, amount_ngn, quote["depositAddress"],
             quote.get("depositMemo"), asset_id, token["symbol"], token["blockchain"],
             quote["amountIn"], quote["amountInFormatted"], str(usdc_out), str(rate),
             quote.get("deadline") or deadline, _in_seconds(MIN_CHECK_SECONDS),
             Clock.now_iso()],
        )
        self._wake.set()
        return shape(row)

    # --- reading ----------------------------------------------------------------

    def recent(self, account_id: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM deposits WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
            [account_id, limit],
        )
        return [shape(row) for row in rows]

    def get(self, account_id: str, deposit_id: str) -> dict[str, Any]:
        """One deposit, checked with its rail first if it is still open."""
        row = self._row(account_id, deposit_id)
        if row["status"] in ("open", "confirming"):
            self._check(row)
            row = self._row(account_id, deposit_id)
        return shape(row)

    def submit_tx(self, account_id: str, deposit_id: str, tx_hash: str) -> dict[str, Any]:
        row = self._row(account_id, deposit_id)
        if row["method"] != "crypto":
            raise ApiError(400, "bad_method", "Only a crypto deposit takes a transaction.")
        try:
            self.one_click.submit_deposit(row["deposit_address"], tx_hash, row["deposit_memo"])
        except OneClickError as err:
            raise ApiError(400, "bad_tx", "That transaction wasn't recognised.") from err
        self.db.query("UPDATE deposits SET next_check_at = $2 WHERE id = $1",
                      [deposit_id, _in_seconds(SOON_SECONDS)])
        self._wake.set()
        return self.get(account_id, deposit_id)

    def _row(self, account_id: str, deposit_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM deposits WHERE id = $1 AND user_id = $2",
                          [deposit_id, account_id])
        if row is None:
            raise ApiError(404, "unknown_deposit", "No deposit with that id.")
        return row

    # --- confirming -------------------------------------------------------------

    def on_charge(self, tx_ref: str) -> None:
        """A `charge.completed` webhook names a deposit; Flutterwave is asked about it.

        The webhook body is not trusted for the amount or the outcome: the verify
        call is the only thing that credits.
        """
        row = self.db.one("SELECT * FROM deposits WHERE id = $1", [tx_ref])
        if row is None or row["status"] == "credited" or row["method"] != "bank":
            return
        self._check(row)

    def check_due(self) -> Optional[float]:
        """Check what has come due. Returns seconds to the next one, None if none is set."""
        for row in self.db.query(
            "SELECT * FROM deposits WHERE status IN ('open', 'confirming')"
            " AND next_check_at <= $1 ORDER BY next_check_at LIMIT 100",
            [Clock.now_iso()],
        ):
            # Moved on before checking, so a deposit that crashes its check can't spin.
            self.db.query("UPDATE deposits SET next_check_at = $2 WHERE id = $1",
                          [row["id"], _in_seconds(_check_delay(row["created_at"]))])
            self._check(row)
        earliest = self.db.value(
            "SELECT MIN(next_check_at) FROM deposits WHERE status IN ('open', 'confirming')"
        )
        if earliest is None:
            return None
        return max((_when(earliest) - datetime.now(timezone.utc)).total_seconds(), 0)

    def start_watching(self) -> None:
        def run() -> None:
            while self._watching:
                self._wake.clear()
                try:
                    wait = self.check_due()
                except Exception:  # the database being down must not end the watch
                    log.exception("deposit checks failed")
                    wait = MIN_CHECK_SECONDS
                self._wake.wait(wait)

        self._watching = True
        threading.Thread(target=run, daemon=True, name="deposits").start()

    def stop_watching(self) -> None:
        self._watching = False
        self._wake.set()

    def _check(self, row: dict[str, Any]) -> None:
        try:
            if row["method"] == "bank":
                self._check_bank(row)
            else:
                self._check_crypto(row)
        except (FlutterwaveError, OneClickError):
            return  # the next pass tries again

    def _check_bank(self, row: dict[str, Any]) -> None:
        if self.flutterwave is None:
            return
        try:
            charge = self.flutterwave.verify_by_reference(row["id"])
        except FlutterwaveError as err:
            # 400 "No transaction was found" is an unpaid checkout, not a failure.
            if err.transient:
                raise
            if row["status"] == "open" and _past(row["expires_at"]):
                self._set_status(row["id"], "expired", None)
            return
        if charge["currency"] != "NGN" or charge["tx_ref"] != row["id"]:
            return
        paid_in_full = whole_naira(charge["amount"]) >= int(row["amount_ngn"])
        if charge["status"] == "successful" and paid_in_full:
            self._credit(row, int(row["amount_ngn"]))
        elif charge["status"] == "failed":
            self._set_status(row["id"], "failed", charge.get("processor_response"))
        elif row["status"] == "open":
            self._set_status(row["id"], "confirming", None)

    def _check_crypto(self, row: dict[str, Any]) -> None:
        report = self.one_click.status(row["deposit_address"], row["deposit_memo"])
        status = report["status"]
        if status == "SUCCESS":
            out = int(report["swapDetails"].get("amountOut") or row["usdc_out"])
            credited = Decimal(out) * Decimal(row["rate_ngn_per_usdc"]) \
                / 10 ** one_click.USDC_DECIMALS
            amount = min(int(credited.to_integral_value(rounding=ROUND_DOWN)),
                         int(row["amount_ngn"]))
            self._credit(row, amount)
        elif status in ("REFUNDED", "FAILED"):
            reason = report["swapDetails"].get("refundReason") or status.lower()
            self._set_status(row["id"], "refunded" if status == "REFUNDED" else "failed",
                             reason)
        elif status == "PENDING_DEPOSIT" and _past(row["expires_at"]):
            self._set_status(row["id"], "expired", None)

    def _credit(self, row: dict[str, Any], amount_ngn: int) -> None:
        crypto = row["method"] == "crypto"
        try:
            self.receipts.record_deposit(row["user_id"], {
                "id": f"rcpt_{uuid.uuid4().hex[:6]}",
                "request_id": row["id"],
                "bill_id": "wallet",
                "bill_label": "Added money",
                "meter": None,
                "amount_ngn": amount_ngn,
                "units": None,
                "token": None,
                "tx_hash": None,
                "status": "received",
                "entry_type": "deposit",
                "source": f"{row['asset_symbol']} on {row['asset_chain']}" if crypto
                else "Bank, card or USSD",
                "vendor": "near-intents" if crypto else "flutterwave",
                "vendor_code": None,
                "vendor_message": None,
                "created_at": Clock.now_iso(),
            }, amount_ngn)
        except neon.DatabaseError as err:
            if err.code != UNIQUE_VIOLATION:
                raise
            # Already credited by the webhook or an earlier pass: fall through so
            # the vault and the row still catch up.
        self.vaults.credit(row["user_id"], amount_ngn, row["id"])
        self.db.query(
            "UPDATE deposits SET status = 'credited', credited_ngn = $2, credited_at = $3,"
            " updated_at = $3 WHERE id = $1 AND status <> 'credited'",
            [row["id"], amount_ngn, Clock.now_iso()],
        )

    def _set_status(self, deposit_id: str, status: str, note: Optional[str]) -> None:
        self.db.query(
            "UPDATE deposits SET status = $2, note = $3, updated_at = $4"
            " WHERE id = $1 AND status <> 'credited'",
            [deposit_id, status, note, Clock.now_iso()],
        )

    # --- plumbing -----------------------------------------------------------------

    def _crypto_ready(self) -> bool:
        return bool(self.settings.treasury_account and self.settings.usdc_ngn_rate)

    def _token_list(self) -> list[dict[str, Any]]:
        """1Click's token list, kept for ten minutes."""
        with self._tokens_lock:
            if self._tokens is not None and time.monotonic() - self._tokens[0] < 600:
                return self._tokens[1]
        try:
            tokens = self.one_click.tokens()
        except OneClickError as err:
            raise ApiError(502, "provider_failed",
                           "Couldn't load what you can pay with right now.") from err
        with self._tokens_lock:
            self._tokens = (time.monotonic(), tokens)
        return tokens


def shape(row: dict[str, Any]) -> dict[str, Any]:
    """The `Deposit` the API returns. `pay` is what the user does next."""
    pay: dict[str, Any]
    if row["method"] == "bank":
        pay = {"checkout_url": row["checkout_url"]}
    else:
        pay = {
            "asset": row["asset_symbol"],
            "chain": row["asset_chain"],
            "amount": row["amount_in_formatted"],
            "address": row["deposit_address"],
            "memo": row["deposit_memo"],
        }
    return {
        "id": row["id"],
        "method": row["method"],
        "amount_ngn": int(row["amount_ngn"]),
        "credited_ngn": int(row["credited_ngn"]) if row.get("credited_ngn") is not None
        else None,
        "status": row["status"],
        "note": row.get("note"),
        "pay": pay,
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "credited_at": row.get("credited_at"),
    }


def _past(iso: Optional[str]) -> bool:
    if not iso:
        return False
    return _when(iso) < datetime.now(timezone.utc)


def _when(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _in_seconds(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_delay(created_at: str) -> float:
    age = (datetime.now(timezone.utc) - _when(created_at)).total_seconds()
    return min(max(age / 2, MIN_CHECK_SECONDS), MAX_CHECK_SECONDS)
