"""What the operator needs to see at a glance: the money, and what is stuck.

Read-only. Served by `GET /v1/admin/overview` behind `AdminGuard`.
"""

from __future__ import annotations

import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from app.database import neon
from app.modules.chain.vault_chain import VaultChain
from app.modules.settings.operator_limits import OperatorLimits
from app.modules.settings.settings_service import SettingsService
from app.modules.treasury.operator_alerts import OperatorAlerts
from app.modules.treasury.treasury_service import TreasuryService
from app.modules.vault.vault_service import VaultService

IN_FLIGHT_LIMIT = 50
VAULT_LIMIT = 100
EGRESS_ECHO = "https://api.ipify.org"


class AdminService:
    def __init__(self, db: neon.Database, treasury: TreasuryService,
                 vaults: VaultService, settings: SettingsService,
                 alerts: OperatorAlerts, limits: OperatorLimits) -> None:
        self.db = db
        self.treasury = treasury
        self.vaults = vaults
        self.chain: Optional[VaultChain] = vaults.chain
        self.settings = settings
        self.alerts = alerts
        self.limits = limits

    def overview(self) -> dict[str, Any]:
        """Every part is an independent query or network call, so they run at once."""
        with ThreadPoolExecutor(max_workers=8) as pool:
            report = pool.submit(self.treasury.report, fresh=False)
            deposits = pool.submit(self._by_status, "deposits")
            withdrawals = pool.submit(self._by_status, "withdrawals")
            in_flight = pool.submit(
                self.db.query,
                "SELECT id, user_id, method, amount_ngn, status, note, created_at,"
                " updated_at FROM withdrawals WHERE status IN ('sending', 'processing')"
                " ORDER BY created_at LIMIT $1",
                [IN_FLIGHT_LIMIT],
            )
            open_deposits = pool.submit(
                self.db.query,
                "SELECT id, user_id, method, amount_ngn, status, created_at, expires_at"
                " FROM deposits WHERE status IN ('open', 'confirming')"
                " ORDER BY created_at LIMIT $1",
                [IN_FLIGHT_LIMIT],
            )
            vaults = pool.submit(
                self.db.query,
                "SELECT user_id, account_id, status, created_at, last_error FROM vaults"
                " ORDER BY created_at DESC LIMIT $1",
                [VAULT_LIMIT],
            )
            stuck = pool.submit(self.vaults.stuck_ops) if self.vaults.enabled else None
            alerts = pool.submit(self.alerts.recent)
            ip = pool.submit(egress_ip)
            fees = pool.submit(self.settings.fees)
            limits = pool.submit(self.limits.all)
        treasury = report.result()
        usdc = treasury["treasury_usdc"]
        return {
            "treasury": {**treasury, "treasury_usdc": None if usdc is None else str(usdc)},
            "deposits": deposits.result(),
            "withdrawals": withdrawals.result(),
            "withdrawals_in_flight": in_flight.result(),
            "deposits_open": open_deposits.result(),
            "chain": None if self.chain is None else {
                "network": self.chain.network,
                "funder": self.chain.funder_id,
                "usdc": self.chain.usdc_id,
            },
            # What needs the operator now, and what did recently: raised by the money
            # loop's watch, shown here rather than sent to anyone's chat.
            "alerts": alerts.result(),
            "vaults": vaults.result(),
            # What is holding payments up on chain, with the chain's own reason.
            "chain_ops_stuck": stuck.result() if stuck is not None else [],
            "egress_ip": ip.result(),
            "fees_ngn": fees.result(),
            "limits": limits.result(),
        }

    def _by_status(self, table: str) -> list[dict[str, Any]]:
        # `table` is one of two literals above, never input.
        return self.db.query(
            f"SELECT method, status, COUNT(*)::int AS count,"
            f" COALESCE(SUM(amount_ngn), 0)::bigint AS amount_ngn"
            f" FROM {table} GROUP BY method, status ORDER BY method, status"
        )


_egress: tuple[float, str] | None = None
EGRESS_CACHE_SECONDS = 600


def egress_ip() -> Optional[str]:
    """The address this server's outbound calls come from, which is what Flutterwave's
    IP whitelist needs. Kept for ten minutes, since it only changes with a redeploy.
    None when the echo service can't be reached."""
    global _egress
    if _egress is not None and time.monotonic() - _egress[0] < EGRESS_CACHE_SECONDS:
        return _egress[1]
    try:
        with urllib.request.urlopen(urllib.request.Request(
                EGRESS_ECHO, headers={"User-Agent": "stark-backend/1.0"}), timeout=5) as res:
            ip = res.read().decode().strip()
    except OSError:
        return None
    _egress = (time.monotonic(), ip)
    return ip
