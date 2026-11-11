"""A real account's data is its own: no artboard seed, nothing lost on restart.

Drives the API over HTTP as a throwaway account on the real database
(`support.ApiHarness`), so it needs `DATABASE_URL` like the store tests.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from app.modules.liquidity.usdc_rate import RateUnavailable, UsdcRate
from tests import support as test_support


class AccountDataTest(unittest.TestCase):
    def setUp(self):
        self.account = test_support.TempAccount()
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.addCleanup(self.api.restart)
        self.client = self.api.client

    def test_a_new_account_opens_empty(self):
        api = test_support.ApiHarness(self.account, opened=False)
        state = api.client.get("/v1/state").json()
        self.assertEqual(state["bills"], [])
        self.assertEqual(state["balance_ngn"], 0)
        self.assertIsNone(state["units_left"])
        self.assertIsNone(state["days_left"])
        self.assertEqual(api.client.get("/v1/activity").json(), [])
        self.assertEqual(self.account.store.wallet(), {"balance_ngn": 0, "spent_ngn": 0})

    def test_bills_and_limits_survive_a_restart(self):
        bill = self.client.post("/v1/bills", json={
            "kind": "airtime", "provider": "MTN", "reference": "08030000001",
            "label": "Test line",
        }).json()
        self.client.patch(f"/v1/bills/{bill['id']}", json={"label": "Renamed"})
        self.client.patch("/v1/limits",
                          json={"monthly_cap_ngn": 40_000, "per_payment_cap_ngn": 8_000})

        self.api.restart()

        bills = self.client.get("/v1/bills").json()
        self.assertEqual([(b["id"], b["label"]) for b in bills], [(bill["id"], "Renamed")])
        caps = self.client.get("/v1/limits").json()
        self.assertEqual((caps["monthly_cap_ngn"], caps["per_payment_cap_ngn"]),
                         (40_000, 8_000))

        self.client.delete(f"/v1/bills/{bill['id']}")
        self.api.restart()
        self.assertEqual(self.client.get("/v1/bills").json(), [])

    def test_a_reading_is_stamped_with_server_time(self):
        response = self.client.post("/v1/telemetry", json={
            "device_id": "ac", "watts": 900, "ts": "2001-01-01T00:00:00Z",
        })
        self.assertEqual(response.status_code, 202)
        rows = self.api.module.readings.since(self.account.id, "2000-01-01T00:00:00Z")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["ts"].startswith("20"))
        self.assertNotEqual(rows[0]["ts"], "2001-01-01T00:00:00Z")

    def test_negative_watts_are_refused(self):
        response = self.client.post("/v1/telemetry", json={"device_id": "ac", "watts": -5})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "bad_watts")

    def test_watts_that_are_not_a_number_keep_their_contract_code(self):
        response = self.client.post("/v1/telemetry", json={"watts": "lots"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "bad_watts")

    def test_reset_is_off_unless_switched_on(self):
        api = test_support.ApiHarness(self.account, stub_reset_enabled=False)
        response = api.client.post("/v1/_stub/reset")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "no_route")

    def test_withdraw_refuses_and_takes_nothing(self):
        self.account.store.set_wallet(5_000, 0)
        # No payout rail configured in tests: refused, and nothing leaves the balance.
        response = self.client.post("/v1/wallet/withdraw", json={
            "amount_ngn": 1_000, "bank_code": "058", "account_number": "0123456789"})
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["code"], "not_available")
        self.assertEqual(self.account.store.wallet()["balance_ngn"], 5_000)

    def test_crypto_withdraw_refuses_without_a_treasury_key(self):
        self.account.store.set_wallet(5_000, 0)
        response = self.client.post("/v1/wallet/withdraw/crypto", json={
            "amount_ngn": 2_000, "asset_id": "nep141:tron-usdt", "address": "TQn9Y2kh"})
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["code"], "not_available")
        self.assertEqual(self.account.store.wallet()["balance_ngn"], 5_000)
        methods = self.client.get("/v1/wallet/methods").json()
        self.assertEqual(methods["withdraw"], {"bank": False, "crypto": False})

    def test_rates_take_the_spread_each_way(self):
        self.api.module.usdc_rate = UsdcRate(spread_ngn=Decimal("10"),
                                             fixed=Decimal("1380.56"))
        response = self.client.get("/v1/wallet/rates")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deposit": "1370.56", "withdraw": "1390.56"})

    def test_rates_without_a_market_rate_are_provider_failed(self):
        class Down(UsdcRate):
            def _fetch(self):
                raise RateUnavailable("down")

        self.api.module.usdc_rate = Down(spread_ngn=Decimal("10"))
        response = self.client.get("/v1/wallet/rates")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "provider_failed")

    def test_top_up_is_labelled_test_money(self):
        self.account.store.set_wallet(0, 0)
        response = self.client.post("/v1/wallet/topup",
                                    json={"amount_ngn": 2_000, "source": "Bank transfer"})
        self.assertEqual(response.status_code, 201)
        moved = response.json()
        self.assertEqual(moved["entry"]["source"], "Test money")
        self.assertEqual(moved["wallet"]["balance_ngn"], 2_000)

    def test_an_amount_that_is_not_an_integer_is_bad_amount(self):
        response = self.client.post("/v1/payments",
                                    json={"bill_id": "bill_x", "amount_ngn": "12.5"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "bad_amount")

    def test_a_bill_without_renews_on_has_no_such_key(self):
        bill = self.client.post("/v1/bills", json={
            "kind": "airtime", "provider": "MTN", "reference": "08030000002",
        }).json()
        # Absent, not null: the contract says so, and a docs-only response model
        # must not have rewritten it.
        self.assertNotIn("renews_on", bill)
        self.assertNotIn("plan", bill)


if __name__ == "__main__":
    unittest.main()
