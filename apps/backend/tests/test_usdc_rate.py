import unittest
from decimal import Decimal
from unittest import mock

from app.modules.liquidity import usdc_rate
from app.modules.liquidity.usdc_rate import RateUnavailable, UsdcRate


class ScriptedRate(UsdcRate):
    """Paycrest replaced by a list of answers; an exception in the list is raised."""

    def __init__(self, answers, **kwargs):
        super().__init__(spread_ngn=Decimal("10"), **kwargs)
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
        rate = ScriptedRate([], fixed=Decimal("1500"))
        self.assertEqual(rate.buying(), Decimal("1490"))
        self.assertEqual(rate.selling(), Decimal("1510"))
        self.assertEqual(rate.calls, 0)


if __name__ == "__main__":
    unittest.main()
