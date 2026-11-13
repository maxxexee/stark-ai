"""Where Stark's money is, against what it owes — and the loop that keeps it moving.

**Coverage.** Every naira in a user's wallet is a promise Stark must be able to
keep. It is covered by money Stark actually holds:

    owed     = Σ wallet balances
    held     = Flutterwave NGN balance − pending purchases + treasury USDC × rate
               + vault USDC × rate   (mainnet vaults only)
    coverage = held − owed           (must never go negative)

A deposit moves the treasury's USDC into the user's vault, so the vaults hold the
backing for most wallet balances. Vaults on testnet hold test tokens, worth
nothing: they are shown in `report()` but left out of coverage.

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
5. read both balances and alert the operator on Telegram (`TreasuryWatch`).

Open deposits are not here: each has its own due time (`DepositService.check_due`).

Each step is idempotent and isolated: one failing never stops the others.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any, Callable, Optional, TypeVar

from app.database import neon
from app.modules.flutterwave.flutterwave import FlutterwaveError
from app.modules.chain import near_tx
from app.modules.intents import one_click
from app.modules.liquidity.float_service import FloatService
from app.modules.liquidity.usdc_rate import RateUnavailable, UsdcRate
from app.modules.payment.bill_payment_service import BillPaymentService
from app.modules.treasury.treasury_watch import TreasuryWatch
from app.modules.vault.vault_service import VaultService
from app.modules.wallet.deposit_service import DepositService
from app.modules.wallet.crypto_withdrawal_service import CryptoWithdrawalService
from app.modules.wallet.withdrawal_service import WithdrawalService

log = logging.getLogger("stark.treasury")
USDC_CONTRACT = one_click.USDC_NEAR.split(":", 1)[1]
T = TypeVar("T")


class TreasuryService:
    def __init__(self, db: neon.Database, vaults: VaultService, deposits: DepositService,
                 bill_payments: BillPaymentService,
                 withdrawals: WithdrawalService, crypto_withdrawals: CryptoWithdrawalService,
                 floats: FloatService, treasury_account: Optional[str],
                 usdc_rate: UsdcRate,
                 mainnet_rpc: near_tx.NearRpc, watch: TreasuryWatch) -> None:
        self.db = db
        self.vaults = vaults
        self.deposits = deposits
        self.bill_payments = bill_payments
        self.withdrawals = withdrawals
        self.crypto_withdrawals = crypto_withdrawals
        self.floats = floats
        self.treasury_account = treasury_account
        self.usdc_rate = usdc_rate
        self.mainnet_rpc = mainnet_rpc
        self.watch = watch

    def report(self, *, fresh: bool = True) -> dict[str, Any]:
        """Each balance is a separate network call, so they are read at the same time.

        `fresh=False` reuses the Flutterwave balance the money loop read in the last
        minute, which is what the admin page wants: it is a view, not an alarm.
        """
        with ThreadPoolExecutor(max_workers=7) as pool:
            owed = pool.submit(self.db.value,
                               "SELECT COALESCE(SUM(balance_ngn), 0) FROM wallets")
            usdc = pool.submit(_read, self._treasury_usdc) if self.treasury_account else None
            flutterwave = pool.submit(_read, lambda: self.floats.balance(fresh=fresh))
            reserved = pool.submit(self.floats.reserved)
            vault_usdc = pool.submit(_read, self.vaults.holdings) \
                if self.vaults.holds_usdc else None
            rate = pool.submit(_read, self.usdc_rate.market)
            stuck = pool.submit(self.db.value,
                                "SELECT COUNT(*) FROM chain_ops WHERE status <> 'done'")
        usdc_held = usdc.result() if usdc is not None else None
        in_vaults = vault_usdc.result() if vault_usdc is not None else None
        market = rate.result()
        held: dict[str, Optional[int]] = {
            "flutterwave_ngn": flutterwave.result(),
            "pending_purchases_ngn": reserved.result(),
            "treasury_usdc_as_ngn": _as_ngn(usdc_held, market),
            "vaults_usdc_as_ngn": _as_ngn(in_vaults.usdc if in_vaults else None, market),
        }
        vaults = None
        if self.vaults.holds_usdc:
            network = self.vaults.chain.network  # type: ignore[union-attr]
            vaults = {"network": network,
                      "count": in_vaults.count if in_vaults else None,
                      "usdc": in_vaults.usdc if in_vaults else None,
                      "counted": network == "mainnet"}
        counted = [held["flutterwave_ngn"], held["treasury_usdc_as_ngn"]]
        if vaults is not None and vaults["counted"]:
            counted.append(held["vaults_usdc_as_ngn"])
        owed = int(owed.result() or 0)
        stuck_ops = int(stuck.result() or 0)
        return {
            "owed_to_users_ngn": owed,
            "held": held,
            "treasury_usdc": usdc_held,
            "vaults": vaults,
            "coverage_ngn": sum(v for v in counted if v is not None)
            - held["pending_purchases_ngn"] - owed,
            "unsettled_vault_ops": stuck_ops,
        }

    def _treasury_usdc(self) -> Decimal:
        raw = self.mainnet_rpc.view(USDC_CONTRACT, "ft_balance_of",
                                    {"account_id": self.treasury_account})
        return Decimal(str(raw)) / 10 ** one_click.USDC_DECIMALS

    # --- the loop -------------------------------------------------------------

    def tick(self) -> None:
        for step in (self.vaults.flush, self.bill_payments.settle_pending,
                     self.withdrawals.advance,
                     self.crypto_withdrawals.advance, self.watch_levels):
            try:
                step()
            except Exception:  # one rail being down must not stop the others
                log.exception("money loop step %s failed", step.__name__)

    def watch_levels(self) -> None:
        self.watch.check(self.report())

    def start(self, tick_seconds: int) -> threading.Event:
        stop = threading.Event()

        def run() -> None:
            while not stop.wait(tick_seconds):
                self.tick()

        threading.Thread(target=run, daemon=True, name="money").start()
        return stop


def _read(read: Callable[[], T]) -> Optional[T]:
    """A balance that could not be read is unknown, not zero."""
    try:
        return read()
    except (FlutterwaveError, near_tx.NearRpcError, RateUnavailable) as err:
        log.warning("balance unreadable: %s", err)
        return None


def _as_ngn(usdc: Optional[Decimal], market: Optional[Decimal]) -> Optional[int]:
    return None if usdc is None or market is None else int(usdc * market)


def _main() -> None:  # pragma: no cover - operator CLI
    import json

    from app.app_module import AppModule

    print(json.dumps(AppModule.from_env().treasury.report(), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    _main()
