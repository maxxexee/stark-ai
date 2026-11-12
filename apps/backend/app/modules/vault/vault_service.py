"""Keeps each user's onchain vault in step with their wallet in Postgres.

Postgres is what the app reads; the vault is what the agent's key is bound by.
They agree because every money movement in Postgres has a vault counterpart, and
that counterpart is written to an outbox (`chain_ops`) **before** it is sent:

| Postgres | Vault | When |
|---|---|---|
| deposit credited | `fund(amount, reference)` | Flutterwave charge, Intents deposit |
| withdrawal debited | `debit(amount, reference)` | bank withdrawal |
| withdrawal reversed | `fund(amount, reference)` | Flutterwave transfer failed |
| payment not delivered | `refund(payment_id)` | Flutterwave bill failed after `pay` |

Policy (caps and the meter allowlist) is synced **at payment time**: before `pay`,
the vault's `get_policy` is compared with the account's current limits and
`set_policy` is sent if they differ. Caps only bind at the moment of paying, so
this is exact where it matters, and settings screens need no chain calls.

Op ids (`chain_ops.id`, one table for every user) are scoped by user:
`fund:<user>:<reference>`, `debit:<user>:<reference>`, `refund:<user>:<payment_id>`.
Payment ids restart at 1 in every vault and some references are client-chosen, so an
unscoped `refund:1` from one user would turn every other user's `refund:1` into a
silent no-op. Rows written before this (`fund:<reference>`, …) are still sent: an id
is only a key. On chain a reference is already per vault, so it is left as it was.

A broadcast that fails for a network reason stays `pending` and is retried by the
money loop. Every op is safe to resend: `fund`/`debit` carry a reference the
contract applies once, and `refund` applies once per payment. A refusal from the
contract itself (say, a debit over the vault balance) is `failed` and is not
retried; it means the two ledgers disagree, which `drift()` reports.

`pay` is the exception: it is synchronous, because it is the authorisation. A
user's pending ops are flushed first — a deposit must land before it can be
spent — and if any are still stuck, the payment is refused rather than signed
against a vault that is behind.

With no chain configured (`VaultChain` is None) every method is a no-op and
payments book off-chain, as they always have offline.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Optional

from app.common.clock import Clock
from app.database import neon
from app.modules.account.account_service import AccountService
from app.modules.agent import agent as agent_layer
from app.modules.chain import near_tx
from app.modules.chain.vault_chain import ChainResult, VaultChain

log = logging.getLogger("stark.vault")


class AuthorisationFailed(Exception):
    """The vault did not authorise the payment. `message` is safe to say aloud."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class PaymentAuthorisation:
    # None when the chain is not broadcasting: a dry signature names no transaction,
    # so a receipt must not link one.
    tx_hash: Optional[str]
    # None when the transaction was signed dry and never sent.
    payment_id: Optional[int]


_COULD_NOT_AUTHORISE = "I couldn't authorise that payment just now. Nothing was charged."
_NOT_SETTLED = "I couldn't move the money for that just now. Nothing was charged."


