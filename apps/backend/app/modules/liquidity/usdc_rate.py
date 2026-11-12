"""Naira per USDC: Paycrest's live rate, with Stark's spread on each side.

Paycrest is the liquidity network behind Noblocks. Its public rate endpoint needs
no key and quotes what its providers pay in naira for one USDC:

    GET https://api.paycrest.io/v1/rates/USDC/<amount>/NGN
    → {"status": "success", "data": "1380.56"}

Stark earns the spread on both rails:

| Rail | Stark | Rate used |
|---|---|---|
| crypto deposit | buys the user's USDC | market − spread (`buying`) |
| crypto withdrawal | sells the treasury's USDC | market + spread (`selling`) |

Each deposit stores the rate it was quoted at, so a later move never changes a
credit already promised.

The market rate is kept for a minute. If Paycrest cannot be reached, the last good
rate stays usable for fifteen minutes; after that `RateUnavailable` is raised and
the caller refuses the quote rather than guess a price.

**Paycrest is the only source, so its answer is bounded.** A rate outside
`usdc_rate_min`..`usdc_rate_max`, or one that moved more than
`usdc_rate_max_move_pct` from the last rate accepted, is treated like Paycrest being
down: the last good rate covers the fifteen minutes, then quotes are refused until
Paycrest comes back in range, or the owner pins the rate. A genuine devaluation
bigger than the move limit therefore needs the owner, on purpose: a wrong rate here
sends real USDC. A spread that leaves either side at or below zero is refused the
same way.

The spread, the pin and the bounds are operator limits (`OperatorLimits`), set on
the admin page and read on every quote, so a change applies within seconds:

| Limit | Default | Meaning |
|---|---|---|
| `usdc_spread_ngn` | 10 | naira Stark keeps per USDC, each way |
| `usdc_rate_pinned` | 0 | the market rate to use instead of asking Paycrest; 0 asks |
| `usdc_rate_min` / `usdc_rate_max` | 500 / 5000 | naira per USDC Paycrest may quote |
| `usdc_rate_max_move_pct` | 15 | largest move, in percent, from the last accepted rate |

While a rate is pinned it counts as the last one accepted, so the first Paycrest
quote after the pin is lifted is held to the move limit from it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.modules.settings.operator_limits import OperatorLimits

log = logging.getLogger("stark.rate")

PAYCREST_URL = "https://api.paycrest.io/v1/rates/USDC/100/NGN"
USER_AGENT = "stark-backend/1.0 (+https://hellostark.xyz)"
FRESH_SECONDS = 60
STALE_SECONDS = 15 * 60


class RateUnavailable(Exception):
    pass


class UsdcRate:
    def __init__(self, limits: OperatorLimits, *, timeout: int = 10) -> None:
        self.limits = limits
        self.timeout = timeout
        self._lock = threading.Lock()
        self._market: Optional[Decimal] = None
        self._fetched_at = 0.0

    def buying(self) -> Decimal:
        """Naira Stark credits per USDC it receives (crypto deposits)."""
        return _priced(self.market() - self.limits.get("usdc_spread_ngn"))

    def selling(self) -> Decimal:
        """Naira Stark charges per USDC it sends (crypto withdrawals)."""
        return _priced(self.market() + self.limits.get("usdc_spread_ngn"))

    def market(self) -> Decimal:
        pinned = self.limits.get("usdc_rate_pinned")
        with self._lock:
            if pinned:
                # Never fetched, so lifting the pin asks Paycrest at once, and an
                # outage then refuses rather than keep quoting the old pin.
                self._market, self._fetched_at = Decimal(pinned), float("-inf")
                return self._market
            age = time.monotonic() - self._fetched_at
            if self._market is not None and age < FRESH_SECONDS:
                return self._market
            try:
                self._market = self._accept(self._fetch())
                self._fetched_at = time.monotonic()
            except RateUnavailable as err:
                if self._market is None or age >= STALE_SECONDS:
                    raise
                log.warning("%s; using the rate from %ds ago", err, int(age))
            return self._market

    def _accept(self, rate: Decimal) -> Decimal:
        """The fetched rate, or `RateUnavailable` if it is out of bounds."""
        floor = self.limits.get("usdc_rate_min")
        ceiling = self.limits.get("usdc_rate_max")
        if not floor <= rate <= ceiling:
            log.error("Paycrest quoted %s naira per USDC, outside %s to %s",
                      rate, floor, ceiling)
            raise RateUnavailable(f"Paycrest rate {rate} is outside the allowed range")
        last = self._market
        max_move_pct = self.limits.get("usdc_rate_max_move_pct")
        if last is not None and abs(rate - last) * 100 > last * max_move_pct:
            log.error("Paycrest rate jumped from %s to %s; not using it", last, rate)
            raise RateUnavailable(f"Paycrest rate moved from {last} to {rate}")
        return rate

    def _fetch(self) -> Decimal:
        request = urllib.request.Request(
            PAYCREST_URL, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
            rate = Decimal(body["data"])
        except (urllib.error.URLError, ValueError, KeyError, TypeError,
                InvalidOperation) as err:
            raise RateUnavailable(f"Paycrest rate unavailable: {err}") from err
        if body.get("status") != "success" or rate <= 0:
            raise RateUnavailable(f"Paycrest returned {body!r}")
        return rate


def _priced(rate: Decimal) -> Decimal:
    """A side of the spread is only a price while it is above zero."""
    if rate <= 0:
        raise RateUnavailable(f"the spread leaves a rate of {rate}")
    return rate
