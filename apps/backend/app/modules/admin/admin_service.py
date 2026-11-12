"""What the operator needs to see at a glance: the money, and what is stuck.

Read-only. Served by `GET /v1/admin/overview` behind `AdminGuard`.
"""

from __future__ import annotations

import urllib.request
from typing import Any, Optional

from app.database import neon
from app.modules.chain.vault_chain import VaultChain
from app.modules.treasury.treasury_service import TreasuryService

IN_FLIGHT_LIMIT = 50
VAULT_LIMIT = 100
EGRESS_ECHO = "https://api.ipify.org"


class AdminService:
    def __init__(self, db: neon.Database, treasury: TreasuryService,
                 chain: Optional[VaultChain]) -> None:
        self.db = db
        self.treasury = treasury
        self.chain = chain

    def overview(self) -> dict[str, Any]:
        report = self.treasury.report()
        usdc = report["treasury_usdc"]
        return {
            "treasury": {**report, "treasury_usdc": None if usdc is None else str(usdc)},
            "deposits": self._by_status("deposits"),
            "withdrawals": self._by_status("withdrawals"),
            "withdrawals_in_flight": self.db.query(
                "SELECT id, user_id, method, amount_ngn, status, note, created_at,"
                " updated_at FROM withdrawals WHERE status IN ('sending', 'processing')"
                " ORDER BY created_at LIMIT $1",
                [IN_FLIGHT_LIMIT],
            ),
            "deposits_open": self.db.query(
                "SELECT id, user_id, method, amount_ngn, status, created_at, expires_at"
                " FROM deposits WHERE status IN ('open', 'confirming')"
                " ORDER BY created_at LIMIT $1",
                [IN_FLIGHT_LIMIT],
            ),
            "chain": None if self.chain is None else {
                "network": self.chain.network,
                "funder": self.chain.funder_id,
                "usdc": self.chain.usdc_id,
            },
            "vaults": self.db.query(
                "SELECT user_id, account_id, status, created_at, last_error FROM vaults"
                " ORDER BY created_at DESC LIMIT $1",
                [VAULT_LIMIT],
            ),
            "egress_ip": egress_ip(),
        }

    def _by_status(self, table: str) -> list[dict[str, Any]]:
        # `table` is one of two literals above, never input.
        return self.db.query(
            f"SELECT method, status, COUNT(*)::int AS count,"
            f" COALESCE(SUM(amount_ngn), 0)::bigint AS amount_ngn"
            f" FROM {table} GROUP BY method, status ORDER BY method, status"
        )


def egress_ip() -> Optional[str]:
    """The address this server's outbound calls come from, which is what Flutterwave's
    IP whitelist needs. None when the echo service can't be reached."""
    try:
        with urllib.request.urlopen(urllib.request.Request(
                EGRESS_ECHO, headers={"User-Agent": "stark-backend/1.0"}), timeout=5) as res:
            return res.read().decode().strip()
    except OSError:
        return None