class VaultService:
    def __init__(self, db: neon.Database, chain: Optional[VaultChain],
                 accounts: AccountService, ngn_per_usdc: Callable[[], Decimal]) -> None:
        self.db = db
        self.chain = chain
        self.accounts = accounts
        self.ngn_per_usdc = ngn_per_usdc
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.chain is not None

    # --- the vault itself -----------------------------------------------------

    def vault_account(self, user_id: str) -> Optional[str]:
        """The user's vault under the current funder. A vault made under another funder
        (another network, or code before USDC) is not reused: a new one is created."""
        if self.chain is None:
            return None
        row = self.db.one(
            "SELECT account_id FROM vaults WHERE user_id = $1 AND status = 'ready'"
            " AND account_id LIKE $2",
            [user_id, f"%.{self.chain.funder_id}"],
        )
        return row["account_id"] if row else None

    def ensure(self, user_id: str) -> Optional[str]:
        """This user's vault, created on first need with their current policy."""
        if self.chain is None:
            return None
        existing = self.vault_account(user_id)
        if existing is not None:
            return existing
        with self._lock_for(user_id):
            existing = self.vault_account(user_id)
            if existing is not None:
                return existing
            vault_id = self.chain.vault_id(user_id)
            limits = self.accounts.state(user_id).limits
            try:
                result = self.chain.create(
                    vault_id,
                    usdc_per_kngn=self.usdc_per_kngn(),
                    monthly_cap_ngn=limits.monthly_cap_ngn,
                    per_payment_cap_ngn=limits.per_payment_cap_ngn,
                    meters=sorted(limits.allowed_meters),
                )
            except (near_tx.NearRpcError, near_tx.ContractRefused) as err:
                log.error("vault creation failed user=%s vault=%s: %s", user_id, vault_id, err)
                self._record_vault(user_id, vault_id, "failed", None, str(err))
                raise AuthorisationFailed(_COULD_NOT_AUTHORISE) from err
            self._record_vault(user_id, vault_id, "ready", result.sent_tx_hash, None)
            self._queue_opening_deposit(user_id, vault_id)
            return vault_id

    def _queue_opening_deposit(self, user_id: str, vault_id: str) -> None:
        """Back a new vault with the balance the wallet already holds, so an existing
        account can spend from day one. Queued deposits and withdrawals are left out:
        they reach the vault on their own."""
        wallet = self.db.one("SELECT balance_ngn FROM wallets WHERE user_id = $1", [user_id])
        opening = int(wallet["balance_ngn"]) if wallet else 0
        for op in self.db.query(
            "SELECT method, args FROM chain_ops WHERE user_id = $1 AND status = 'pending'"
            " AND method IN ('fund', 'debit')",
            [user_id],
        ):
            amount = int(json.loads(op["args"])["amount_ngn"])
            opening += -amount if op["method"] == "fund" else amount
        if opening <= 0:
            return
        reference = f"opening:{vault_id}"
        self.db.query(
            "INSERT INTO chain_ops (id, user_id, method, args, status, attempts, created_at)"
            " VALUES ($1, $2, 'fund', $3, 'pending', 0, $4) ON CONFLICT (id) DO NOTHING",
            [f"fund:{user_id}:{reference}", user_id,
             json.dumps({"amount_ngn": str(opening), "reference": reference,
                         "amount_usdc": str(self.usdc_for(opening))}),
             Clock.now_iso()],
        )

    # --- outbox ---------------------------------------------------------------

    def credit(self, user_id: str, amount_ngn: int, reference: str) -> None:
        """Send the deposit's worth of USDC into the vault, priced now so a retry
        sends the same amount.

        `reference` becomes the deposit's on-chain `msg`, so a caller passing an id
        the client chose must prefix it (test top-ups use `topup:`): a bare
        `refund:1` or `opening:<vault>` would be read as something else."""
        if self.chain is None:
            return
        self._enqueue(user_id, f"fund:{user_id}:{reference}", "fund",
                      {"amount_ngn": str(amount_ngn), "reference": reference,
                       "amount_usdc": str(self.usdc_for(amount_ngn))})

    def debit(self, user_id: str, amount_ngn: int, reference: str) -> None:
        if self.chain is None:
            return
        self._enqueue(user_id, f"debit:{user_id}:{reference}", "debit",
                      {"amount_ngn": str(amount_ngn), "reference": reference,
                       "amount_usdc": str(self.usdc_for(amount_ngn))})

    def usdc_per_kngn(self) -> int:
        """USDC base units per ₦1,000 at the market rate: what the vault converts at."""
        units = Decimal(1000 * 10 ** 6) / self.ngn_per_usdc()
        return int(units.to_integral_value(rounding=ROUND_HALF_UP))

    def usdc_for(self, amount_ngn: int) -> int:
        return -(-amount_ngn * self.usdc_per_kngn() // 1000)

    def refund(self, user_id: str, payment_id: int) -> None:
        self._enqueue(user_id, f"refund:{user_id}:{payment_id}", "refund",
                      {"payment_id": payment_id})

    def set_paused(self, user_id: str, paused: bool) -> None:
        """Mirror the owner's off switch onchain, so even the agent key stops."""
        if self.vault_account(user_id) is None:
            return  # a vault created later starts from the current state anyway
        self._enqueue(user_id, f"pause:{uuid.uuid4().hex[:12]}",
                      "pause" if paused else "unpause", {})

    def record_payment(self, user_id: str, receipt_id: str, payment_id: int) -> None:
        """Which vault payment a receipt spent, so a vendor failure can refund it."""
        self.db.query(
            "INSERT INTO vault_payments (user_id, receipt_id, payment_id, created_at)"
            " VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            [user_id, receipt_id, payment_id, Clock.now_iso()],
        )

    def refund_receipt(self, user_id: str, receipt_id: str) -> None:
        row = self.db.one(
            "SELECT payment_id FROM vault_payments WHERE user_id = $1 AND receipt_id = $2",
            [user_id, receipt_id],
        )
        if row is not None:
            self.refund(user_id, int(row["payment_id"]))

    def _enqueue(self, user_id: str, op_id: str, method: str, args: dict) -> None:
        """Write the op, then try to send it now. Writing is idempotent on `op_id`."""
        if self.chain is None:
            return
        self.db.query(
            "INSERT INTO chain_ops (id, user_id, method, args, status, attempts, created_at)"
            " VALUES ($1, $2, $3, $4, 'pending', 0, $5) ON CONFLICT (id) DO NOTHING",
            [op_id, user_id, method, json.dumps(args), Clock.now_iso()],
        )
        self.flush(user_id)

    def flush(self, user_id: Optional[str] = None) -> int:
        """Send pending ops in order. Returns how many are still pending.

        A user's queue stops at its first transient failure, because order matters:
        deposits go first, since a debit sent ahead of the deposit it depends on
        would be refused, and a deposit never fails for want of balance.
        A user's first money movement creates their vault here; if that fails, the
        ops wait for the next pass.
        """
        if self.chain is None:
            return 0
        users = [user_id] if user_id else [
            row["user_id"] for row in self.db.query(
                "SELECT DISTINCT user_id FROM chain_ops WHERE status = 'pending'"
            )
        ]
        for uid in users:
            vault_id = self._vault_or_create(uid)
            if vault_id is None:
                continue
            with self._lock_for(uid):
                self._flush_one(uid, vault_id)
        where, params = ("WHERE status = 'pending' AND user_id = $1", [user_id]) if user_id \
            else ("WHERE status = 'pending'", [])
        return int(self.db.value(f"SELECT COUNT(*) FROM chain_ops {where}", params) or 0)

    def stuck_ops(self, user_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """Chain ops that have not gone through, oldest first: still pending, or
        refused by the contract. What blocks a user's payments, and why."""
        where, params = ("WHERE status <> 'done' AND user_id = $1", [user_id]) if user_id \
            else ("WHERE status <> 'done'", [])
        return self.db.query(
            "SELECT id, user_id, method, status, attempts, last_error, created_at"
            f" FROM chain_ops {where} ORDER BY seq LIMIT {int(limit)}", params)

    def _flush_one(self, user_id: str, vault_id: str) -> None:
        assert self.chain is not None
        ops = self.db.query(
            "SELECT id, method, args FROM chain_ops"
            " WHERE user_id = $1 AND status = 'pending'"
            " ORDER BY CASE WHEN method = 'fund' THEN 0 ELSE 1 END, seq",
            [user_id],
        )
        for op in ops:
            try:
                result = self._send_op(vault_id, op["method"], json.loads(op["args"]))
            except near_tx.ContractRefused as err:
                log.error("chain op %s (%s) refused by the contract, marked failed: %s",
                          op["id"], op["method"], err.message)
                self._finish(op["id"], "failed", None, err.message)
                continue
            except near_tx.NearRpcError as err:
                log.warning("chain op %s (%s) for user=%s not sent, will retry: %s",
                            op["id"], op["method"], user_id, err)
                self.db.query(
                    "UPDATE chain_ops SET attempts = attempts + 1, last_error = $2"
                    " WHERE id = $1",
                    [op["id"], str(err)[:300]],
                )
                return
            self._finish(op["id"], "done", result.sent_tx_hash, None)

    def _send_op(self, vault_id: str, method: str, args: dict) -> ChainResult:
        """Ops written before the vault held USDC carry naira only; they are priced now."""
        assert self.chain is not None
        if method in ("fund", "debit"):
            amount_usdc = int(args.get("amount_usdc") or self.usdc_for(int(args["amount_ngn"])))
            if method == "fund":
                return self.chain.deposit(vault_id, amount_usdc, args["reference"])
            return self.chain.call(vault_id, "debit", {"amount_usdc": str(amount_usdc),
                                                       "reference": args["reference"]})
        if method == "refund":
            payment_id = int(args["payment_id"])
            amount_usdc = int(self.chain.payment(vault_id, payment_id)["amount_usdc"])
            return self.chain.deposit(vault_id, amount_usdc, f"refund:{payment_id}")
        return self.chain.call(vault_id, method, args)

    def _finish(self, op_id: str, status: str, tx_hash: Optional[str],
                error: Optional[str]) -> None:
        self.db.query(
            "UPDATE chain_ops SET status = $2, tx_hash = $3, last_error = $4,"
            " attempts = attempts + 1 WHERE id = $1",
            [op_id, status, tx_hash, error],
        )

    # --- the authorisation ----------------------------------------------------

    def authorise_payment(self, user_id: str, meter: str, amount_ngn: int, *,
                          approved: bool = False) -> Optional[PaymentAuthorisation]:
        """Sign `pay` on this user's vault, or refuse. None when there is no chain.

        `approved` is a payment the owner approved over the caps: it goes through
        the owner-only `pay_approved`, never the agent key.

        The contract's refusal sentence (over the cap, meter not on the list) is
        passed through as-is: it is the same plain English the policy twin speaks.
        """
        if self.chain is None:
            return None
        vault_id = self.ensure(user_id)
        assert vault_id is not None
        if self.flush(user_id):
            # The queue runs in order, so a payment cannot go ahead of a deposit that
            # has not reached the vault yet. Say which op is stuck and why: an
            # unfunded treasury reads exactly like this from the outside.
            for op in self.stuck_ops(user_id):
                log.warning("payment blocked user=%s vault=%s: %s %s still pending after "
                            "%s attempt(s): %s", user_id, vault_id, op["method"], op["id"],
                            op["attempts"], op["last_error"] or "not sent yet")
            raise AuthorisationFailed(_COULD_NOT_AUTHORISE)
        try:
            self._sync_policy(vault_id, self.accounts.state(user_id).limits)
            result = (self.chain.pay_approved(vault_id, meter, amount_ngn) if approved
                      else self.chain.pay(vault_id, meter, amount_ngn))
        except near_tx.ContractRefused as err:
            log.info("payment refused by the vault user=%s vault=%s: %s",
                     user_id, vault_id, err.message)
            raise AuthorisationFailed(f"{err.message} Nothing was charged.") from err
        except near_tx.NearRpcError as err:
            log.warning("payment authorisation failed user=%s vault=%s: rpc %s",
                        user_id, vault_id, err)
            raise AuthorisationFailed(_COULD_NOT_AUTHORISE) from err
        outcome = result.value if isinstance(result.value, dict) else {}
        if result.broadcast and not outcome.get("settled"):
            log.warning("payment not settled user=%s vault=%s tx=%s",
                        user_id, vault_id, result.tx_hash)
            raise AuthorisationFailed(_NOT_SETTLED)
        return PaymentAuthorisation(result.sent_tx_hash, outcome.get("payment_id"))

    def _sync_policy(self, vault_id: str, limits: agent_layer.Limits) -> None:
        """Push the account's caps, meters and the naira rate where the vault differs.

        Skipped on a dry chain, which has nothing to read.
        """
        assert self.chain is not None
        if not self.chain.broadcast:
            return
        current = self.chain.rpc.view(vault_id, "get_policy", {})
        wanted = {
            "monthly_cap_ngn": str(limits.monthly_cap_ngn),
            "per_payment_cap_ngn": str(limits.per_payment_cap_ngn),
            "allowed_meters": sorted(limits.allowed_meters),
        }
        held = {
            "monthly_cap_ngn": current["monthly_cap_ngn"],
            "per_payment_cap_ngn": current["per_payment_cap_ngn"],
            "allowed_meters": sorted(current["allowed_meters"]),
        }
        if held != wanted:
            self.chain.call(vault_id, "set_policy", wanted)
        rate = self.usdc_per_kngn()
        if int(self.chain.state(vault_id)["usdc_per_kngn"]) != rate:
            self.chain.call(vault_id, "set_rate", {"usdc_per_kngn": str(rate)})

    # --- reconciliation -------------------------------------------------------

    def drift(self, user_id: str, wallet_balance_ngn: int) -> dict[str, Any]:
        """The vault's balance against Postgres, and the ops still in flight."""
        vault_id = self.vault_account(user_id)
        stuck = self.db.query(
            "SELECT id, method, status, last_error FROM chain_ops"
            " WHERE user_id = $1 AND status <> 'done' ORDER BY seq",
            [user_id],
        )
        report: dict[str, Any] = {"vault": vault_id, "wallet_balance_ngn": wallet_balance_ngn,
                                  "vault_balance_ngn": None, "drift_ngn": None,
                                  "unsettled_ops": stuck}
        if self.chain is None or vault_id is None or not self.chain.broadcast:
            return report
        state = self.chain.state(vault_id)
        balance = int(state["balance_ngn"])
        report["vault_balance_usdc"] = int(state["balance_usdc"])
        report["vault_balance_ngn"] = balance
        report["drift_ngn"] = balance - wallet_balance_ngn
        return report

    # --- plumbing -------------------------------------------------------------

    def _vault_or_create(self, user_id: str) -> Optional[str]:
        try:
            return self.ensure(user_id)
        except AuthorisationFailed:
            return None

    def _record_vault(self, user_id: str, vault_id: str, status: str,
                      tx_hash: Optional[str], error: Optional[str]) -> None:
        self.db.query(
            "INSERT INTO vaults (user_id, account_id, status, tx_hash, created_at, last_error)"
            " VALUES ($1, $2, $3, $4, $5, $6)"
            " ON CONFLICT (user_id) DO UPDATE SET status = EXCLUDED.status,"
            " tx_hash = EXCLUDED.tx_hash, last_error = EXCLUDED.last_error",
            [user_id, vault_id, status, tx_hash, Clock.now_iso(), error],
        )

    def _lock_for(self, user_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(user_id, threading.Lock())
