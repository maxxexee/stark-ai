"""Operator alerts and the admin key: no database, no network."""

from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.filters.http_exception_filter import HttpExceptionFilter
from app.modules.admin import admin_controller
from app.modules.treasury.treasury_watch import (
    LAGOS,
    REPEAT_SECONDS,
    TreasuryWatch,
    WatchSettings,
)
from app.shared.services.api_config_service import _admin_key

SETTINGS = WatchSettings(float_low_ngn=100_000, treasury_low_usdc=Decimal(100),
                         summary_hour=8)
NOON = datetime(2026, 11, 11, 12, tzinfo=LAGOS).timestamp()


def report(flutterwave=500_000, usdc=Decimal(1000), coverage=200_000):
    return {
        "owed_to_users_ngn": 1_000_000,
        "held": {"flutterwave_ngn": flutterwave, "pending_purchases_ngn": 0,
                 "treasury_usdc_as_ngn": None if usdc is None else int(usdc * 1500)},
        "treasury_usdc": usdc,
        "coverage_ngn": coverage,
        "unsettled_vault_ops": 0,
    }


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.said: list[str] = []
        self.clock = NOON
        self.watch = TreasuryWatch(SETTINGS, self.say, now=lambda: self.clock)

    def say(self, text: str) -> int:
        self.said.append(text)
        return 1

    def test_healthy_balances_say_nothing(self):
        self.watch.check(report())
        self.assertEqual(self.said, [])

    def test_low_flutterwave_alerts_once_then_repeats_after_six_hours(self):
        self.watch.check(report(flutterwave=40_000))
        self.watch.check(report(flutterwave=30_000))
        self.assertEqual(len(self.said), 1)
        self.assertIn("₦40,000", self.said[0])

        self.clock += REPEAT_SECONDS
        self.watch.check(report(flutterwave=30_000))
        self.assertEqual(len(self.said), 2)

    def test_recovery_is_announced_once(self):
        self.watch.check(report(flutterwave=40_000))
        self.watch.check(report())
        self.watch.check(report())
        self.assertEqual(len(self.said), 2)
        self.assertIn("back to ₦500,000", self.said[1])

    def test_low_treasury_usdc_alerts(self):
        self.watch.check(report(usdc=Decimal("12.5")))
        self.assertEqual(len(self.said), 1)
        self.assertIn("12.50 USDC", self.said[0])

    def test_negative_coverage_alerts(self):
        self.watch.check(report(coverage=-5_000))
        self.assertIn("-₦5,000", self.said[0])

    def test_unreadable_balances_raise_nothing(self):
        self.watch.check(report(flutterwave=None, usdc=None, coverage=-1_000_000))
        self.assertEqual(self.said, [])

    def test_summary_goes_out_once_in_the_summary_hour(self):
        self.clock = datetime(2026, 11, 11, 8, 5, tzinfo=LAGOS).timestamp()
        self.watch.check(report())
        self.clock += 600
        self.watch.check(report())
        self.assertEqual(len(self.said), 1)
        self.assertIn("Coverage: ₦200,000", self.said[0])

        self.clock = datetime(2026, 11, 12, 8, 1, tzinfo=LAGOS).timestamp()
        self.watch.check(report())
        self.assertEqual(len(self.said), 2)


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
