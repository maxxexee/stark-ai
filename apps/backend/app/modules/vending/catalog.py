"""Which Flutterwave biller and item a bill actually is.

Read live from `GET /v3/bill-categories?country=NG`: one row per (biller, item),
with the item's price, refreshed hourly. The app points the shared catalogue at
Flutterwave at boot (`CATALOG.use`); until then, or with Flutterwave unconfigured, it
is empty and nothing can be sold.

Rows group by `biller_code` (`BIL104` is MTN data) and each item is either:

- **amount** (airtime `AT…`, electricity `UB…`, price `0`): the amount is the product.
- **plan** (data `MD…`, TV `CB…`, priced): the item is the product and the price is
  the item's. A bill therefore carries a `plan` (the item code) and the amount paid
  must equal that price — otherwise Flutterwave charges something nobody asked for.

Which billers Stark sells, by name, since that is what the catalogue is keyed on:

| Kind | Biller rows |
|---|---|
| airtime | `is_airtime: true` — MTN, Airtel, Glo, 9mobile |
| data | `… DATA BUNDLE` |
| tv | DSTV, GOTV, STARTIMES |
| electricity | Ikeja's prepaid item (`IKEDC  PREPAID`) |
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

AMOUNT = "amount"
PLAN = "plan"
REFRESH_SECONDS = 3600

# What a bill's provider is called, against the first word of Flutterwave's biller name.
NETWORKS = ("mtn", "airtel", "glo", "9mobile", "dstv", "gotv", "startimes")
ALIASES = {"etisalat": "9mobile", "dstvcompact": "dstv"}


@dataclass(frozen=True)
class Product:
    kind: str
    biller_code: str
    name: str
    mode: str  # AMOUNT | PLAN
    item_code: str | None = None  # the item, for an amount product

    @property
    def needs_plan(self) -> bool:
        return self.mode == PLAN


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_ngn: int


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


class Catalog:
    def __init__(self, load: Callable[[], list[dict[str, Any]]] = list):
        self._load = load
        self._rows: list[dict[str, Any]] | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def use(self, load: Callable[[], list[dict[str, Any]]]) -> None:
        """Read the catalogue from `load` (the live API) from now on."""
        with self._lock:
            self._load = load
            self._rows = None

    def rows(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._rows is not None and time.monotonic() - self._loaded_at < REFRESH_SECONDS:
                return self._rows
            load = self._load
        try:
            rows = load()
        except Exception:
            if self._rows is not None:
                return self._rows  # a stale catalogue beats none while Flutterwave is down
            raise
        with self._lock:
            self._rows, self._loaded_at = rows, time.monotonic()
        return rows

    # --- products ------------------------------------------------------------

    def products(self, kind: str) -> list[Product]:
        """Every biller Stark sells for `kind`, one per biller code."""
        by_biller: dict[str, list[dict[str, Any]]] = {}
        for row in self.rows():
            if _kind_of(row) == kind:
                by_biller.setdefault(row["biller_code"], []).append(row)
        products = []
        for biller_code, items in by_biller.items():
            name = _network(items[0]) or items[0]["name"]
            if kind in ("data", "tv"):
                products.append(Product(kind, biller_code, name.upper(), PLAN))
            else:
                products.append(Product(kind, biller_code, name.upper(), AMOUNT,
                                        _amount_item(biller_code, items)))
        return products

    def product(self, kind: str, provider: str) -> Product | None:
        """The biller for a bill kind and provider, or `None`.

        `provider` is what the bill was saved with: a name (`MTN`, `DStv`,
        `Ikeja Electric`) or a biller code (`BIL104`).
        """
        wanted = ALIASES.get(slug(provider), slug(provider))
        if not wanted:
            return None
        for product in self.products(kind):
            network = slug(product.name)
            if wanted in (slug(product.biller_code), network, f"{network}data"):
                return product
            if kind == "electricity" and wanted.startswith("ikeja"):
                return product
        return None

    # --- plans ---------------------------------------------------------------

    def plans(self, product: Product) -> list[Plan]:
        if not product.needs_plan:
            return []
        seen: dict[str, Plan] = {}
        for row in self.rows():
            code = row["item_code"]
            if row["biller_code"] == product.biller_code and code not in seen:
                seen[code] = Plan(code, row["biller_name"].strip(), int(row["amount"]))
        return [plan for plan in seen.values() if plan.price_ngn > 0]

    def plan(self, product: Product, code: str) -> Plan | None:
        return next((p for p in self.plans(product) if p.code == code), None)


def _network(row: dict[str, Any]) -> str | None:
    first = slug(row["name"].split()[0]) if row["name"].split() else ""
    return first if first in NETWORKS else None


def _kind_of(row: dict[str, Any]) -> str | None:
    name = row["name"].upper()
    if row["is_airtime"]:
        return "airtime" if _network(row) else None
    if name.endswith("DATA BUNDLE") and _network(row):
        return "data"
    if _network(row) in ("dstv", "gotv", "startimes") and int(row["amount"]) > 0:
        return "tv"
    if "IKEJA" in name and "PREPAID" in row["biller_name"].upper():
        return "electricity"
    return None


def _amount_item(biller_code: str, items: list[dict[str, Any]]) -> str:
    """The item to buy an amount on. Glo lists two airtime items; the one numbered like
    its biller (`BIL102` → `AT102`) is the one Flutterwave's docs test with."""
    matching = f"AT{biller_code[3:]}"
    codes = [row["item_code"] for row in items]
    return matching if matching in codes else codes[0]


# One shared catalogue, pointed at Flutterwave by the app module.
CATALOG = Catalog()
