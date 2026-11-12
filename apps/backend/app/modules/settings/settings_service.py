"""Business settings the owner edits on the admin page.

They live in Postgres rather than the environment, so a change applies to the next
payment without a deploy.
"""

from __future__ import annotations

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.database import neon

# The service fee Stark adds to a bill of each kind, in naira. Flutterwave charges ₦100
# on electricity and TV and pays a commission on airtime and data instead.
DEFAULT_FEES_NGN = {"electricity": 100, "tv": 100, "airtime": 0, "data": 0}
MAX_FEE_NGN = 5_000


class SettingsService:
    def __init__(self, db: neon.Database) -> None:
        self.db = db

    def fees(self) -> dict[str, int]:
        stored = {
            row["key"].removeprefix("fee:"): int(row["value"])
            for row in self.db.query("SELECT key, value FROM settings WHERE key LIKE 'fee:%'")
        }
        return {kind: stored.get(kind, default) for kind, default in DEFAULT_FEES_NGN.items()}

    def fee_for(self, kind: str) -> int:
        return self.fees().get(kind, 0)

    def set_fees(self, changes: dict[str, int]) -> dict[str, int]:
        unknown = sorted(set(changes) - set(DEFAULT_FEES_NGN))
        if unknown:
            raise ApiError(400, "unknown_fee", f"There is no fee for {', '.join(unknown)}.")
        for fee in changes.values():
            if not 0 <= fee <= MAX_FEE_NGN:
                raise ApiError(400, "bad_fee", f"A fee must be between ₦0 and ₦{MAX_FEE_NGN:,}.")
        for kind, fee in changes.items():
            self.db.query(
                "INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, $3)"
                " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,"
                " updated_at = EXCLUDED.updated_at",
                [f"fee:{kind}", fee, Clock.now_iso()],
            )
        return self.fees()
