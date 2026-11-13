"""Operator alerts, vault holdings and the admin key: no database, no network."""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.filters.http_exception_filter import HttpExceptionFilter
from app.modules.admin import admin_controller
from app.modules.chain import near_tx
from app.modules.settings.operator_limits import OperatorLimits
from app.modules.treasury.treasury_watch import TreasuryWatch
from app.modules.vault.vault_service import VaultService
from app.shared.services.api_config_service import _admin_key


def report(flutterwave=500_000, usdc=Decimal(1000), coverage=200_000, vaults=None):
    return {
        "owed_to_users_ngn": 1_000_000,
        "held": {"flutterwave_ngn": flutterwave, "pending_purchases_ngn": 0,
                 "treasury_usdc_as_ngn": None if usdc is None else int(usdc * 1500)},
        "treasury_usdc": usdc,
        "vaults": vaults,
        "coverage_ngn": coverage,
        "unsettled_vault_ops": 0,
    }


class MemoryAlerts:
    """`OperatorAlerts` without the database: the same raise/clear contract."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def raise_alarm(self, kind, message):
        row = self.rows.get(kind)
        new = row is None or row["cleared"] is not None
        self.rows[kind] = {"message": message, "cleared": None}
        return new

    def clear(self, kind, message):
        row = self.rows.get(kind)
        if row is None or row["cleared"] is not None:
            return False
        row["cleared"] = message
        return True

    def active(self):
        return {k: r["message"] for k, r in self.rows.items() if r["cleared"] is None}


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.alerts = MemoryAlerts()
        self.limits = OperatorLimits.fixed(float_low_ngn=100_000, treasury_low_usdc=100)
        self.watch = TreasuryWatch(self.limits, self.alerts)

    def test_healthy_balances_raise_nothing(self):
        self.watch.check(report())
        self.assertEqual(self.alerts.rows, {})

    def test_low_flutterwave_is_raised_once_and_kept_current(self):
        self.watch.check(report(flutterwave=40_000))
        self.watch.check(report(flutterwave=30_000))
        self.assertEqual(list(self.alerts.active()), ["flutterwave"])
        self.assertIn("₦30,000", self.alerts.active()["flutterwave"])

    def test_recovery_clears_it(self):
        self.watch.check(report(flutterwave=40_000))
        self.watch.check(report())
        self.assertEqual(self.alerts.active(), {})
        self.assertIn("back to ₦500,000", self.alerts.rows["flutterwave"]["cleared"])

    def test_low_treasury_usdc_is_raised(self):
        self.watch.check(report(usdc=Decimal("12.5")))
        self.assertIn("12.50 USDC", self.alerts.active()["treasury"])

    def test_negative_coverage_is_raised(self):
        self.watch.check(report(coverage=-5_000))
        self.assertIn("-₦5,000", self.alerts.active()["coverage"])

    def test_a_raised_threshold_applies_to_the_next_check(self):
        self.watch.check(report(flutterwave=150_000))
        self.assertEqual(self.alerts.active(), {})
        self.limits.set({"float_low_ngn": 200_000})
        self.watch.check(report(flutterwave=150_000))
        self.assertIn("under ₦200,000", self.alerts.active()["flutterwave"])

    def test_unreadable_balances_change_nothing(self):
        self.watch.check(report(flutterwave=40_000))
        self.watch.check(report(flutterwave=None, usdc=None, coverage=-1_000_000))
        # Unknown is neither low nor recovered: the raised alarm stays as it was.
        self.assertEqual(list(self.alerts.active()), ["flutterwave"])

    def test_coverage_waits_for_mainnet_vaults_to_be_read(self):
        unread = {"network": "mainnet", "count": 2, "usdc": None, "counted": True}
        self.watch.check(report(coverage=-1_000, vaults=unread))
        self.assertNotIn("coverage", self.alerts.active())

    def test_testnet_vaults_do_not_hold_coverage_back(self):
        unread = {"network": "testnet", "count": 2, "usdc": None, "counted": False}
        self.watch.check(report(coverage=-1_000, vaults=unread))
        self.assertIn("coverage", self.alerts.active())


class FakeVaultDb:
    def __init__(self, vaults):
        self.vaults = vaults
        self.reads = 0

    def query(self, sql, params):
        self.reads += 1
        return [{"account_id": v} for v in self.vaults]


class FakeRpc:
    def __init__(self, balances):
        self.balances = balances

    def view(self, contract, method, args):
        balance = self.balances[args["account_id"]]
        if balance is None:
            raise near_tx.NearRpcError("timeout")
        return str(balance)


def vault_service(balances):
    chain = SimpleNamespace(rpc=FakeRpc(balances), usdc_id="usdc.fakes.testnet",
                            funder_id="f.testnet", network="testnet", broadcast=True)
    return VaultService(FakeVaultDb(list(balances)), chain, None, lambda: Decimal(1500))


class VaultHoldingsTests(unittest.TestCase):
    def test_sums_every_vault_and_reuses_the_read(self):
        vaults = vault_service({"u-a.f.testnet": 2_500_000, "u-b.f.testnet": 10_360_000})
        held = vaults.holdings()
        self.assertEqual((held.count, held.usdc), (2, Decimal("12.86")))
        vaults.holdings()
        self.assertEqual(vaults.db.reads, 1)

    def test_an_unreadable_vault_counts_as_zero(self):
        vaults = vault_service({"u-a.f.testnet": 2_500_000, "u-b.f.testnet": None})
        held = vaults.holdings()
        self.assertEqual((held.count, held.usdc), (2, Decimal("2.5")))


KEY = "k" * 32


def client(admin_key, limits=None):
    app = FastAPI()
    app.state.module = SimpleNamespace(
        config=SimpleNamespace(admin_key=admin_key),
        admin=SimpleNamespace(overview=lambda: {"ok": True}),
        operator_limits=limits or OperatorLimits.fixed(),
    )
    HttpExceptionFilter.register(app)
    app.include_router(admin_controller.router)
    return TestClient(app)


class AdminGuardTests(unittest.TestCase):
    def test_the_right_key_gets_the_overview(self):
        res = client(KEY).get("/v1/admin/overview", headers={"X-Stark-Admin-Key": KEY})
        self.assertEqual((res.status_code, res.json()), (200, {"ok": True}))

    def test_a_wrong_or_missing_key_is_refused(self):
        for headers in ({}, {"X-Stark-Admin-Key": "k" * 31 + "x"}):
            res = client(KEY).get("/v1/admin/overview", headers=headers)
            self.assertEqual((res.status_code, res.json()["code"]), (401, "unauthorized"))

    def test_no_key_configured_refuses_everyone(self):
        res = client(None).get("/v1/admin/overview", headers={"X-Stark-Admin-Key": KEY})
        self.assertEqual((res.status_code, res.json()["code"]), (403, "admin_disabled"))

    def test_a_short_key_is_refused_at_boot(self):
        with self.assertRaises(ValueError):
            _admin_key("short")
        self.assertIsNone(_admin_key("  "))


class LimitsRouteTests(unittest.TestCase):
    """`PATCH /v1/admin/limits` on in-memory limits: the body, the codes, the guard."""

    def setUp(self):
        self.limits = OperatorLimits.fixed()
        self.client = client(KEY, self.limits)

    def patch(self, body, key=KEY):
        return self.client.patch("/v1/admin/limits", json=body,
                                 headers={"X-Stark-Admin-Key": key})

    def test_a_change_answers_every_limit(self):
        res = self.patch({"withdraw_daily_ngn": 300_000})
        self.assertEqual(res.status_code, 200)
        row = next(r for r in res.json()["limits"] if r["key"] == "withdraw_daily_ngn")
        self.assertEqual((row["value"], row["default"], row["overridden"]),
                         (300_000, 200_000, True))
        self.assertEqual(self.limits.get("withdraw_daily_ngn"), 300_000)

    def test_null_puts_a_limit_back_on_its_default(self):
        self.patch({"card_hold_hours": 24})
        res = self.patch({"card_hold_hours": None})
        row = next(r for r in res.json()["limits"] if r["key"] == "card_hold_hours")
        self.assertEqual((row["value"], row["overridden"]), (72, False))

    def test_refusals_carry_their_codes(self):
        for body, code in (({"nope": 1}, "unknown_limit"),
                           ({"card_hold_hours": 721}, "bad_limit"),
                           ({"usdc_rate_min": 6000}, "bad_limit"),
                           ({"card_hold_hours": 1.5}, "bad_request"),
                           ({"card_hold_hours": "24"}, "bad_request")):
            with self.subTest(body=body):
                res = self.patch(body)
                self.assertEqual((res.status_code, res.json()["code"]), (400, code))
        self.assertEqual(self.limits.stored(), {})

    def test_the_admin_key_is_required(self):
        res = self.patch({"card_hold_hours": 24}, key="k" * 31 + "x")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(self.limits.get("card_hold_hours"), 72)


if __name__ == "__main__":
    unittest.main()
