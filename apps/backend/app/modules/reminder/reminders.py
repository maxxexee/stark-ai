"""When a bill is supposed to be paid — and the one line Stark says about it.

A bill that knows its own renewal date is the difference between "Stark, what
do I owe?" and Stark telling you first. `renews_on` is an additive field on a
bill (docs/API.md): a calendar date, YYYY-MM-DD, unset for meters and lines
that do not renew on a schedule.

Everything here is pure: dates in, dicts out, no clock unless you hand it one,
no store, no network — so the rules are testable and the server stays a stub.
The notify log is the one piece of state, and it is deliberately in-memory:
this demo sends at most one reminder per bill per renewal date, and losing
that on a restart costs a repeat message, never a payment.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from typing import Any, Iterable

# The reminder window: a bill inside this many days is worth a nudge. A week
# matches how people actually pay subscriptions — soon enough to act on, far
# enough not to nag.
WINDOW_DAYS = 7


def parse_date(value: Any) -> date | None:
    """A bill's `renews_on`: YYYY-MM-DD, or any ISO string that starts with one."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _today(today: date | None) -> date:
    return today or datetime.now(timezone.utc).date()


def _price(bill: dict) -> int | None:
    """What the renewal costs: the plan's own price, else the last amount paid."""
    return bill.get("plan_price_ngn") or bill.get("last_amount_ngn") or None


def due_soon(bills: Iterable[dict], *, today: date | None = None,
             window_days: int = WINDOW_DAYS) -> list[dict]:
    """Bills with a renewal inside the window, soonest first.

    Overdue inside the window still counts — "was due 2 days ago" is the
    loudest reminder there is. Outside the window either way the bill goes
    quiet: a renewal a month away is not due yet, and a date months in the
    past is stale data to fix rather than this week's problem.
    """
    now = _today(today)
    items: list[dict] = []
    for bill in bills:
        on = parse_date(bill.get("renews_on"))
        if on is None:
            continue
        days = (on - now).days
        if abs(days) > window_days:
            continue
        items.append({
            "id": bill.get("id"),
            "kind": bill.get("kind"),
            "provider": bill.get("provider"),
            "label": bill.get("label"),
            "renews_on": on.isoformat(),
            "days_until": days,
            "price_ngn": _price(bill),
        })
    items.sort(key=lambda item: (item["days_until"], str(item["id"])))
    return items


def severity(days_until: int) -> str:
    """alert on or before the day, warn within three days, info beyond."""
    if days_until <= 0:
        return "alert"
    if days_until <= 3:
        return "warn"
    return "info"


def line(item: dict) -> str:
    """One spoken sentence — what a reminder push and the agent say out loud."""
    days = int(item["days_until"])
    who = f"Your {item['provider']}"
    price = f", ₦{item['price_ngn']:,}" if item.get("price_ngn") else ""
    if days < 0:
        n = -days
        return f"{who} was due {n} day{'s' if n != 1 else ''} ago{price}."
    if days == 0:
        return f"{who} is due today{price}."
    if days == 1:
        return f"{who} renews tomorrow{price}."
    return f"{who} renews in {days} days{price}."


def summary(item: dict) -> str:
    """The same fact as finished UI copy: no possessive, read at a glance."""
    days = int(item["days_until"])
    price = f", ₦{item['price_ngn']:,}" if item.get("price_ngn") else ""
    when = ("today" if days == 0 else "tomorrow" if days == 1
            else f"in {days} days" if days > 0 else f"{-days} days ago")
    verb = "renews" if days >= 0 else "was due"
    return f"{item['provider']} {verb} {when}{price}."


def push_text(item: dict) -> str:
    """The Telegram nudge: the fact, then how to act on it in one word."""
    return f"{line(item)} Reply to pay it."


class NotifyLog:
    """One reminder per bill per renewal date.

    In-memory by design (module docstring): the claim is best-effort, so a
    restart may repeat a nudge but a nudge is never sent twice in one run.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sent: set[str] = set()

    @staticmethod
    def key(item: dict) -> str:
        return f"{item['id']}@{item['renews_on']}"

    def claim(self, item: dict) -> bool:
        """True the first time this renewal is claimed — meaning: push it now."""
        key = self.key(item)
        with self._lock:
            if key in self._sent:
                return False
            self._sent.add(key)
            return True

    def clear(self) -> None:
        with self._lock:
            self._sent.clear()


def due_for_push(bills: Iterable[dict], *, log: NotifyLog,
                 today: date | None = None,
                 window_days: int = WINDOW_DAYS) -> list[dict]:
    """What has not been said out loud yet — the scheduler's queue.

    Claiming happens here, before any send: a push that fails costs the nudge
    for this run, never a double message.
    """
    return [item for item in due_soon(bills, today=today, window_days=window_days)
            if log.claim(item)]
