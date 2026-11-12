"""Raise an operator alert when the money needs a hand.

Runs as the money loop's last step, on the report `TreasuryService.report()` just
built, and records alarms in `OperatorAlerts`, which the admin page shows:

- **Flutterwave low**: the NGN balance is under `STARK_FLOAT_LOW_NGN`. Bills and
  bank withdrawals are refused once it cannot cover them.
- **Treasury low**: the treasury holds less USDC than `STARK_TREASURY_LOW_USDC`.
  Crypto withdrawals are paid from it.
- **Coverage negative**: Stark holds less than it owes its users.

An alarm is raised when its condition starts and cleared when it ends; each change
is also logged. A balance that could not be read changes nothing: unknown is not
low, and not recovered either.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.modules.treasury.operator_alerts import OperatorAlerts

log = logging.getLogger("stark.treasury")


@dataclass(frozen=True)
class WatchSettings:
    float_low_ngn: int
    treasury_low_usdc: Decimal


class TreasuryWatch:
    def __init__(self, settings: WatchSettings, alerts: OperatorAlerts) -> None:
        self.settings = settings
        self.alerts = alerts

    def check(self, report: dict[str, Any]) -> None:
        held = report["held"]
        flutterwave = held["flutterwave_ngn"]
        usdc = report["treasury_usdc"]
        coverage = report["coverage_ngn"]

        if flutterwave is not None:
            self._alarm(
                "flutterwave", flutterwave < self.settings.float_low_ngn,
                f"Flutterwave balance is ₦{flutterwave:,}, under "
                f"₦{self.settings.float_low_ngn:,}. Top it up: bills and bank "
                "withdrawals stop when it cannot cover them.",
                f"Flutterwave balance is back to ₦{flutterwave:,}.",
            )
        if usdc is not None:
            self._alarm(
                "treasury", usdc < self.settings.treasury_low_usdc,
                f"Treasury holds {usdc:,.2f} USDC, under "
                f"{self.settings.treasury_low_usdc:,} USDC. Crypto withdrawals and "
                "vault funding are paid from it.",
                f"Treasury is back to {usdc:,.2f} USDC.",
            )
        # Coverage only means something when both sides were read.
        if flutterwave is not None and usdc is not None:
            self._alarm(
                "coverage", coverage < 0,
                f"Coverage is -₦{-coverage:,}: Stark holds less than it owes users "
                f"(₦{report['owed_to_users_ngn']:,}).",
                f"Coverage is back to ₦{coverage:,}.",
            )

    def _alarm(self, kind: str, low: bool, raise_text: str, clear_text: str) -> None:
        if low:
            if self.alerts.raise_alarm(kind, raise_text):
                log.warning("operator alert raised: %s", raise_text)
        elif self.alerts.clear(kind, clear_text):
            log.info("operator alert cleared: %s", clear_text)
