"""Raise an operator alert when the money needs a hand.

Runs as the money loop's last step, on the report `TreasuryService.report()` just
built, and records alarms in `OperatorAlerts`, which the admin page shows:

- **Flutterwave low**: the NGN balance is under the `float_low_ngn` limit. Bills
  and bank withdrawals are refused once it cannot cover them.
- **Treasury low**: the treasury holds less USDC than the `treasury_low_usdc` limit.
  Crypto withdrawals are paid from it.

Both thresholds are operator limits, set on the admin page and read on every check.
- **Coverage negative**: Stark holds less than it owes its users.

An alarm is raised when its condition starts and cleared when it ends; each change
is also logged. A balance that could not be read changes nothing: unknown is not
low, and not recovered either.
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.settings.operator_limits import OperatorLimits
from app.modules.treasury.operator_alerts import OperatorAlerts

log = logging.getLogger("stark.treasury")


class TreasuryWatch:
    def __init__(self, limits: OperatorLimits, alerts: OperatorAlerts) -> None:
        self.limits = limits
        self.alerts = alerts

    def check(self, report: dict[str, Any]) -> None:
        held = report["held"]
        flutterwave = held["flutterwave_ngn"]
        usdc = report["treasury_usdc"]
        coverage = report["coverage_ngn"]

        if flutterwave is not None:
            float_low_ngn = self.limits.get("float_low_ngn")
            self._alarm(
                "flutterwave", flutterwave < float_low_ngn,
                f"Flutterwave balance is ₦{flutterwave:,}, under "
                f"₦{float_low_ngn:,}. Top it up: bills and bank "
                "withdrawals stop when it cannot cover them.",
                f"Flutterwave balance is back to ₦{flutterwave:,}.",
            )
        if usdc is not None:
            treasury_low_usdc = self.limits.get("treasury_low_usdc")
            self._alarm(
                "treasury", usdc < treasury_low_usdc,
                f"Treasury holds {usdc:,.2f} USDC, under "
                f"{treasury_low_usdc:,} USDC. Crypto withdrawals and "
                "vault funding are paid from it.",
                f"Treasury is back to {usdc:,.2f} USDC.",
            )
        # Coverage only means something when every pot it counts was read.
        vaults = report["vaults"]
        vaults_read = vaults is None or not vaults["counted"] or vaults["usdc"] is not None
        if flutterwave is not None and usdc is not None and vaults_read:
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
