"""What the operator should act on, kept for the admin page instead of sent to a chat.

One row per alarm (`flutterwave`, `treasury`, `coverage`): raised when its condition
starts, updated while it lasts, cleared when it ends. Being in the database, an
alarm survives a restart and the admin page can show what is wrong now and what
was wrong recently, without anyone having to be linked on Telegram.
"""

from __future__ import annotations

from typing import Any

from app.common.clock import Clock
from app.database import neon

RECENT_DAYS = 7


class OperatorAlerts:
    def __init__(self, db: neon.Database) -> None:
        self.db = db

    def raise_alarm(self, kind: str, message: str) -> bool:
        """Raise `kind`, or refresh its message while it lasts. True when it is new:
        it was clear, or had never been raised."""
        # `prev` reads the row as it was before this statement wrote it, so "new" is
        # decided by state, not by comparing timestamps a second apart.
        row = self.db.one(
            "WITH prev AS (SELECT cleared_at FROM operator_alerts WHERE kind = $1),"
            " up AS (INSERT INTO operator_alerts (kind, message, raised_at, cleared_at,"
            " cleared_message, updated_at) VALUES ($1, $2, $3, NULL, NULL, $3)"
            " ON CONFLICT (kind) DO UPDATE SET message = EXCLUDED.message,"
            " updated_at = EXCLUDED.updated_at,"
            " raised_at = CASE WHEN operator_alerts.cleared_at IS NULL"
            " THEN operator_alerts.raised_at ELSE EXCLUDED.raised_at END,"
            " cleared_at = NULL, cleared_message = NULL RETURNING kind)"
            " SELECT NOT EXISTS (SELECT 1 FROM prev WHERE cleared_at IS NULL) AS new"
            " FROM up",
            [kind, message, Clock.now_iso()],
        )
        return bool(row and row["new"])

    def clear(self, kind: str, message: str) -> bool:
        """Clear `kind` if it is raised. True when this call cleared it."""
        now = Clock.now_iso()
        row = self.db.one(
            "UPDATE operator_alerts SET cleared_at = $2, cleared_message = $3,"
            " updated_at = $2 WHERE kind = $1 AND cleared_at IS NULL RETURNING kind",
            [kind, now, message],
        )
        return row is not None

    def recent(self) -> list[dict[str, Any]]:
        """Raised alarms first, then those cleared in the last week, newest first."""
        return self.db.query(
            "SELECT kind, message, raised_at, cleared_at, cleared_message, updated_at"
            " FROM operator_alerts WHERE cleared_at IS NULL OR cleared_at > $1"
            " ORDER BY (cleared_at IS NULL) DESC, updated_at DESC",
            [Clock.ago(days=RECENT_DAYS)],
        )
