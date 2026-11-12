"""Tell the operator, on Telegram, when the money needs a hand.

Runs as the money loop's last step, on the report `TreasuryService.report()` just
built. It sends to the bot owner's linked Telegram chats (`STARK_TG_OWNER_EMAIL`):

- **Flutterwave low**: the NGN balance is under `STARK_FLOAT_LOW_NGN`. Bills and
  bank withdrawals are refused once it cannot cover them.
- **Treasury low**: the treasury holds less USDC than `STARK_TREASURY_LOW_USDC`.
  Crypto withdrawals are paid from it.
- **Coverage negative**: Stark holds less than it owes its users.
- **Daily summary**: both balances and coverage, once a day at
  `STARK_SUMMARY_HOUR` (Lagos time).

An alarm is sent when it starts, repeated every six hours while it lasts, and
cleared with one "back to normal" line. A balance that could not be read raises
nothing: unknown is not low. The state is in memory, so a restart can repeat an
alarm or the day's summary, never lose a payment.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

log = logging.getLogger("stark.treasury")

LAGOS = timezone(timedelta(hours=1))
REPEAT_SECONDS = 6 * 3600


@dataclass(frozen=True)
class WatchSettings:
    float_low_ngn: int
    treasury_low_usdc: Decimal
    summary_hour: int


class TreasuryWatch:
    def __init__(self, settings: WatchSettings, say: Callable[[str], int],
                 now: Callable[[], float] = time.time) -> None:
        self.settings = settings
        self.say = say
        self.now = now
        self._raised: dict[str, float] = {}  # alarm → when it was last sent
        self._summary_on: Optional[str] = None

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
                f"{self.settings.treasury_low_usdc:,} USDC. Crypto withdrawals are "
                "paid from it.",
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
        self._summary(report)

    def _alarm(self, name: str, low: bool, raise_text: str, clear_text: str) -> None:
        last = self._raised.get(name)
        if not low:
            if last is not None:
                del self._raised[name]
                self.say(clear_text)
            return
        if last is not None and self.now() - last < REPEAT_SECONDS:
            return
        log.warning(raise_text)
        self._raised[name] = self.now()
        self.say(raise_text)

    def _summary(self, report: dict[str, Any]) -> None:
        local = datetime.fromtimestamp(self.now(), LAGOS)
        today = local.date().isoformat()
        if local.hour != self.settings.summary_hour or self._summary_on == today:
            return
        self._summary_on = today
        self.say(summary_text(report))


def summary_text(report: dict[str, Any]) -> str:
    held = report["held"]

    def naira(value: Optional[int]) -> str:
        return "unreadable" if value is None else f"₦{value:,}"

    usdc = report["treasury_usdc"]
    lines = [
        "Stark money, today",
        f"Flutterwave: {naira(held['flutterwave_ngn'])}",
        f"Pending purchases: {naira(held['pending_purchases_ngn'])}",
        "Treasury: " + ("unreadable" if usdc is None else
                        f"{usdc:,.2f} USDC ({naira(held['treasury_usdc_as_ngn'])})"),
        f"Owed to users: {naira(report['owed_to_users_ngn'])}",
        f"Coverage: {naira(report['coverage_ngn'])}",
    ]
    if report["unsettled_vault_ops"]:
        lines.append(f"Vault ops not settled: {report['unsettled_vault_ops']}")
    return "\n".join(lines)
