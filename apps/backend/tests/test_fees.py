"""Stark's service fee: charged on top of a bill, held and refunded with it, and set
on the admin page rather than in the environment."""

from __future__ import annotations

import unittest

from app.common.api_error import ApiError
from app.modules.settings.settings_service import SettingsService
from tests import support as test_support
from tests.support import FakeBills


class FeeOnAPaymentTest(unittest.TestCase):
    def setUp(self):
        self.account = test_support.TempAccount(balance_ngn=20_000)
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account, fees={"electricity": 100})
        self.addCleanup(self.api.restart)
        self.client = self.api.client
        self.vendor = FakeBills("successful")
        self.api.sell_with(self.vendor)
        self.bill = self.client.post("/v1/bills", json={
            "kind": "electricity", "provider": "Eko Electric",
            "reference": "0101170026583", "label": "Home",
        }).json()

    def pay(self, amount: int):
        return self.client.post("/v1/payments",
                                json={"bill_id": self.bill["id"], "amount_ngn": amount})

    def test_the_fee_is_charged_on_top_and_recorded(self):
        receipt = self.pay(5_000).json()
        self.assertEqual((receipt["amount_ngn"], receipt["fee_ngn"]), (5_000, 100))
        self.assertEqual(self.account.store.wallet(),
                         {"balance_ngn": 14_900, "spent_ngn": 5_100})

    def test_a_failed_bill_gives_the_fee_back_too(self):
        self.vendor.outcome = "failed"
        self.pay(5_000)
        self.assertEqual(self.account.store.wallet(), {"balance_ngn": 20_000, "spent_ngn": 0})

    def test_the_fee_counts_toward_the_per_payment_cap(self):
        cap = self.api.state().limits.per_payment_cap_ngn
        refused = self.pay(cap)
        self.assertEqual(refused.json()["code"], "over_per_payment_cap")

    def test_a_bill_shows_the_fee_its_payment_would_carry(self):
        listed = self.client.get("/v1/bills").json()
        self.assertEqual({b["id"]: b["fee_ngn"] for b in listed}[self.bill["id"]], 100)
        self.assertEqual(self.client.get(f"/v1/bills/{self.bill['id']}").json()["fee_ngn"], 100)


class FakeDb:
    def __init__(self):
        self.rows: dict[str, int] = {}

    def query(self, sql, params=None):
        if sql.startswith("INSERT"):
            self.rows[params[0]] = params[1]
            return []
        return [{"key": key, "value": value} for key, value in self.rows.items()]


class SettingsTest(unittest.TestCase):
    def test_defaults_until_the_owner_changes_one(self):
        settings = SettingsService(FakeDb())
        self.assertEqual(settings.fee_for("electricity"), 100)
        settings.set_fees({"electricity": 150})
        self.assertEqual(settings.fees(),
                         {"electricity": 150, "tv": 100, "airtime": 0, "data": 0})

    def test_an_out_of_range_or_unknown_fee_is_refused_and_nothing_is_saved(self):
        db = FakeDb()
        settings = SettingsService(db)
        for change in ({"electricity": -1}, {"electricity": 5_001}, {"water": 10}):
            with self.subTest(change=change), self.assertRaises(ApiError):
                settings.set_fees(change)
        self.assertEqual(db.rows, {})


if __name__ == "__main__":
    unittest.main()
