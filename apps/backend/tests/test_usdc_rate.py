import unittest
from decimal import Decimal
from unittest import mock

from app.modules.liquidity import usdc_rate
from app.modules.liquidity.usdc_rate import RateUnavailable, UsdcRate
from app.modules.settings.operator_limits import OperatorLimits


class ScriptedRate(UsdcRate):
    """Paycrest replaced by a list of answers; an exception in the list is raised."""

    def __init__(self, answers, **limits):
        super().__init__(OperatorLimits.fixed(**{"usdc_spread_ngn": 10, **limits}))
        self.answers = list(answers)
        self.calls = 0

    def _fetch(self):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class UsdcRateTests(unittest.TestCase):
    def at(self, seconds):
        return mock.patch.object(usdc_rate.time, "monotonic", return_value=seconds)

    def test_stark_buys_below_and_sells_above_the_market(self):
        rate = ScriptedRate([Decimal("1380.56")])
        with self.at(1000):
            self.assertEqual(rate.buying(), Decimal("1370.56"))
            self.assertEqual(rate.selling(), Decimal("1390.56"))
        self.assertEqual(rate.calls, 1, "one fetch serves both sides")

    def test_the_market_is_asked_again_after_a_minute(self):
        rate = ScriptedRate([Decimal("1380"), Decimal("1400")])
        with self.at(1000):
            rate.market()
        with self.at(1059):
            self.assertEqual(rate.market(), Decimal("1380"))
        with self.at(1061):
            self.assertEqual(rate.market(), Decimal("1400"))

    def test_an_outage_reuses_the_last_rate_for_fifteen_minutes_then_refuses(self):
        down = RateUnavailable("down")
        rate = ScriptedRate([Decimal("1380"), down, down])
        with self.at(1000):
            rate.market()
        with self.at(1000 + 14 * 60):
            self.assertEqual(rate.market(), Decimal("1380"))
        with self.at(1000 + 16 * 60), self.assertRaises(RateUnavailable):
            rate.market()

    def test_no_rate_at_all_refuses(self):
        rate = ScriptedRate([RateUnavailable("down")])
        with self.at(1000), self.assertRaises(RateUnavailable):
            rate.buying()

    def test_a_pinned_rate_never_asks_paycrest(self):
        rate = ScriptedRate([], usdc_rate_pinned=1500)
        self.assertEqual(rate.buying(), Decimal("1490"))
        self.assertEqual(rate.selling(), Decimal("1510"))
        self.assertEqual(rate.calls, 0)

    def test_a_pinned_rate_skips_the_bounds(self):
        rate = ScriptedRate([], usdc_rate_pinned=9000, usdc_rate_max=5000)
        self.assertEqual(rate.market(), Decimal(9000))


class LiveSettingsTests(unittest.TestCase):
    """The spread and the pin are read on every quote, so the admin page's change
    applies to the next one without rebuilding anything."""

    def at(self, seconds):
        return mock.patch.object(usdc_rate.time, "monotonic", return_value=seconds)

    def test_a_changed_spread_applies_to_the_next_quote(self):
        rate = ScriptedRate([], usdc_rate_pinned=1500)
        self.assertEqual(rate.buying(), Decimal(1490))
        rate.limits.set({"usdc_spread_ngn": 25})
        self.assertEqual((rate.buying(), rate.selling()), (Decimal(1475), Decimal(1525)))

    def test_a_spread_that_leaves_no_price_is_still_refused(self):
        rate = ScriptedRate([], usdc_rate_pinned=1500)
        rate.limits.set({"usdc_spread_ngn": 1000})
        rate.limits.set({"usdc_rate_pinned": 900})
        with self.assertRaises(RateUnavailable):
            rate.buying()

    def test_pinning_and_unpinning_live(self):
        rate = ScriptedRate([Decimal(1400), Decimal(1450)])
        with self.at(1000):
            self.assertEqual(rate.market(), Decimal(1400))
            rate.limits.set({"usdc_rate_pinned": 1600})
            self.assertEqual(rate.market(), Decimal(1600))
            self.assertEqual(rate.calls, 1, "a pin never asks Paycrest")
        with self.at(1001):
            rate.limits.set({"usdc_rate_pinned": 0})
            # Lifted: Paycrest is asked at once, and 1450 is within 15% of the pin.
            self.assertEqual(rate.market(), Decimal(1450))
        self.assertEqual(rate.calls, 2)

    def test_after_a_pin_paycrest_is_held_to_the_move_limit_from_it(self):
        rate = ScriptedRate([Decimal(1000)], usdc_rate_pinned=1600)
        with self.at(1000):
            rate.market()
            rate.limits.set({"usdc_rate_pinned": 0})
            with self.assertLogs("stark.rate", "ERROR"), self.assertRaises(RateUnavailable):
                rate.market()


if __name__ == "__main__":
    unittest.main()
