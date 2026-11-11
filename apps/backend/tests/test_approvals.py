"""Over a limit, Stark asks instead of only refusing — and only the app can say yes.

Drives the real app on the real database (`support.ApiHarness`), so it needs
`DATABASE_URL` like the other store tests. The agent runs on the deterministic
model: NEAR_AI_API_KEY is blanked so a key in the shell cannot make it a live call.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from app.modules.agent import policy
from tests import support as test_support


class ApprovalsTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"NEAR_AI_API_KEY": ""}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.account = test_support.TempAccount(balance_ngn=50_000)
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.addCleanup(self.api.restart)
        self.api.sell_with(test_support.FakeBills())
        self.client = self.api.client
        self.bill = self.client.post("/v1/bills", json={
            "kind": "airtime", "provider": "MTN", "reference": "08030000003",
            "label": "Test line",
        }).json()
        self.client.patch("/v1/limits",
                          json={"monthly_cap_ngn": 20_000, "per_payment_cap_ngn": 2_000})

    def ask_over_the_limit(self, amount=5_000):
        return self.api.state().agent.respond(f"pay {amount} for my line")

    def pending(self):
        return [r for r in self.client.get("/v1/approvals").json()
                if r["status"] == "pending"]

    def test_over_a_limit_the_agent_files_a_request_and_pays_nothing(self):
        reply = self.ask_over_the_limit()
        self.assertEqual(reply.code, policy.OVER_PER_PAYMENT_CAP)
        self.assertIn("Stark app", reply.reply)
        self.assertIsNone(reply.receipt_id)

        [request] = self.pending()
        self.assertEqual((request["bill_id"], request["amount_ngn"], request["reason"]),
                         (self.bill["id"], 5_000, policy.OVER_PER_PAYMENT_CAP))
        self.assertGreater(request["expires_at"], request["created_at"])
        self.assertEqual(self.account.store.wallet()["balance_ngn"], 50_000)

    def test_asking_twice_waits_once(self):
        self.ask_over_the_limit()
        self.ask_over_the_limit()
        self.assertEqual(len(self.pending()), 1)

    def test_approving_pays_that_one_amount_past_the_cap(self):
        self.ask_over_the_limit()
        [request] = self.pending()

        response = self.client.post(f"/v1/approvals/{request['id']}/approve")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["request"]["status"], "approved")
        self.assertEqual(body["receipt"]["amount_ngn"], 5_000)
        self.assertEqual(body["request"]["receipt_id"], body["receipt"]["id"])
        self.assertEqual(self.pending(), [])

        again = self.client.post(f"/v1/approvals/{request['id']}/approve")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["code"], "request_closed")

        # The cap still holds for everything else.
        refused = self.client.post("/v1/payments",
                                   json={"bill_id": self.bill["id"], "amount_ngn": 5_000})
        self.assertEqual(refused.json()["code"], policy.OVER_PER_PAYMENT_CAP)

    def test_denying_pays_nothing_and_leaves_a_declined_row(self):
        self.ask_over_the_limit()
        [request] = self.pending()
        denied = self.client.post(f"/v1/approvals/{request['id']}/deny").json()
        self.assertEqual(denied["status"], "denied")
        self.assertEqual(self.account.store.wallet()["balance_ngn"], 50_000)

        [row] = self.client.get("/v1/activity").json()
        self.assertEqual((row["status"], row["amount_ngn"]), ("declined", 5_000))
        self.assertEqual(row["reason"], "You declined this payment.")

    def test_a_paused_account_cannot_approve_and_the_request_keeps_waiting(self):
        self.ask_over_the_limit()
        [request] = self.pending()
        self.client.post("/v1/controls/pause")
        response = self.client.post(f"/v1/approvals/{request['id']}/approve")
        self.assertEqual(response.json()["code"], policy.PAUSED)
        self.assertEqual([r["id"] for r in self.pending()], [request["id"]])

    def test_a_lapsed_request_reads_expired_and_cannot_be_approved(self):
        self.ask_over_the_limit()
        [request] = self.pending()
        self.account.db.query(
            "UPDATE payment_requests SET expires_at = '2000-01-01T00:00:00Z'"
            " WHERE user_id = $1", [self.account.id])
        response = self.client.post(f"/v1/approvals/{request['id']}/approve")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["status"], "expired")

    def test_an_unknown_request_is_404(self):
        response = self.client.post("/v1/approvals/req_nope/approve")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "unknown_request")

    def test_the_window_is_a_setting_with_fixed_choices(self):
        self.assertEqual(self.client.get("/v1/limits").json()["approval_window_minutes"], 60)
        changed = self.client.patch("/v1/limits", json={"approval_window_minutes": 15})
        self.assertEqual(changed.json()["approval_window_minutes"], 15)
        bad = self.client.patch("/v1/limits", json={"approval_window_minutes": 7})
        self.assertEqual(bad.json()["code"], "bad_limits")

        reply = self.ask_over_the_limit()
        self.assertIn("within 15 minutes", reply.reply)

    def test_a_refusal_that_is_not_a_limit_shows_in_activity(self):
        self.account.store.set_wallet(1_000, 0)
        reply = self.api.state().agent.respond("pay 1500 for my line")
        self.assertEqual(reply.code, policy.INSUFFICIENT_BALANCE)
        [row] = self.client.get("/v1/activity").json()
        self.assertEqual(row["status"], "declined")
        self.assertEqual(row["reason"], policy.MESSAGES[policy.INSUFFICIENT_BALANCE])
        self.assertEqual(self.pending(), [])


if __name__ == "__main__":
    unittest.main()
