"""Where Stark's money is, against what it owes — and the loop that keeps it moving.

**Coverage.** Every naira in a user's wallet is a promise Stark must be able to
keep. It is covered by money Stark actually holds:

    owed     = Σ wallet balances
    held     = Flutterwave NGN balance − pending purchases + treasury USDC × rate
    coverage = held − owed           (must never go negative)

Collections Flutterwave has not settled yet are not in its balance, so right after
a run of deposits coverage dips until settlement; it must recover by the next day.

`report()` prints both sides; `python -m app.modules.treasury.treasury_service`
runs it from a shell. Treasury USDC is read through NEAR RPC when a treasury
account is configured.

**The money loop** (`start`) runs every `STARK_MONEY_TICK` seconds (default 30):

1. send vault ops that are still pending (`VaultService.flush`);
2. settle bill purchases that came back pending (`BillPaymentService.settle_pending`);
3. send bank withdrawals not yet taken, and re-read ones in flight;
4. send held crypto withdrawals and follow their swaps;
5. read the float, and warn if it is low.

Open deposits are not here: each has its own due time (`DepositService.check_due`).

Each step is idempotent and isolated: one failing never stops the others.
"""

from __future__ import annotations

import logging
import threading
from decimal import Decimal
from typing import Any, Callable, Optional

from app.database import neon
from app.modules.flutterwave.flutterwave import FlutterwaveError
from app.modules.chain import near_tx
from app.modules.intents import one_click
from app.modules.liquidity.float_service import FloatService
from app.modules.payment.bill_payment_service import BillPaymentService
from app.modules.vault.vault_service import VaultService
from app.modules.wallet.deposit_service import DepositService
from app.modules.wallet.crypto_withdrawal_service import CryptoWithdrawalService
from app.modules.wallet.withdrawal_service import WithdrawalService

log = logging.getLogger("stark.treasury")
USDC_CONTRACT = one_click.USDC_NEAR.split(":", 1)[1]


class TreasuryService:
    def __init__(self, db: neon.Database, vaults: VaultService, deposits: DepositService,
                 bill_payments: BillPaymentService,
                 withdrawals: WithdrawalService, crypto_withdrawals: CryptoWithdrawalService,
                 floats: FloatService, treasury_account: Optional[str],
                 usdc_ngn_rate: Optional[Decimal],
                 mainnet_rpc: near_tx.NearRpc) -> None:
        self.db = db
        self.vaults = vaults
        self.deposits = deposits
        self.bill_payments = bill_payments
        self.withdrawals = withdrawals
        self.crypto_withdrawals = crypto_withdrawals
        self.floats = floats
        self.treasury_account = treasury_account
        self.usdc_ngn_rate = usdc_ngn_rate
        self.mainnet_rpc = mainnet_rpc

    def report(self) -> dict[str, Any]:
        owed = int(self.db.value("SELECT COALESCE(SUM(balance_ngn), 0) FROM wallets") or 0)
        held: dict[str, Optional[int]] = {
            "flutterwave_ngn": _read(lambda: self.floats.balance(fresh=True)),
            "pending_purchases_ngn": self.floats.reserved(),
            "treasury_usdc_as_ngn": _read(self._treasury_usdc_as_ngn),
        }
        known = sum(v for k, v in held.items() if v is not None and k != "pending_purchases_ngn")
        stuck_ops = int(self.db.value(
            "SELECT COUNT(*) FROM chain_ops WHERE status <> 'done'"
        ) or 0)
        return {
            "owed_to_users_ngn": owed,
            "held": held,
            "coverage_ngn": known - held["pending_purchases_ngn"] - owed,
            "unsettled_vault_ops": stuck_ops,
        }

    def _treasury_usdc_as_ngn(self) -> Optional[int]:
        if not (self.treasury_account and self.usdc_ngn_rate):
            return None
        raw = self.mainnet_rpc.view(USDC_CONTRACT, "ft_balance_of",
                                    {"account_id": self.treasury_account})
        usdc = Decimal(str(raw)) / 10 ** one_click.USDC_DECIMALS
        return int(usdc * self.usdc_ngn_rate)

    # --- the loop -------------------------------------------------------------

    def tick(self) -> None:
        for step in (self.vaults.flush, self.bill_payments.settle_pending,
                     self.withdrawals.advance,
                     self.crypto_withdrawals.advance, self.floats.check_level):
            try:
                step()
            except Exception:  # one rail being down must not stop the others
                log.exception("money loop step %s failed", step.__name__)

    def start(self, tick_seconds: int) -> threading.Event:
        stop = threading.Event()

        def run() -> None:
            while not stop.wait(tick_seconds):
                self.tick()

        threading.Thread(target=run, daemon=True, name="money").start()
        return stop


def _read(read: Callable[[], Optional[int]]) -> Optional[int]:
    """A balance that could not be read is unknown, not zero."""
    try:
        return read()
    except (FlutterwaveError, near_tx.NearRpcError) as err:
        log.warning("balance unreadable: %s", err)
        return None


def _main() -> None:  # pragma: no cover - operator CLI
    import json

    from app.app_module import AppModule

    print(json.dumps(AppModule.from_env().treasury.report(), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    _main()
