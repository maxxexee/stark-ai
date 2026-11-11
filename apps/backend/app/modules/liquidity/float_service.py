"""The float: Stark's Flutterwave NGN balance, which every bill is paid from.

A deposit is credited to the user the moment Flutterwave confirms it, but the
money only reaches the balance bills and transfers spend once Flutterwave settles
it (batched daily). Until then Stark fronts it from this balance. So before a
payment is signed, this checks that the balance can cover it:

    available = Flutterwave available balance − purchases still pending

A pending purchase has been sent to Flutterwave and may still be charged, so it is
counted as spent. If the payment does not fit, it is refused with `float_low`
(nothing signed, nothing charged) and logged, so the operator can top the balance
up. There is no refill to run: deposits settle into the same balance.

| Variable | Default | Meaning |
|---|---|---|
| `STARK_FLOAT_LOW_NGN` | 100,000 | log a warning when the balance falls under this |
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app.common.api_error import ApiError
from app.database import neon
from app.modules.flutterwave.flutterwave import FlutterwaveClient, FlutterwaveError

log = logging.getLogger("stark.float")

FLOAT_LOW_MESSAGE = (
    "I can't buy that right now, so nothing was charged. Try again in a few minutes."
)


@dataclass(frozen=True)
class FloatSettings:
    low_water_ngn: int
    cache_seconds: int = 60


class FloatService:
    def __init__(self, db: neon.Database, flutterwave: Optional[FlutterwaveClient],
                 settings: FloatSettings) -> None:
        self.db = db
        self.flutterwave = flutterwave
        self.settings = settings
        self._cached: Optional[tuple[float, int]] = None
        self._lock = threading.Lock()

    # --- reading --------------------------------------------------------------

    def balance(self, *, fresh: bool = False) -> int:
        if self.flutterwave is None:
            raise FlutterwaveError(0, "Flutterwave is not configured")
        with self._lock:
            if not fresh and self._cached is not None \
                    and time.monotonic() - self._cached[0] < self.settings.cache_seconds:
                return self._cached[1]
        value = self.flutterwave.ngn_balance()
        with self._lock:
            self._cached = (time.monotonic(), value)
        return value

    def reserved(self) -> int:
        return int(self.db.value(
            "SELECT COALESCE(SUM(amount_ngn), 0) FROM receipts WHERE status = 'pending'"
        ) or 0)

    def available(self) -> int:
        return self.balance() - self.reserved()

    # --- the check ------------------------------------------------------------

    def ensure_can_cover(self, amount_ngn: int) -> None:
        """Refuse before anything is signed when the balance cannot cover the purchase.

        A balance that cannot be read is treated the same way: buying blind is how a
        purchase fails halfway with nothing to show for it.
        """
        try:
            available = self.available()
        except FlutterwaveError as err:
            log.warning("float unreadable: %s", err)
            raise ApiError(503, "float_low", FLOAT_LOW_MESSAGE) from err
        if amount_ngn > available:
            log.warning("float is ₦%s; a ₦%s purchase was refused", f"{available:,}",
                        f"{amount_ngn:,}")
            raise ApiError(503, "float_low", FLOAT_LOW_MESSAGE, {"amount_ngn": amount_ngn})

    def check_level(self) -> None:
        """Read the balance fresh and warn if it is low. Runs after every delivered
        purchase and on every money-loop tick."""
        try:
            balance = self.balance(fresh=True)
        except FlutterwaveError:
            return
        if balance < self.settings.low_water_ngn:
            log.warning("Flutterwave NGN balance is ₦%s, under ₦%s: top it up",
                        f"{balance:,}", f"{self.settings.low_water_ngn:,}")
