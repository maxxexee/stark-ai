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
`[STARK_USDC_RATE_MIN, STARK_USDC_RATE_MAX]`, or one that moved more than
`STARK_USDC_RATE_MAX_MOVE` (a fraction) from the last rate accepted, is treated like
Paycrest being down: the last good rate covers the fifteen minutes, then quotes are
refused until Paycrest comes back in range, or the owner pins the rate. A genuine
devaluation bigger than the move limit therefore needs the owner, on purpose: a
wrong rate here sends real USDC. A spread that leaves either side at or below zero
is refused the same way.

| Variable | Default | Meaning |
|---|---|---|
| `STARK_USDC_NGN_SPREAD` | 10 | naira Stark keeps per USDC, each way |
| `STARK_USDC_NGN_RATE` | unset | pin the market rate instead of asking Paycrest |
| `STARK_USDC_RATE_MIN` / `STARK_USDC_RATE_MAX` | 500 / 5000 | naira per USDC Paycrest may quote |
| `STARK_USDC_RATE_MAX_MOVE` | 0.15 | largest move from the last accepted rate |
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

log = logging.getLogger("stark.rate")

PAYCREST_URL = "https://api.paycrest.io/v1/rates/USDC/100/NGN"
USER_AGENT = "stark-backend/1.0 (+https://hellostark.xyz)"
FRESH_SECONDS = 60
STALE_SECONDS = 15 * 60
RATE_MIN = Decimal(500)
RATE_MAX = Decimal(5000)
MAX_MOVE = Decimal("0.15")


class RateUnavailable(Exception):
    pass


class UsdcRate:
    def __init__(self, *, spread_ngn: Decimal, fixed: Optional[Decimal] = None,
                 floor: Decimal = RATE_MIN, ceiling: Decimal = RATE_MAX,
                 max_move: Decimal = MAX_MOVE, timeout: int = 10) -> None:
        self.spread_ngn = spread_ngn
        self.fixed = fixed
        self.floor = floor
        self.ceiling = ceiling
        self.max_move = max_move
        self.timeout = timeout
        self._lock = threading.Lock()
        self._market: Optional[Decimal] = None
        self._fetched_at = 0.0

    def buying(self) -> Decimal:
        """Naira Stark credits per USDC it receives (crypto deposits)."""
        return _priced(self.market() - self.spread_ngn)

    def selling(self) -> Decimal:
        """Naira Stark charges per USDC it sends (crypto withdrawals)."""
        return _priced(self.market() + self.spread_ngn)

    def market(self) -> Decimal:
        if self.fixed is not None:
            return self.fixed
        with self._lock:
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
        if not self.floor <= rate <= self.ceiling:
            log.error("Paycrest quoted %s naira per USDC, outside %s to %s",
                      rate, self.floor, self.ceiling)
            raise RateUnavailable(f"Paycrest rate {rate} is outside the allowed range")
        last = self._market
        if last is not None and abs(rate - last) > last * self.max_move:
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
