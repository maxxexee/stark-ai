"""Operator limits: defaults from the environment, the owner's overrides, the checks.

The `OperatorLimitsTests` and `CacheTests` run without a database (a fake one for
the cache). `LimitsEndpointTests` and `LiveConsumerTests` run the real app on the
real database, like `test_money`, and need `DATABASE_URL`.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.common.api_error import ApiError
from app.modules.settings import operator_limits
from app.modules.settings.operator_limits import LIMITS, OperatorLimits


class OperatorLimitsTests(unittest.TestCase):
    def test_defaults_come_from_the_environment_else_the_built_in_value(self):
        limits = OperatorLimits(None, env={"STARK_WITHDRAW_DAILY_NGN": "300000",
                                           "STARK_CARD_HOLD_HOURS": " ",
                                           "STARK_USDC_NGN_RATE": "1380.56"})
        self.assertEqual(limits.get("withdraw_daily_ngn"), 300_000)
        self.assertEqual(limits.get("card_hold_hours"), 72)
        self.assertEqual(limits.get("usdc_rate_pinned"), 1380)
        self.assertEqual(limits.get("usdc_spread_ngn"), 10)

    def test_the_move_limit_reads_the_old_fraction_as_a_percentage(self):
        for raw, pct in (("0.15", 15), ("0.05", 5), ("20", 20)):
            with self.subTest(raw=raw):
                limits = OperatorLimits(None, env={"STARK_USDC_RATE_MAX_MOVE": raw})
                self.assertEqual(limits.get("usdc_rate_max_move_pct"), pct)

    def test_an_override_wins_and_null_resets_it(self):
        limits = OperatorLimits.fixed()
        limits.set({"withdraw_daily_ngn": 500_000})
        self.assertEqual(limits.get("withdraw_daily_ngn"), 500_000)
        limits.set({"withdraw_daily_ngn": None})
        self.assertEqual(limits.get("withdraw_daily_ngn"), 200_000)
        self.assertEqual(limits.stored(), {})

    def test_all_lists_every_limit_in_order_with_its_default(self):
        limits = OperatorLimits.fixed(card_hold_hours=24)
        rows = limits.all()
        self.assertEqual([row["key"] for row in rows], [limit.key for limit in LIMITS])
        hold = next(row for row in rows if row["key"] == "card_hold_hours")
        self.assertEqual(hold, {"key": "card_hold_hours",
                                "label": "Hold on card deposits before withdrawal",
                                "unit": "hours", "value": 24, "default": 72, "minimum": 0,
                                "maximum": 720, "overridden": True})

    def test_an_unknown_key_in_code_is_a_key_error(self):
        with self.assertRaises(KeyError):
            OperatorLimits.fixed().get("withdraw_dialy_ngn")
        with self.assertRaises(KeyError):
            OperatorLimits.fixed(withdraw_dialy_ngn=1)

    def test_bad_changes_are_refused_and_nothing_is_saved(self):
        limits = OperatorLimits.fixed()
        for change, code in (({"nope": 1}, "unknown_limit"),
                             ({"card_hold_hours": -1}, "bad_limit"),
                             ({"card_hold_hours": 721}, "bad_limit"),
                             ({"card_hold_hours": 24, "bank_lookups_per_day": 0}, "bad_limit"),
                             ({"usdc_rate_min": 5000}, "bad_limit"),
                             ({"usdc_rate_min": 2000, "usdc_rate_max": 1000}, "bad_limit")):
            with self.subTest(change=change), self.assertRaises(ApiError) as caught:
                limits.set(change)
            self.assertEqual((caught.exception.status, caught.exception.code), (400, code))
        self.assertEqual(limits.stored(), {})

    def test_a_range_message_names_the_limit_and_its_range(self):
        with self.assertRaises(ApiError) as caught:
            OperatorLimits.fixed().set({"card_hold_hours": 721})
        self.assertEqual(caught.exception.message,
                         "Hold on card deposits before withdrawal must be between 0 and 720.")

    def test_the_rate_bounds_rule_counts_the_values_already_set(self):
        limits = OperatorLimits.fixed(usdc_rate_max=1000)
        with self.assertRaises(ApiError):
            limits.set({"usdc_rate_min": 1000})
        limits.set({"usdc_rate_min": 999})
        with self.assertRaises(ApiError):
            limits.set({"usdc_rate_max": None, "usdc_rate_min": 5000})

    def test_a_change_is_logged_with_old_and_new(self):
        limits = OperatorLimits.fixed()
        with self.assertLogs("stark.limits", "INFO") as logged:
            limits.set({"card_hold_hours": 24})
        self.assertIn("card_hold_hours changed from 72 to 24", logged.output[0])


class FakeDb:
    """The settings table, counting the reads."""

    def __init__(self):
        self.rows: dict[str, int] = {}
        self.reads = 0

    def query(self, sql, params=None):
        if sql.startswith("INSERT"):
            self.rows[params[0]] = params[1]
        elif sql.startswith("DELETE"):
            self.rows.pop(params[0], None)
        else:
            self.reads += 1
            return [{"key": key, "value": str(value)} for key, value in self.rows.items()]
        return []


class CacheTests(unittest.TestCase):
    def at(self, seconds):
        return mock.patch.object(operator_limits.time, "monotonic", return_value=seconds)

    def test_overrides_are_read_once_per_fifteen_seconds(self):
        db = FakeDb()
        limits = OperatorLimits(db, env={})
        with self.at(100):
            limits.get("card_hold_hours")
            limits.get("withdraw_daily_ngn")
        self.assertEqual(db.reads, 1)
        db.rows["limit:card_hold_hours"] = 12    # another process saved it
        with self.at(114):
            self.assertEqual(limits.get("card_hold_hours"), 72, "still cached")
        with self.at(116):
            self.assertEqual(limits.get("card_hold_hours"), 12)
        self.assertEqual(db.reads, 2)

    def test_a_write_is_seen_at_once_and_reset_deletes_the_row(self):
        db = FakeDb()
        limits = OperatorLimits(db, env={})
        with self.at(100):
            limits.get("card_hold_hours")
            limits.set({"card_hold_hours": 24})
            self.assertEqual(limits.get("card_hold_hours"), 24)
            self.assertEqual(db.rows, {"limit:card_hold_hours": 24})
            limits.set({"card_hold_hours": None})
            self.assertEqual(limits.get("card_hold_hours"), 72)
        self.assertEqual(db.rows, {})

    def test_rows_for_limits_that_no_longer_exist_are_ignored(self):
        db = FakeDb()
        db.rows["limit:retired"] = 5
        db.rows["limit:card_hold_hours"] = 24
        self.assertEqual(OperatorLimits(db, env={}).stored(), {"card_hold_hours": 24})


class LimitsEndpointTests(unittest.TestCase):
    """`PATCH /v1/admin/limits` on the real settings table.

    The table is shared with the dev server, so the one limit touched is put back as
    it was."""

    ADMIN_KEY = "k" * 32
    KEY = "bank_lookups_per_day"

    def setUp(self):
        from tests import support

        self.account = support.TempAccount()
        self.addCleanup(self.account.close)
        self.api = support.ApiHarness(self.account, admin_key=self.ADMIN_KEY,
                                      live_limits=True)
        limits = self.api.module.operator_limits
        before = limits.stored().get(self.KEY)
        self.addCleanup(limits.set, {self.KEY: before})

    def patch(self, body):
        return self.api.client.patch("/v1/admin/limits", json=body,
                                     headers={"X-Stark-Admin-Key": self.ADMIN_KEY})

    def row(self, rows):
        return next(row for row in rows if row["key"] == self.KEY)

    def test_a_change_is_stored_reread_and_reset(self):
        changed = self.patch({self.KEY: 7})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.row(changed.json()["limits"])["value"], 7)
        # A second process, with its own cache, reads the same row.
        fresh = OperatorLimits(self.account.db)
        self.assertEqual(fresh.get(self.KEY), 7)
        reset = self.patch({self.KEY: None})
        self.assertEqual(self.row(reset.json()["limits"])["overridden"], False)
        self.assertNotIn(self.KEY, OperatorLimits(self.account.db).stored())

    def test_a_refused_change_saves_nothing(self):
        refused = self.patch({self.KEY: 7, "usdc_rate_min": 0})
        self.assertEqual((refused.status_code, refused.json()["code"]), (400, "bad_limit"))
        self.assertNotEqual(OperatorLimits(self.account.db).get(self.KEY), 7)


class LiveConsumerTests(unittest.TestCase):
    """The app's own wiring: a change on the admin route reaches the route that
    decides on it, with no rebuild and no restart. The harness keeps the limits in
    memory, so the shared table is not touched."""

    ADMIN_KEY = "k" * 32

    def setUp(self):
        from tests import support
        from tests.test_money import FakeFlutterwave

        self.account = support.TempAccount()
        self.addCleanup(self.account.close)
        self.api = support.ApiHarness(self.account, admin_key=self.ADMIN_KEY)
        self.api.module.withdrawals.flutterwave = FakeFlutterwave()

    def set_limit(self, value):
        response = self.api.client.patch("/v1/admin/limits",
                                          json={"bank_lookups_per_day": value},
                                          headers={"X-Stark-Admin-Key": self.ADMIN_KEY})
        self.assertEqual(response.status_code, 200)

    def lookup(self):
        return self.api.client.post("/v1/wallet/bank-accounts/resolve",
                                    json={"bank_code": "058",
                                          "account_number": "0123456789"}).status_code

    def test_a_changed_lookup_limit_applies_to_the_next_lookup(self):
        self.set_limit(1)
        self.assertEqual((self.lookup(), self.lookup()), (200, 429))
        self.set_limit(2)
        self.assertEqual((self.lookup(), self.lookup()), (200, 429))


if __name__ == "__main__":
    unittest.main()
