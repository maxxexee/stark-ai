"""The monthly cap is this month's, and holds even when payments race.

Default caps: ₦30,000 a month, ₦10,000 a payment. Fees are off in the harness, so
a payment's total is its amount. The vault is left out (see `test_settlement`).
"""

from __future__ import annotations

import threading
import time
import unittest

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.database import neon
from tests import support as test_support
from tests.support import FakeBills


class CapCase(unittest.TestCase):
    def setUp(self):
        self.account = test_support.TempAccount(balance_ngn=50_000)
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.addCleanup(self.api.restart)
        self.api.module.bill_payments.payments.vaults = None
        self.client = self.api.client
        self.vendor = FakeBills("successful")
        self.api.sell_with(self.vendor)
        self.meter = self.add_bill("0101170026583", "Home meter")

    def add_bill(self, reference: str, label: str) -> dict:
        return self.client.post("/v1/bills", json={
            "kind": "electricity", "provider": "Ikeja Electric",
            "reference": reference, "label": label,
        }).json()

    def pay(self, bill: dict, amount: int):
        return self.client.post("/v1/payments",
                                json={"bill_id": bill["id"], "amount_ngn": amount})

    def spent_in(self, period: str, spent_ngn: int) -> None:
        self.account.db.query(
            "UPDATE wallets SET spent_ngn = $2, spent_period = $3 WHERE user_id = $1",
            [self.account.id, spent_ngn, period])


class MonthlyCapTest(CapCase):
    def test_last_months_spend_does_not_count(self):
        self.spent_in("2026-01", 29_000)
        self.assertEqual(self.account.store.wallet()["spent_ngn"], 0)
        wallet = self.client.get("/v1/wallet").json()
        self.assertEqual((wallet["spent_ngn"], wallet["remaining_cap_ngn"]), (0, 30_000))

        response = self.pay(self.meter, 5_000)
        self.assertEqual(response.status_code, 201, response.json())
        # The first delivery of the month starts the count again.
        self.assertEqual(self.account.store.wallet(), {"balance_ngn": 45_000,
                                                       "spent_ngn": 5_000})
        self.assertEqual(self.client.get("/v1/state").json()["spent_ngn"], 5_000)

    def test_this_months_spend_still_counts(self):
        self.account.store.set_wallet(50_000, 28_000)
        response = self.pay(self.meter, 5_000)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "over_cap")
        self.assertEqual(response.json()["detail"]["remaining_ngn"], 2_000)

    def test_a_purchase_in_flight_counts_against_the_cap(self):
        self.account.store.set_wallet(50_000, 22_000)
        self.vendor.outcome = "pending"
        held = self.pay(self.meter, 5_000)
        self.assertEqual(held.json()["status"], "pending")

        other = self.add_bill("0101170026584", "Shop meter")
        response = self.pay(other, 5_000)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "over_cap")
        self.assertEqual(response.json()["detail"],
                         {"cap_ngn": 30_000, "spent_ngn": 22_000, "remaining_ngn": 3_000})

        # A retry of the held one settles it rather than counting it twice.
        self.vendor.outcome = "successful"
        retried = self.pay(self.meter, 5_000)
        self.assertEqual(retried.json()["id"], held.json()["id"])
        self.assertEqual(retried.json()["status"], "delivered")
        self.assertEqual(self.account.store.wallet()["spent_ngn"], 27_000)

    def test_old_lifetime_totals_are_rebuilt_from_this_months_receipts(self):
        backfill = next(statement for statement in neon._statements(neon.SCHEMA)
                        if statement.lstrip().startswith("UPDATE wallets"))
        self.account.db.query(
            "UPDATE wallets SET spent_ngn = 99000, spent_period = NULL WHERE user_id = $1",
            [self.account.id])
        this_month = Clock.month_start()
        for request_id, created_at in (("now", this_month), ("old", "2026-01-15T10:00:00Z")):
            self.account.store.create({
                "id": f"rcpt_{request_id}", "request_id": request_id,
                "bill_id": self.meter["id"], "bill_label": "Home meter", "meter": None,
                "amount_ngn": 4_000, "fee_ngn": 100, "units": None, "token": None,
                "tx_hash": None, "status": "delivered", "entry_type": "bill",
                "source": None, "vendor": "flutterwave", "vendor_code": "200",
                "vendor_message": None, "created_at": created_at,
            })
        self.account.db.query(backfill)
        self.assertEqual(self.account.store.wallet()["spent_ngn"], 4_100)


class ConcurrentPaymentTest(CapCase):
    def test_racing_payments_cannot_both_pass_the_cap(self):
        """Two doors (say REST and Telegram) pay at once with room for one."""
        self.account.store.set_wallet(50_000, 22_000)
        other = self.add_bill("0101170026584", "Shop meter")
        place = self.vendor.pay_bill

        def slow_vendor(**order):
            time.sleep(0.5)  # wide enough for the other payment to read the cap
            return place(**order)

        self.vendor.pay_bill = slow_vendor
        outcomes: list[str] = []

        def pay(bill: dict) -> None:
            try:
                receipt = self.api.module.bill_payments.pay(self.account.id, bill["id"],
                                                            5_000)
                outcomes.append(receipt["status"])
            except ApiError as err:
                outcomes.append(err.code)

        threads = [threading.Thread(target=pay, args=(bill,)) for bill in (self.meter, other)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(outcomes), ["delivered", "over_cap"])
        self.assertEqual(self.account.store.wallet(), {"balance_ngn": 45_000,
                                                       "spent_ngn": 27_000})


if __name__ == "__main__":
    unittest.main()
