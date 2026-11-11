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
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from app.common.clock import Clock
from app.database import neon
from app.modules.account.account_service import AccountService
from app.modules.agent import agent as agent_layer
from app.modules.chain import near_tx
from app.modules.chain.vault_chain import VaultChain


class AuthorisationFailed(Exception):
    """The vault did not authorise the payment. `message` is safe to say aloud."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class PaymentAuthorisation:
    tx_hash: str
    # None when the transaction was signed dry and never sent.
    payment_id: Optional[int]


_COULD_NOT_AUTHORISE = "I couldn't authorise that payment just now. Nothing was charged."


class VaultService:
    def __init__(self, db: neon.Database, chain: Optional[VaultChain],
                 accounts: AccountService) -> None:
        self.db = db
        self.chain = chain
        self.accounts = accounts
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.chain is not None

    # --- the vault itself -----------------------------------------------------

    def vault_account(self, user_id: str) -> Optional[str]:
        row = self.db.one(
            "SELECT account_id FROM vaults WHERE user_id = $1 AND status = 'ready'", [user_id]
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
                    monthly_cap_ngn=limits.monthly_cap_ngn,
                    per_payment_cap_ngn=limits.per_payment_cap_ngn,
                    meters=sorted(limits.allowed_meters),
                )
            except (near_tx.NearRpcError, near_tx.ContractRefused) as err:
                self._record_vault(user_id, vault_id, "failed", None, str(err))
                raise AuthorisationFailed(_COULD_NOT_AUTHORISE) from err
            self._record_vault(user_id, vault_id, "ready", result.tx_hash, None)
            return vault_id

    # --- outbox ---------------------------------------------------------------

    def credit(self, user_id: str, amount_ngn: int, reference: str) -> None:
        self._enqueue(user_id, f"fund:{reference}", "fund",
                      {"amount_ngn": str(amount_ngn), "reference": reference})

    def debit(self, user_id: str, amount_ngn: int, reference: str) -> None:
        self._enqueue(user_id, f"debit:{reference}", "debit",
                      {"amount_ngn": str(amount_ngn), "reference": reference})

    def refund(self, user_id: str, payment_id: int) -> None:
        self._enqueue(user_id, f"refund:{payment_id}", "refund", {"payment_id": payment_id})

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
        a debit sent ahead of the deposit it depends on would be refused.
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

    def _flush_one(self, user_id: str, vault_id: str) -> None:
        assert self.chain is not None
        ops = self.db.query(
            "SELECT id, method, args FROM chain_ops"
            " WHERE user_id = $1 AND status = 'pending' ORDER BY seq",
            [user_id],
        )
        for op in ops:
            try:
                result = self.chain.call(vault_id, op["method"], json.loads(op["args"]))
            except near_tx.ContractRefused as err:
                self._finish(op["id"], "failed", None, err.message)
                continue
            except near_tx.NearRpcError as err:
                self.db.query(
                    "UPDATE chain_ops SET attempts = attempts + 1, last_error = $2"
                    " WHERE id = $1",
                    [op["id"], str(err)[:300]],
                )
                return
            self._finish(op["id"], "done", result.tx_hash, None)

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
            raise AuthorisationFailed(_COULD_NOT_AUTHORISE)
        try:
            self._sync_policy(vault_id, self.accounts.state(user_id).limits)
            result = (self.chain.pay_approved(vault_id, meter, amount_ngn) if approved
                      else self.chain.pay(vault_id, meter, amount_ngn))
        except near_tx.ContractRefused as err:
            raise AuthorisationFailed(f"{err.message} Nothing was charged.") from err
        except near_tx.NearRpcError as err:
            raise AuthorisationFailed(_COULD_NOT_AUTHORISE) from err
        payment_id = result.value.get("payment_id") if isinstance(result.value, dict) else None
        return PaymentAuthorisation(result.tx_hash, payment_id)

    def _sync_policy(self, vault_id: str, limits: agent_layer.Limits) -> None:
        """Push the account's caps and meters if the vault holds different ones.

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
        balance = int(self.chain.state(vault_id)["balance_ngn"])
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
