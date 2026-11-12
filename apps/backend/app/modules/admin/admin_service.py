"""What the operator needs to see at a glance: the money, and what is stuck.

Read-only. Served by `GET /v1/admin/overview` behind `AdminGuard`.
"""

from __future__ import annotations

from typing import Any

from app.database import neon
from app.modules.treasury.treasury_service import TreasuryService

IN_FLIGHT_LIMIT = 50


class AdminService:
    def __init__(self, db: neon.Database, treasury: TreasuryService) -> None:
        self.db = db
        self.treasury = treasury

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
        }

    def _by_status(self, table: str) -> list[dict[str, Any]]:
        # `table` is one of two literals above, never input.
        return self.db.query(
            f"SELECT method, status, COUNT(*)::int AS count,"
            f" COALESCE(SUM(amount_ngn), 0)::bigint AS amount_ngn"
            f" FROM {table} GROUP BY method, status ORDER BY method, status"
        )
