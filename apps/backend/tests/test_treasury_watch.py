"""Operator alerts and the admin key: no database, no network."""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.filters.http_exception_filter import HttpExceptionFilter
from app.modules.admin import admin_controller
from app.modules.treasury.treasury_watch import TreasuryWatch, WatchSettings
from app.shared.services.api_config_service import _admin_key

SETTINGS = WatchSettings(float_low_ngn=100_000, treasury_low_usdc=Decimal(100))


def report(flutterwave=500_000, usdc=Decimal(1000), coverage=200_000):
    return {
        "owed_to_users_ngn": 1_000_000,
        "held": {"flutterwave_ngn": flutterwave, "pending_purchases_ngn": 0,
                 "treasury_usdc_as_ngn": None if usdc is None else int(usdc * 1500)},
        "treasury_usdc": usdc,
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
        self.watch = TreasuryWatch(SETTINGS, self.alerts)

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

    def test_unreadable_balances_change_nothing(self):
        self.watch.check(report(flutterwave=40_000))
        self.watch.check(report(flutterwave=None, usdc=None, coverage=-1_000_000))
        # Unknown is neither low nor recovered: the raised alarm stays as it was.
        self.assertEqual(list(self.alerts.active()), ["flutterwave"])


KEY = "k" * 32


def client(admin_key):
    app = FastAPI()
    app.state.module = SimpleNamespace(
        config=SimpleNamespace(admin_key=admin_key),
        admin=SimpleNamespace(overview=lambda: {"ok": True}),
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


if __name__ == "__main__":
    unittest.main()
