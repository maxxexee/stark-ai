"""A bill saved from a chat is payable at once: there is no confirmation step.

Drives the real app on the real database (`support.ApiHarness`), like the other
store tests, so it needs `DATABASE_URL`.
"""

from __future__ import annotations

import unittest

from app.modules.agent.account_toolbox import AccountToolbox
from app.modules.bill.dtos.create_bill_dto import CreateBillDto
from tests import support as test_support


class AgentSavedBillTest(unittest.TestCase):
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

    def test_a_bill_the_agent_saved_is_payable_at_once(self):
        self.assertNotIn("needs_confirmation", self.bill)
        self.assertIn("08031112222", self.api.state().limits.allowed_meters)
        listed = self.client.get(f"/v1/bills/{self.bill['id']}").json()
        self.assertNotIn("needs_confirmation", listed)

        paid = self.client.post("/v1/payments", json={
            "bill_id": self.bill["id"], "amount_ngn": 500})
        self.assertNotEqual(paid.json().get("code"), "bill_unconfirmed", paid.text)

    def test_nothing_holds_it_back_after_a_restart(self):
        self.api.restart()
        self.assertIn("08031112222", self.api.state().limits.allowed_meters)

    def test_a_bill_the_owner_adds_is_payable_too(self):
        added = self.client.post("/v1/bills", json={
            "kind": "airtime", "provider": "MTN", "reference": "08039998888"}).json()
        self.assertNotIn("needs_confirmation", added)
        self.assertIn("08039998888", self.api.state().limits.allowed_meters)
