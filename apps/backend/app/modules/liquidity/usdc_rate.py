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

| Variable | Default | Meaning |
|---|---|---|
| `STARK_USDC_NGN_SPREAD` | 10 | naira Stark keeps per USDC, each way |
| `STARK_USDC_NGN_RATE` | unset | pin the market rate instead of asking Paycrest |
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


class RateUnavailable(Exception):
    pass


class UsdcRate:
    def __init__(self, *, spread_ngn: Decimal, fixed: Optional[Decimal] = None,
                 timeout: int = 10) -> None:
        self.spread_ngn = spread_ngn
        self.fixed = fixed
        self.timeout = timeout
        self._lock = threading.Lock()
        self._market: Optional[Decimal] = None
        self._fetched_at = 0.0

    def buying(self) -> Decimal:
        """Naira Stark credits per USDC it receives (crypto deposits)."""
        return self.market() - self.spread_ngn

    def selling(self) -> Decimal:
        """Naira Stark charges per USDC it sends (crypto withdrawals)."""
        return self.market() + self.spread_ngn

    def market(self) -> Decimal:
        if self.fixed is not None:
            return self.fixed
        with self._lock:
            age = time.monotonic() - self._fetched_at
            if self._market is not None and age < FRESH_SECONDS:
                return self._market
            try:
                self._market = self._fetch()
                self._fetched_at = time.monotonic()
            except RateUnavailable:
                if self._market is None or age >= STALE_SECONDS:
                    raise
                log.warning("Paycrest unreachable; using the rate from %ds ago", int(age))
            return self._market

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
