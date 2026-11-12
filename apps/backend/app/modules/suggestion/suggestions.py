"""What Stark notices on its own — every line computed, nothing invented.

This replaces the old hand-written suggestion list: one live line and one
hardcoded lie ("Your AC is 78% of your usage this week") that no data ever
supported. Everything here is derived from what the server actually holds —
the meter, the wallet, delivered receipts, telemetry samples and renewal
dates. A signal with no data behind it is simply not returned: an empty list
is honest, a fabricated line is not.

Pure by design: the caller passes state in, dicts come out, and the only
clock is the one you hand it. `build()` is the server's single entry point.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.modules.reminder import reminders

# Thresholds. The point is to stay quiet until something is worth acting on.
LOW_UNITS_DAYS = 5        # beyond this, a meter that still has units is not news
UNITS_ALERT_DAYS = 2
UNITS_WARN_DAYS = 4
CAP_WARN = 0.80           # 80% of the monthly limit is worth a nudge
CAP_ALERT = 0.95
AC_DOMINANT_SHARE = 0.60  # one device over 60% of measured load is an imbalance
LOAD_LOOKBACK_SECONDS = 24 * 3600
BURNDAY_LOOKBACK_DAYS = 14
MAX_ITEMS = 4             # a feed that never ends is not a suggestion list


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def burn_rate(receipts: Iterable[dict], *,
              now: datetime | None = None,
              lookback_days: int = BURNDAY_LOOKBACK_DAYS) -> float | None:
    """Units per day, from delivered electricity top-ups in the lookback window.

    Needs at least two deliveries on different days — one top-up says nothing
    about pace, and same-day top-ups are a top-up day, not a habit. Returns
    None whenever the data cannot honestly support a rate.
    """
    now = now or datetime.now(timezone.utc)
    stamps: list[datetime] = []
    total = 0.0
    for receipt in receipts:
        if receipt.get("status") != "delivered" or not receipt.get("units"):
            continue
        when = _parse_ts(receipt.get("created_at"))
        if when is None or (now - when).days > lookback_days:
            continue
        stamps.append(when)
        total += float(receipt["units"])
    if len(stamps) < 2:
        return None
    span = (max(stamps) - min(stamps)).total_seconds() / 86400.0
    if span < 1.0:
        return None
    rate = total / span
    return rate if rate > 0 else None


def _units_item(units_left: float | None, days_left: float | None,
                rate: float | None) -> dict | None:
    """The meter running down — the burn rate when receipts support one, the
    state's own estimate otherwise (and said to be an estimate)."""
    if units_left is None:
        return None
    if rate:
        runway = units_left / rate
        text = (f"You're using about {rate:.1f} units a day, so "
                f"{units_left:g} left is about {runway:.0f} days.")
        reason = "units_low"
    elif days_left is not None:
        runway = float(days_left)
        text = f"About {units_left:g} units left, roughly {days_left:g} days."
        reason = "units_low_estimate"
    else:
        return None
    if runway > LOW_UNITS_DAYS:
        return None
    level = ("alert" if runway <= UNITS_ALERT_DAYS
             else "warn" if runway <= UNITS_WARN_DAYS else "info")
    return {"id": "sug_units", "text": text, "severity": level, "reason": reason}


def _cap_item(spent_ngn: int | None, cap_ngn: int | None) -> dict | None:
    """The monthly limit nearly used — only once it is actually near."""
    if not cap_ngn or spent_ngn is None or spent_ngn < cap_ngn * CAP_WARN:
        return None
    pct = round(spent_ngn / cap_ngn * 100)
    left = max(cap_ngn - spent_ngn, 0)
    level = "alert" if spent_ngn >= cap_ngn * CAP_ALERT else "warn"
    return {
        "id": "sug_cap",
        "text": f"You've used {pct}% of your ₦{cap_ngn:,} limit. ₦{left:,} is left this month.",
        "severity": level,
        "reason": "cap_near",
    }


def _due_items(due: list[dict]) -> list[dict]:
    """Renewals inside the window (reminders.py), worst first, at most two."""
    return [
        {
            "id": f"sug_due_{item['id']}",
            "text": reminders.summary(item),
            "severity": reminders.severity(item["days_until"]),
            "reason": "bill_due",
        }
        for item in due[:2]
    ]


def _load_item(telemetry: Iterable[dict],
               tariff_ngn_per_kwh: float) -> dict | None:
    """Which device is carrying the load — only when telemetry can prove it.

    One device's samples are 100% of its own usage, which says nothing; the
    imbalance needs at least two devices and one clear dominant draw. Draw is
    each device's *average* watts, not the sum — ten samples are ten readings
    of a habit, not ten air conditioners.
    """
    now = datetime.now(timezone.utc)
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for sample in telemetry:
        when = _parse_ts(sample.get("ts"))
        if when is None or (now - when).total_seconds() > LOAD_LOOKBACK_SECONDS:
            continue
        try:
            watts = float(sample.get("watts"))
        except (TypeError, ValueError):
            continue
        device = str(sample.get("device_id") or "unknown")
        sums[device] = sums.get(device, 0.0) + watts
        counts[device] = counts.get(device, 0) + 1
    if len(sums) < 2:
        return None
    averages = {device: sums[device] / counts[device] for device in sums}
    total = sum(averages.values())
    if total <= 0:
        return None
    top, top_watts = max(averages.items(), key=lambda kv: kv[1])
    share = top_watts / total
    if share < AC_DOMINANT_SHARE:
        return None
    per_day_ngn = top_watts * 24 / 1000 * tariff_ngn_per_kwh
    name = top.replace("_", " ")
    return {
        "id": "sug_load",
        "text": (f"{name} is {share:.0%} of measured usage, "
                 f"about ₦{per_day_ngn:,.0f} a day at your tariff."),
        "severity": "info",
        "reason": "load_imbalance",
    }


_SEVERITY_ORDER = {"alert": 0, "warn": 1, "info": 2}


def build(*, bills: Iterable[dict], units_left: float | None,
          days_left: float | None, spent_ngn: int | None, cap_ngn: int | None,
          telemetry: Iterable[dict], receipts: Iterable[dict],
          tariff_ngn_per_kwh: float,
          today=None) -> list[dict]:
    """The suggestion list, worst news first, capped so the UI stays quiet."""
    due = reminders.due_soon(bills, today=today)
    found = [
        item for item in (
            _units_item(units_left, days_left, burn_rate(receipts)),
            _cap_item(spent_ngn, cap_ngn),
            _load_item(telemetry, tariff_ngn_per_kwh),
            *_due_items(due),
        )
        if item
    ]
    found.sort(key=lambda item: _SEVERITY_ORDER.get(item["severity"], 3))
    return found[:MAX_ITEMS]
