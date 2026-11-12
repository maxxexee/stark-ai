"""The reminder rules, pinned.

Hermetic: pure functions and one in-memory log, so no server, no clock of its
own (today is always passed in), no network.
"""

from __future__ import annotations

import threading
import unittest
from datetime import date, datetime, timezone

from app.modules.reminder.reminders import (
    NotifyLog, WINDOW_DAYS, due_for_push, due_soon, line, parse_date,
    push_text, severity, summary,
)

TODAY = date(2026, 10, 24)


def bill(renews_on="2026-10-27", **extra):
    base = {"id": "bill_dstv", "kind": "tv", "provider": "DStv",
            "label": "Living room TV", "renews_on": renews_on}
    base.update(extra)
    return base


class ParseDate(unittest.TestCase):
    def test_a_clean_date(self):
        self.assertEqual(parse_date("2026-11-03"), date(2026, 11, 3))

    def test_any_iso_string_starting_with_a_date(self):
        self.assertEqual(parse_date("2026-11-03T00:00:00Z"), date(2026, 11, 3))

    def test_dates_and_datetimes_pass_through(self):
        self.assertEqual(parse_date(date(2026, 11, 3)), date(2026, 11, 3))
        moment = datetime(2026, 11, 3, 9, 30, tzinfo=timezone.utc)
        self.assertEqual(parse_date(moment), date(2026, 11, 3))

    def test_nonsense_is_none_not_a_guess(self):
        for value in ("soon", "", None, "3/11/2026", "2026-13-45", 12):
            with self.subTest(value=value):
                self.assertIsNone(parse_date(value))


class DueSoon(unittest.TestCase):
    def test_a_bill_inside_the_window_is_due(self):
        items = due_soon([bill()], today=TODAY)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["days_until"], 3)
        self.assertEqual(items[0]["renews_on"], "2026-10-27")
        self.assertEqual(items[0]["provider"], "DStv")

    def test_a_bill_without_a_date_is_never_due(self):
        self.assertEqual(due_soon([bill(renews_on=None)], today=TODAY), [])

    def test_the_window_is_a_week_in_both_directions(self):
        inside = [due_soon([bill("2026-10-31")], today=TODAY),      # +7
                  due_soon([bill("2026-10-17")], today=TODAY)]      # -7
        outside = [due_soon([bill("2026-11-01")], today=TODAY),     # +8
                   due_soon([bill("2026-10-16")], today=TODAY)]     # -8
        self.assertTrue(all(len(items) == 1 for items in inside))
        self.assertEqual(outside, [[], []])
        self.assertEqual(WINDOW_DAYS, 7)

    def test_overdue_inside_the_window_still_counts(self):
        items = due_soon([bill("2026-10-22")], today=TODAY)
        self.assertEqual(items[0]["days_until"], -2)

    def test_soonest_first(self):
        bills = [bill("2026-10-29", id="b_late"),
                 bill("2026-10-25", id="b_soon"),
                 bill("2026-10-27", id="b_mid")]
        items = due_soon(bills, today=TODAY)
        self.assertEqual([i["id"] for i in items], ["b_soon", "b_mid", "b_late"])

    def test_price_prefers_the_plan_then_the_last_amount_then_none(self):
        with_plan = due_soon([bill(plan_price_ngn=7900, last_amount_ngn=100)], today=TODAY)
        with_last = due_soon([bill(last_amount_ngn=100)], today=TODAY)
        with_neither = due_soon([bill()], today=TODAY)
        self.assertEqual(with_plan[0]["price_ngn"], 7900)
        self.assertEqual(with_last[0]["price_ngn"], 100)
        self.assertIsNone(with_neither[0]["price_ngn"])


class Severity(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(severity(0), "alert")
        self.assertEqual(severity(-3), "alert")
        self.assertEqual(severity(1), "warn")
        self.assertEqual(severity(3), "warn")
        self.assertEqual(severity(4), "info")


class Copy(unittest.TestCase):
    def item(self, days):
        return {"id": "b", "provider": "DStv", "days_until": days, "price_ngn": 7900}

    def test_spoken_lines(self):
        self.assertEqual(line(self.item(0)), "Your DStv is due today, ₦7,900.")
        self.assertEqual(line(self.item(1)), "Your DStv renews tomorrow, ₦7,900.")
        self.assertEqual(line(self.item(3)), "Your DStv renews in 3 days, ₦7,900.")
        self.assertEqual(line(self.item(-2)), "Your DStv was due 2 days ago, ₦7,900.")
        self.assertEqual(line(self.item(-1)), "Your DStv was due 1 day ago, ₦7,900.")

    def test_no_price_no_hanging_comma(self):
        self.assertEqual(line({"id": "b", "provider": "DStv", "days_until": 3,
                               "price_ngn": None}),
                         "Your DStv renews in 3 days.")

    def test_ui_summaries(self):
        self.assertEqual(summary(self.item(3)), "DStv renews in 3 days, ₦7,900.")
        self.assertEqual(summary(self.item(0)), "DStv renews today, ₦7,900.")
        self.assertEqual(summary(self.item(-2)), "DStv was due 2 days ago, ₦7,900.")

    def test_push_text_ends_with_the_action(self):
        self.assertEqual(push_text(self.item(3)),
                         "Your DStv renews in 3 days, ₦7,900. Reply to pay it.")


class NotifyLogTests(unittest.TestCase):
    def test_a_renewal_is_claimed_once(self):
        log = NotifyLog()
        item = {"id": "b", "renews_on": "2026-10-27"}
        self.assertTrue(log.claim(item))
        self.assertFalse(log.claim(item))

    def test_clear_lets_it_be_claimed_again(self):
        log = NotifyLog()
        item = {"id": "b", "renews_on": "2026-10-27"}
        log.claim(item)
        log.clear()
        self.assertTrue(log.claim(item))

    def test_due_for_push_claims_then_goes_quiet(self):
        log = NotifyLog()
        bills = [bill()]
        first = due_for_push(bills, log=log, today=TODAY)
        second = due_for_push(bills, log=log, today=TODAY)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_a_date_change_is_a_fresh_reminder(self):
        log = NotifyLog()
        log.claim({"id": "b", "renews_on": "2026-10-27"})
        self.assertTrue(log.claim({"id": "b", "renews_on": "2026-11-03"}))

    def test_exactly_one_thread_wins_the_claim(self):
        log = NotifyLog()
        item = {"id": "b", "renews_on": "2026-10-27"}
        barrier = threading.Barrier(8)
        wins = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            if log.claim(item):
                with lock:
                    wins.append(1)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(wins), 1)


if __name__ == "__main__":
    unittest.main()
