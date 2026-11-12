"""The off switch: a paused account pays nothing, from any door, until resumed.

Drives the real app on the real database (`support.ApiHarness`), so it needs
`DATABASE_URL` like the other store tests.
"""

from __future__ import annotations

import unittest

from app.modules.agent import policy
from app.modules.telegram import telegram
from tests import support as test_support


class ControlsTest(unittest.TestCase):
    def setUp(self):
        self.account = test_support.TempAccount(balance_ngn=50_000)
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.addCleanup(self.api.restart)
        self.client = self.api.client
        self.bill = self.client.post("/v1/bills", json={
            "kind": "airtime", "provider": "MTN", "reference": "08030000002",
            "label": "Test line",
        }).json()

    def test_a_new_account_is_not_paused(self):
        self.assertEqual(self.client.get("/v1/controls").json(),
                         {"paused": False, "paused_at": None})
        self.assertFalse(self.client.get("/v1/state").json()["paused"])

    def test_a_paused_account_refuses_payments_and_charges_nothing(self):
        paused = self.client.post("/v1/controls/pause").json()
        self.assertTrue(paused["paused"])
        self.assertTrue(self.client.get("/v1/state").json()["paused"])

        response = self.client.post("/v1/payments",
                                    json={"bill_id": self.bill["id"], "amount_ngn": 500})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()["code"], policy.PAUSED)
        self.assertEqual(self.account.store.wallet()["balance_ngn"], 50_000)
        self.assertEqual(self.client.get("/v1/activity").json(), [])

    def test_pausing_twice_keeps_the_first_time(self):
        first = self.client.post("/v1/controls/pause").json()["paused_at"]
        second = self.client.post("/v1/controls/pause").json()["paused_at"]
        self.assertEqual(first, second)

    def test_a_pause_survives_a_restart_and_resume_clears_it(self):
        self.client.post("/v1/controls/pause")
        self.api.restart()
        self.assertTrue(self.client.get("/v1/controls").json()["paused"])
        self.assertFalse(self.client.post("/v1/controls/resume").json()["paused"])
        self.api.restart()
        self.assertFalse(self.client.get("/v1/controls").json()["paused"])

    def test_the_agent_says_it_is_paused_instead_of_paying(self):
        self.client.post("/v1/controls/pause")
        agent = self.api.state().agent
        reply = agent.respond("pay 500 for my line")
        self.assertEqual(reply.code, policy.PAUSED)
        self.assertIsNone(reply.receipt_id)
        self.assertEqual(self.account.store.wallet()["balance_ngn"], 50_000)

    def test_a_linked_chat_can_pause_but_only_the_app_resumes(self):
        # A chat linked with a leaked code could otherwise switch payments back
        # on right after the owner paused them.
        module = self.api.module
        adapter = module.telegram.adapter
        code = module.identities.issue_code(self.account.id)
        chat = f"9{self.account.id[-8:]}"
        module.identities.consume_code(code, telegram.CHANNEL, chat, "Tunde")
        self.addCleanup(module.identities.unlink, telegram.CHANNEL, chat)

        self.assertIn("Paused", adapter._command("/pause", chat, None))
        self.assertTrue(self.client.get("/v1/controls").json()["paused"])
        self.assertEqual(adapter._command("/resume", chat, None), telegram.RESUME_IN_APP)
        self.assertTrue(self.client.get("/v1/controls").json()["paused"])
        self.assertFalse(self.client.post("/v1/controls/resume").json()["paused"])

    def test_an_unlinked_chat_cannot_pause_anyone(self):
        adapter = self.api.module.telegram.adapter
        self.assertEqual(adapter._command("/pause", "1", None), telegram.NOT_LINKED_REPLY)
        self.assertFalse(self.client.get("/v1/controls").json()["paused"])


if __name__ == "__main__":
    unittest.main()
