"""The suggestion rules, pinned.

Hermetic: state in, dicts out. Timestamps are relative to a real clock where
`build` insists on one, and pinned where the function takes `now`.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.modules.suggestion import suggestions
from app.modules.suggestion.suggestions import burn_rate, build

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def ts(**days_ago) -> str:
    return (NOW - timedelta(**days_ago)).isoformat().replace("+00:00", "Z")


def recent(**ago) -> str:
    """A timestamp measured from the real clock, for rules that read it.

    `_load_item` ignores telemetry older than a day, so a sample pinned to `NOW`
    becomes a sample from two days ago — the same trap `renewing_in` documents,
    and the reason this test used to pass on 2026-10-24 and fail on 2026-10-26.
    """
    return (datetime.now(timezone.utc) - timedelta(**ago)).isoformat().replace("+00:00", "Z")


def renewing_in(days: int) -> str:
    """A calendar date `days` from the real today.

    `build` reads the real clock — unlike `burn_rate`, it takes no `now` — so a
    renewal date pinned to `NOW` disagrees with it the day after this file was
    written, and the suite goes red at midnight for no code reason.
    """
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def receipt(units=23.9, status="delivered", when=None):
    return {"status": status, "units": units, "created_at": when or ts(days=3)}


def bill(**extra):
    base = {"id": "bill_dstv", "kind": "tv", "provider": "DStv",
            "label": "Living room TV"}
    base.update(extra)
    return base


def build_suggestions(**overrides):
    kwargs = {
        "bills": [bill()],
        "units_left": None,
        "days_left": None,
        "spent_ngn": 23_000,
        "cap_ngn": 30_000,
        "telemetry": [],
        "receipts": [],
        "tariff_ngn_per_kwh": 209.0,
    }
    kwargs.update(overrides)
    return build(**kwargs)


class BurnRate(unittest.TestCase):
    def test_two_deliveries_on_different_days_give_a_rate(self):
        rate = burn_rate([receipt(23.9, when=ts(days=14)), receipt(48.0, when=ts(days=2))],
                         now=NOW)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 71.9 / 12, places=3)

    def test_one_delivery_says_nothing_about_pace(self):
        self.assertIsNone(burn_rate([receipt(23.9)], now=NOW))

    def test_same_day_topups_are_a_day_not_a_habit(self):
        self.assertIsNone(burn_rate([receipt(20.0, when=ts(days=3, hours=-2)),
                                     receipt(30.0, when=ts(days=3))], now=NOW))

    def test_undelivered_and_unitless_receipts_do_not_count(self):
        receipts = [receipt(23.9, status="pending"), receipt(units=None),
                    receipt(0)]
        self.assertIsNone(burn_rate(receipts, now=NOW))

    def test_old_deliveries_are_out_of_the_lookback(self):
        self.assertIsNone(burn_rate([receipt(23.9, when=ts(days=30)),
                                     receipt(48.0, when=ts(days=20))], now=NOW))

    def test_a_broken_timestamp_is_skipped_not_guessed(self):
        rate = burn_rate([receipt(23.9, when="not-a-time"),
                          receipt(48.0, when=ts(days=2))], now=NOW)
        self.assertIsNone(rate)


class UnitsSignal(unittest.TestCase):
    def test_no_meter_no_signal(self):
        self.assertEqual(build_suggestions(units_left=None, days_left=None), [])

    def test_a_meter_far_from_empty_is_not_news(self):
        found = build_suggestions(units_left=40.0, days_left=12)
        self.assertEqual(found, [])

    def test_the_estimate_is_used_when_receipts_cannot_give_a_rate(self):
        found = build_suggestions(units_left=11.4, days_left=4)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["id"], "sug_units")
        self.assertEqual(found[0]["reason"], "units_low_estimate")
        self.assertEqual(found[0]["severity"], "warn")
        self.assertIn("roughly 4 days", found[0]["text"])

    def test_a_real_burn_rate_wins_over_the_estimate(self):
        # `build` reads the real clock and burn_rate's lookback is 14 days, so
        # these two deliveries must be relative to now. Pinned to NOW they age
        # out of the window, burn_rate falls back to None, and the suggestion
        # silently degrades to the estimate (or vanishes when days_left is also
        # beyond LOW_UNITS_DAYS) — the same trap recent() and renewing_in()
        # were introduced for.
        found = build_suggestions(
            units_left=12.0, days_left=9,
            # 24 units across 8 days = 3.0 a day, so 12 left is 4 days.
            receipts=[receipt(12.0, when=recent(days=10)),
                      receipt(12.0, when=recent(days=2))],
        )
        self.assertEqual(found[0]["reason"], "units_low")
        self.assertIn("3.0 units a day", found[0]["text"])
        self.assertIn("about 4 days", found[0]["text"])

    def test_severity_follows_the_runway(self):
        cases = [(2, "alert"), (4, "warn"), (5, "info")]
        for days, level in cases:
            with self.subTest(days=days):
                found = build_suggestions(units_left=10.0, days_left=days)
                self.assertEqual(found[0]["severity"], level)


class CapSignal(unittest.TestCase):
    def test_under_eighty_percent_is_quiet(self):
        self.assertEqual(build_suggestions(spent_ngn=23_000, cap_ngn=30_000), [])

    def test_near_the_limit_is_a_warning(self):
        found = build_suggestions(spent_ngn=24_500, cap_ngn=30_000)
        self.assertEqual(found[0]["id"], "sug_cap")
        self.assertEqual(found[0]["severity"], "warn")
        self.assertEqual(found[0]["text"],
                         "You've used 82% of your ₦30,000 limit. ₦5,500 is left this month.")

    def test_past_ninety_five_percent_is_an_alert(self):
        found = build_suggestions(spent_ngn=29_000, cap_ngn=30_000)
        self.assertEqual(found[0]["severity"], "alert")

    def test_no_cap_no_signal(self):
        self.assertEqual(build_suggestions(spent_ngn=29_000, cap_ngn=0), [])


class DueSignal(unittest.TestCase):
    def test_a_renewal_inside_the_window_becomes_a_suggestion(self):
        found = build_suggestions(bills=[bill(renews_on=renewing_in(3),
                                              plan_price_ngn=7900)])
        due = [f for f in found if f["reason"] == "bill_due"]
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["text"], "DStv renews in 3 days, ₦7,900.")
        self.assertEqual(due[0]["severity"], "warn")

    def test_at_most_two_renewals_surface(self):
        bills = [bill(id=f"b{i}", renews_on=renewing_in(i + 1)) for i in range(4)]
        found = build_suggestions(bills=bills)
        self.assertEqual(len([f for f in found if f["reason"] == "bill_due"]), 2)


class LoadSignal(unittest.TestCase):
    AC = [{"device_id": "living_ac", "watts": 1200, "ts": recent(hours=1)},
          {"device_id": "living_ac", "watts": 1200, "ts": recent(hours=2)},
          {"device_id": "fridge", "watts": 150, "ts": recent(hours=1)}]

    def test_one_device_cannot_be_an_imbalance(self):
        single = [s for s in self.AC if s["device_id"] == "living_ac"]
        self.assertEqual(build_suggestions(telemetry=single), [])

    def test_a_dominant_device_is_named_with_its_share(self):
        found = build_suggestions(telemetry=self.AC)
        load = [f for f in found if f["reason"] == "load_imbalance"]
        self.assertEqual(len(load), 1)
        # Average watts, not the sum: 1200 against 1200 + 150.
        self.assertIn("89% of measured usage", load[0]["text"])
        self.assertIn("₦6,019 a day", load[0]["text"])

    def test_a_balanced_load_is_not_a_suggestion(self):
        balanced = [{"device_id": "ac", "watts": 600, "ts": recent(hours=1)},
                    {"device_id": "fridge", "watts": 550, "ts": recent(hours=1)}]
        self.assertEqual(build_suggestions(telemetry=balanced), [])

    def test_stale_and_broken_samples_are_ignored(self):
        stale = [{"device_id": "ac", "watts": 1200, "ts": ts(days=2)},
                 {"device_id": "fridge", "watts": 150, "ts": ts(hours=1)}]
        broken = [{"device_id": "ac", "watts": "a lot", "ts": ts(hours=1)},
                  {"device_id": "fridge", "watts": 150, "ts": ts(hours=1)}]
        self.assertEqual(build_suggestions(telemetry=stale), [])
        self.assertEqual(build_suggestions(telemetry=broken), [])


class Shape(unittest.TestCase):
    def test_worst_news_first(self):
        found = build_suggestions(
            units_left=1.0, days_left=1, spent_ngn=29_000, cap_ngn=30_000,
            bills=[bill(renews_on=renewing_in(1))],
        )
        order = {"alert": 0, "warn": 1, "info": 2}
        self.assertEqual([f["severity"] for f in found],
                         sorted((f["severity"] for f in found),
                                key=lambda s: order[s]))

    def test_at_most_four_items(self):
        found = build_suggestions(
            units_left=1.0, days_left=1, spent_ngn=29_500, cap_ngn=30_000,
            bills=[bill(id=f"b{i}", renews_on=renewing_in(i + 1))
                   for i in range(4)],
            telemetry=self_ac(),
        )
        self.assertEqual(len(found), suggestions.MAX_ITEMS)

    def test_every_item_is_finished_copy_with_a_debugging_reason(self):
        found = build_suggestions(units_left=11.4, days_left=4)
        for item in found:
            with self.subTest(item=item):
                self.assertTrue(item["text"].endswith("."))
                self.assertIn(item["severity"], ("info", "warn", "alert"))
                self.assertTrue(item["reason"])


def self_ac():
    return [{"device_id": "ac", "watts": 1200, "ts": ts(hours=1)},
            {"device_id": "fridge", "watts": 150, "ts": ts(hours=1)}]


if __name__ == "__main__":
    unittest.main()
