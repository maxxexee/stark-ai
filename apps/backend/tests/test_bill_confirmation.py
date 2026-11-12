"""A bill the agent saves is not payable until its owner confirms it in the app.

Drives the real app on the real database (`support.ApiHarness`), like the other
store tests, so it needs `DATABASE_URL`. Covers the whole chain the security
review traced: the agent's allowlist, the app's own payment path, and the
owner-only confirm route that lifts the hold.
"""

from __future__ import annotations

import unittest

from app.modules.agent.account_toolbox import AccountToolbox
from app.modules.bill.dtos.create_bill_dto import CreateBillDto
from tests import support as test_support


class BillConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.account = test_support.TempAccount(balance_ngn=50_000)
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.addCleanup(self.api.restart)
        self.api.sell_with(test_support.FakeBills())
        self.client = self.api.client
        toolbox = AccountToolbox(self.account.id, self.api.module)
        self.bill = toolbox.add_bill(CreateBillDto(
            kind="airtime", provider="MTN", reference="08031112222", label="Said aloud"))

    def test_an_agent_saved_bill_waits_for_the_owner(self):
        self.assertTrue(self.bill["needs_confirmation"])
        self.assertNotIn("08031112222", self.api.state().limits.allowed_meters)
        listed = self.client.get(f"/v1/bills/{self.bill['id']}").json()
        self.assertTrue(listed["needs_confirmation"])

        refused = self.client.post("/v1/payments", json={
            "bill_id": self.bill["id"], "amount_ngn": 500})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["code"], "bill_unconfirmed")

        confirmed = self.client.post(f"/v1/bills/{self.bill['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200)
        self.assertNotIn("needs_confirmation", confirmed.json())
        self.assertIn("08031112222", self.api.state().limits.allowed_meters)

    def test_the_hold_survives_a_restart(self):
        self.api.restart()
        self.assertNotIn("08031112222", self.api.state().limits.allowed_meters)

    def test_a_bill_the_owner_adds_needs_no_confirmation(self):
        added = self.client.post("/v1/bills", json={
            "kind": "airtime", "provider": "MTN", "reference": "08039998888"}).json()
        self.assertNotIn("needs_confirmation", added)
        self.assertIn("08039998888", self.api.state().limits.allowed_meters)

    def test_confirming_an_unknown_bill_is_404(self):
        response = self.client.post("/v1/bills/bill_nope/confirm")
        self.assertEqual(response.status_code, 404)
