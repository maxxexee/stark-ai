"""Pending bills settle in the background, without the user retrying.

The money loop runs `BillPaymentService.settle_pending` across every account. These
tests share the real database with other accounts, so the scan is narrowed to the
test account: a fake Flutterwave must never answer for somebody else's purchase.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.common.clock import Clock
from tests import support as test_support
from tests.support import FakeBills


class PendingCase(unittest.TestCase):
    """A ₦20,000 account, one electricity bill, and a fake Flutterwave."""

    def setUp(self):
        self.account = test_support.TempAccount(balance_ngn=20_000)
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.addCleanup(self.api.restart)
        # Settlement is about the vendor's answer, not the vault: with a vault chain
        # in the environment (dev secrets name a testnet one), every payment would
        # first need a live, funded testnet vault and fail with 502 without one.
        self.api.module.bill_payments.payments.vaults = None
        self.client = self.api.client
        self.vendor = FakeBills("pending")
        self.api.sell_with(self.vendor)
        self.bill = self.client.post("/v1/bills", json={
            "kind": "electricity", "provider": "Ikeja Electric",
            "reference": "0101170026583", "label": "Home meter",
        }).json()

    def pay(self) -> dict:
        response = self.client.post("/v1/payments",
                                    json={"bill_id": self.bill["id"], "amount_ngn": 5_000})
        self.assertEqual(response.json()["status"], "pending")
        return response.json()

    def settle(self, receipt: dict, *, minutes_old: int = 2) -> None:
        self.account.db.query("UPDATE receipts SET created_at = $2 WHERE id = $1",
                              [receipt["id"], Clock.ago(minutes=minutes_old)])
        store = self.api.module.bill_payments.payments.store
        every_account = store.pending_purchases
        with mock.patch.object(store, "pending_purchases", lambda before: [
                row for row in every_account(before) if row["user_id"] == self.account.id]):
            self.api.module.bill_payments.settle_pending()

    def wallet(self) -> dict:
        return self.account.store.wallet()


class SettlementTest(PendingCase):
    def test_a_delivery_settles_without_a_retry(self):
        receipt = self.pay()
        self.assertEqual(self.wallet(), {"balance_ngn": 15_000, "spent_ngn": 0})

        self.vendor.outcome = "successful"
        self.settle(receipt)

        settled = self.account.store.get(receipt["id"])
        self.assertEqual(settled["status"], "delivered")
        self.assertTrue(settled["token"])
        self.assertEqual(self.wallet(), {"balance_ngn": 15_000, "spent_ngn": 5_000})
        [bill] = self.client.get("/v1/bills").json()
        self.assertEqual(bill["last_amount_ngn"], 5_000)
        self.assertEqual(len(self.vendor.paid), 1)

    def test_a_failure_gives_the_money_back(self):
        receipt = self.pay()
        self.vendor.outcome = "failed"
        self.settle(receipt)
        self.assertEqual(self.account.store.get(receipt["id"])["status"], "failed")
        self.assertEqual(self.wallet(), {"balance_ngn": 20_000, "spent_ngn": 0})

    def test_still_pending_stays_held(self):
        receipt = self.pay()
        self.settle(receipt)
        self.assertEqual(self.account.store.get(receipt["id"])["status"], "pending")
        self.assertEqual(self.wallet(), {"balance_ngn": 15_000, "spent_ngn": 0})

    def test_a_fresh_purchase_is_left_for_its_own_answer(self):
        receipt = self.pay()
        self.vendor.read.clear()
        self.settle(receipt, minutes_old=0)
        self.assertEqual(self.vendor.read, [])

    def test_a_retry_after_the_background_settled_it_charges_once(self):
        receipt = self.pay()
        self.vendor.outcome = "successful"
        self.settle(receipt)
        again = self.client.post("/v1/payments",
                                 json={"bill_id": self.bill["id"], "amount_ngn": 5_000})
        self.assertNotEqual(again.json()["id"], receipt["id"])  # a new, separate purchase
        self.assertEqual(self.wallet(), {"balance_ngn": 10_000, "spent_ngn": 10_000})


class LostAnswerTest(PendingCase):
    """The order call timed out, so the receipt has no `tx_ref` to re-read.

    It may still have been placed. Before anything is given back, Flutterwave is
    asked by our own reference; only a purchase it has no record of is written off.
    """

    def setUp(self):
        super().setUp()
        self.vendor.outcome = "successful"
        self.vendor.lose_answer = True

    def test_a_purchase_that_went_through_is_delivered_not_refunded(self):
        receipt = self.pay()
        self.settle(receipt, minutes_old=45)  # well past the write-off window
        settled = self.account.store.get(receipt["id"])
        self.assertEqual(settled["status"], "delivered")
        self.assertEqual(settled["vendor_ref"], receipt["request_id"])
        self.assertEqual(self.wallet(), {"balance_ngn": 15_000, "spent_ngn": 5_000})
        self.assertIn(receipt["request_id"], self.vendor.read)

    def test_one_flutterwave_never_got_is_written_off_after_the_window(self):
        self.vendor.refuse = self.vendor.error(0, "Could not reach Flutterwave: timed out")
        receipt = self.pay()
        self.settle(receipt, minutes_old=5)
        self.assertEqual(self.account.store.get(receipt["id"])["status"], "pending")
        self.settle(receipt, minutes_old=45)
        self.assertEqual(self.account.store.get(receipt["id"])["status"], "failed")
        self.assertEqual(self.wallet(), {"balance_ngn": 20_000, "spent_ngn": 0})

    def test_flutterwave_unreachable_is_not_a_reason_to_refund(self):
        receipt = self.pay()
        self.vendor.refuse_reads = self.vendor.error(503, "Service unavailable")
        self.settle(receipt, minutes_old=45)
        self.assertEqual(self.account.store.get(receipt["id"])["status"], "pending")
        self.assertEqual(self.wallet(), {"balance_ngn": 15_000, "spent_ngn": 0})


if __name__ == "__main__":
    unittest.main()
