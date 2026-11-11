"""The artboard's account: three bills, ₦64,200, ₦23,000 spent and six receipts.

Only `POST /v1/_stub/reset` uses it, so smoke runs and demos start from the same
numbers. Real accounts are never seeded: they open empty.

Meter, phone and smartcard numbers are fake but shaped like the real thing, and
every timestamp moves with the clock, so a demo always has one bill inside the
reminder window.
"""

from __future__ import annotations

import copy
from typing import Any

from app.common.clock import Clock
from app.modules.vending import catalog


class StubSeed:
    BALANCE_NGN = 64_200
    # "Spent this month ₦23,000 of ₦30,000": three electricity top-ups (5,000 +
    # 10,000 + 8,000). The airtime entry is an automatic top-up and the ₦20,000
    # entry is money in, so neither counts as bill spend.
    SPENT_NGN = 23_000
    SAMPLE_TOKEN = "4821 0937 5512 8846 3019"

    @staticmethod
    def bills() -> dict[str, dict[str, Any]]:
        """A fresh copy every call, so one reset never edits the next one's seed."""
        seed = [
            {
                "id": "bill_home_meter",
                "kind": "electricity",
                "provider": "Ikeja Electric",
                "label": "Home",
                "reference": "04512345678",
                "last_amount_ngn": 5_000,
                "last_units": 23.9,
                "last_paid_at": Clock.ago(0),
            },
            {
                "id": "bill_dstv",
                "kind": "tv",
                "provider": "DStv",
                "label": "Living room TV",
                "reference": "7032119456",
                # The plan is the product: the cheapest DStv bouquet Flutterwave
                # sells, picked below from the live catalogue.
                # Due in three days, not recently paid: the reminder window always
                # has a bill in it (see `reminders.py`).
                "renews_on": Clock.in_days(3),
                "last_amount_ngn": None,
                "last_units": None,
                "last_paid_at": None,
            },
            {
                "id": "bill_airtime",
                "kind": "airtime",
                "provider": "MTN",
                "label": "My line",
                "reference": "08031234567",
                "last_amount_ngn": 1_000,
                "last_units": None,
                "last_paid_at": Clock.ago(0, hours=6),
            },
        ]
        bills = {bill["id"]: copy.deepcopy(bill) for bill in seed}
        # Bills bought by plan carry the vendor's plan and price, so nobody guesses
        # them. Without a catalogue (Flutterwave unset) the TV bill has no plan yet.
        for bill in bills.values():
            product = catalog.CATALOG.product(bill["kind"], bill["provider"])
            if product is not None and product.needs_plan:
                plans = catalog.CATALOG.plans(product)
                if plans:
                    cheapest = min(plans, key=lambda plan: plan.price_ngn)
                    bill["plan"] = cheapest.code
                    bill["plan_price_ngn"] = cheapest.price_ngn
        return bills

    @staticmethod
    def receipts(bills: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """The six activity entries the artboards show.

        The three delivered electricity top-ups total ₦23,000. The ₦1,000 airtime
        entry is an automatic top-up and the ₦20,000 entry is money in, so neither
        is bill spend; the ₦15,000 attempt was declined by the per-payment cap and
        was never charged.
        """
        meter = bills["bill_home_meter"]["reference"]
        line = bills["bill_airtime"]["reference"]

        def entry(**fields: Any) -> dict[str, Any]:
            base = {"meter": meter, "units": None, "token": None, "tx_hash": None,
                    "status": "delivered", "entry_type": "bill", "vendor": "seed",
                    "vendor_code": "000", "vendor_message": "seeded",
                    "bill_id": "bill_home_meter", "bill_label": "Home electricity"}
            return {**base, **fields}

        return [
            entry(id="rcpt_0003", request_id="seed-0003", amount_ngn=5_000, units=23.9,
                  token=StubSeed.SAMPLE_TOKEN,
                  tx_hash="8f2c1d4e6a9b0c3f5e7d1a2b4c6d8e0f1a3b5c7d9e0f2a4b6c8d0e1f3a5b7c9d",
                  source="Telegram voice note", created_at=Clock.ago(0)),
            entry(id="rcpt_0004", request_id="seed-0004", amount_ngn=15_000,
                  status="declined", source="Telegram voice note", vendor="policy",
                  vendor_code="over_per_payment_cap",
                  vendor_message="Over your ₦10,000 per-payment limit",
                  created_at=Clock.ago(0, minutes=1)),
            entry(id="rcpt_0002", request_id="seed-0002", bill_id="bill_airtime",
                  bill_label="My line airtime", meter=line, amount_ngn=1_000,
                  entry_type="autotopup", source="Automatic top-up",
                  created_at=Clock.ago(0, hours=6)),
            entry(id="rcpt_0005", request_id="seed-0005", bill_id="wallet",
                  bill_label="Added money", meter=None, amount_ngn=20_000,
                  status="received", entry_type="deposit", source="Bank transfer",
                  created_at=Clock.ago(10)),
            entry(id="rcpt_0006", request_id="seed-0006", amount_ngn=10_000, units=47.8,
                  token="1290 4478 0031 6652 9917", source="Wall phone",
                  created_at=Clock.ago(14)),
            entry(id="rcpt_0001", request_id="seed-0001", amount_ngn=8_000, units=38.3,
                  token="6634 2210 9845 1176 0042", source="Typed on Telegram",
                  created_at=Clock.ago(20)),
        ]

    @staticmethod
    def sync_history(bills: dict[str, dict[str, Any]],
                     history: list[dict[str, Any]]) -> None:
        """Point each bill at its newest delivered payment in the seeded history."""
        newest: dict[str, dict[str, Any]] = {}
        for entry in history:
            if (entry["entry_type"] in ("bill", "autotopup")
                    and entry["status"] == "delivered" and entry["bill_id"] in bills):
                newest.setdefault(entry["bill_id"], entry)
        for bill_id, entry in newest.items():
            bill = bills[bill_id]
            bill["last_amount_ngn"] = entry["amount_ngn"]
            bill["last_units"] = entry["units"]
            bill["last_paid_at"] = entry["created_at"]
