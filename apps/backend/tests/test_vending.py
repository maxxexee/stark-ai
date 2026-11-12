#!/usr/bin/env python3
"""Tests for M3: receipt store, vending gateway, two-phase payments.

Flutterwave is faked at its client (`support.FakeBills`), and the catalogue is the
slice in `support.CATALOGUE`.
"""

from __future__ import annotations

import unittest

from app.common.clock import Clock
from app.modules.flutterwave.flutterwave import FlutterwaveError
from app.modules.payment import payment_service
from app.modules.receipt import receipt_repository
from app.modules.vending import vending
from app.modules.vending.catalog import CATALOG
from tests import support as test_support
from tests.support import FakeBills

ELECTRICITY = {
    "id": "bill_home_meter",
    "kind": "electricity",
    "provider": "Ikeja Electric",
    "label": "Home meter",
    "reference": "0101170026583",
}
DSTV = {
    "id": "bill_dstv",
    "kind": "tv",
    "provider": "DStv",
    "label": "DStv Access",
    "reference": "7032119456",
    "plan": "CB141",  # DSTV Access, ₦1,800
}

AIRTIME = {
    "id": "bill_airtime",
    "kind": "airtime",
    "provider": "MTN",
    "label": "My line",
    "reference": "08031234567",
}

DATA = {
    "id": "bill_data",
    "kind": "data",
    "provider": "MTN",
    "label": "MTN data",
    "reference": "08031234567",
    "plan": "MD107",  # MTN 1.5 GB, ₦1,000
}

SEED_BALANCE = 64_200
SEED_SPENT = 12_400


class StoreCase(unittest.TestCase):
    """One throwaway account per test, on the database the app actually uses."""

    def setUp(self):
        self.account = test_support.TempAccount(
            balance_ngn=SEED_BALANCE, spent_ngn=SEED_SPENT
        )
        self.store = self.account.store

    def tearDown(self):
        self.account.close()


class StoreTests(StoreCase):
    def test_wallet_round_trip(self):
        self.assertEqual(
            self.store.wallet(), {"balance_ngn": SEED_BALANCE, "spent_ngn": SEED_SPENT}
        )

    def hold(self, amount=5_000):
        receipt, _ = self.store.record_debit(
            _receipt("r1", request_id="req-1", amount_ngn=amount), amount)
        return receipt

    def test_a_hold_leaves_the_balance_but_is_not_spend(self):
        self.hold()
        self.assertEqual(self.store.wallet(), {"balance_ngn": 59_200, "spent_ngn": SEED_SPENT})

    def test_a_hold_refuses_more_than_the_balance(self):
        with self.assertRaises(ValueError):
            self.hold(SEED_BALANCE + 1)
        self.assertEqual(self.store.wallet()["balance_ngn"], SEED_BALANCE)
        self.assertEqual(self.store.count(), 0)

    def test_a_delivered_hold_becomes_spend(self):
        self.hold()
        row = self.store.finish("r1", "delivered", token="1234")
        self.assertEqual((row["status"], row["token"]), ("delivered", "1234"))
        self.assertEqual(self.store.wallet(), {"balance_ngn": 59_200, "spent_ngn": 17_400})

    def test_a_failed_hold_goes_back_to_the_balance(self):
        self.hold()
        self.assertEqual(self.store.finish("r1", "failed")["status"], "failed")
        self.assertEqual(self.store.wallet(), {"balance_ngn": SEED_BALANCE,
                                               "spent_ngn": SEED_SPENT})

    def test_a_hold_is_settled_only_once(self):
        self.hold()
        self.assertIsNotNone(self.store.finish("r1", "delivered"))
        self.assertIsNone(self.store.finish("r1", "delivered"))
        self.assertIsNone(self.store.finish("r1", "failed"))
        self.assertEqual(self.store.wallet(), {"balance_ngn": 59_200, "spent_ngn": 17_400})

    def test_a_dropped_hold_leaves_no_trace(self):
        self.hold()
        self.store.drop_hold("r1")
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(self.store.wallet()["balance_ngn"], SEED_BALANCE)

    def test_created_receipt_is_findable_by_request_id(self):
        row = self.store.create(_receipt("r1", request_id="req-1"))
        self.assertEqual(self.store.by_request_id("req-1")["id"], row["id"])

    def test_request_id_is_unique(self):
        self.store.create(_receipt("r1", request_id="req-1"))
        with self.assertRaises(Exception):
            self.store.create(_receipt("r2", request_id="req-1"))

    def test_find_pending_ignores_finished_receipts(self):
        self.store.create(_receipt("r1", request_id="req-1", status="delivered"))
        self.assertIsNone(self.store.find_pending("bill_home_meter", 5_000))

    def test_find_pending_matches_only_the_same_intent(self):
        self.store.create(_receipt("r1", request_id="req-1", status="pending"))
        self.assertIsNone(self.store.find_pending("bill_home_meter", 6_000))
        self.assertIsNotNone(self.store.find_pending("bill_home_meter", 5_000))

    def test_recent_is_newest_first(self):
        self.store.create(_receipt("old", request_id="r-old", created_at="2026-10-01T00:00:00Z"))
        self.store.create(_receipt("new", request_id="r-new", created_at="2026-10-20T00:00:00Z"))
        self.assertEqual([r["id"] for r in self.store.recent(5)], ["new", "old"])

    def test_state_survives_a_new_connection(self):
        """A second store on the same database sees the same wallet and receipts."""
        self.store.record_debit(_receipt("r1", request_id="req-1"), 5_000)
        self.store.finish("r1", "delivered")

        reopened = test_support.BoundStore(
            receipt_repository.ReceiptRepository(self.account.db), self.account.id
        )
        self.assertEqual(reopened.wallet()["balance_ngn"], 59_200)
        self.assertEqual(reopened.count(), 1)
        self.assertEqual(reopened.get("r1")["status"], "delivered")

    def test_replace_all_clears_and_reseeds(self):
        self.store.create(_receipt("r1", request_id="req-1"))
        self.store.replace_all(
            [_receipt("seed", request_id="seed-1", status="delivered")],
            balance_ngn=SEED_BALANCE,
            spent_ngn=SEED_SPENT,
        )
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.recent()[0]["id"], "seed")
        self.assertEqual(self.store.wallet()["balance_ngn"], SEED_BALANCE)

    def test_api_shape_has_the_frozen_keys(self):
        row = self.store.create(_receipt("r1", request_id="req-1"))
        shape = receipt_repository.api_shape(row)
        for key in ("id", "bill_id", "bill_label", "amount_ngn", "units",
                    "token", "tx_hash", "created_at"):
            self.assertIn(key, shape)
        # Additive.
        self.assertIn("status", shape)
        self.assertIn("request_id", shape)


class GatewayTests(unittest.TestCase):
    def gateway(self, bills=None):
        self.bills = bills or FakeBills()
        return vending.VendingGateway(self.bills)

    def test_a_delivered_meter_gets_its_token_and_units(self):
        outcome = self.gateway().buy(ELECTRICITY, 5_000, "bill_req1")
        self.assertEqual(outcome.status, vending.DELIVERED)
        self.assertEqual(outcome.token, "1147 2398 5707 1234 5678")
        self.assertEqual(outcome.units, 23.92)  # worked out from the tariff

    def test_the_order_is_the_documented_one(self):
        self.gateway().buy(ELECTRICITY, 5_000, "bill_req1")
        self.assertEqual(self.bills.paid, [{
            "biller_code": "BIL113", "item_code": "UB159", "customer_id": "0101170026583",
            "amount_ngn": 5_000, "reference": "bill_req1",
        }])
        # The payment only says it was taken; the status read is what decides.
        self.assertEqual(self.bills.read, ["CF-FLYAPI-bill_req1"])

    def test_a_token_is_read_from_wherever_flutterwave_put_it(self):
        token = "48210937551288463019"
        printed = "4821 0937 5512 8846 3019"
        bills = FakeBills(extra=None)
        bills.bill_status = lambda _ref: {"status": "successful", "code": "200",
                                          "token": token, "extra": None}
        self.assertEqual(self.gateway(bills).buy(ELECTRICITY, 5_000, "bill_a").token, printed)

        bills = FakeBills(extra=None)
        pay_bill = bills.pay_bill
        bills.pay_bill = lambda **order: {**pay_bill(**order), "recharge_token": token}
        self.assertEqual(self.gateway(bills).buy(ELECTRICITY, 5_000, "bill_b").token, printed)

    def test_a_purchase_keeps_flutterwaves_id_for_the_retry(self):
        outcome = self.gateway(FakeBills("pending")).buy(ELECTRICITY, 5_000, "bill_req1")
        self.assertEqual(outcome.vendor_ref, "CF-FLYAPI-bill_req1")

    def test_pending_is_not_delivered(self):
        outcome = self.gateway(FakeBills("pending")).buy(ELECTRICITY, 5_000, "bill_req1")
        self.assertEqual(outcome.status, vending.PENDING)
        self.assertIsNone(outcome.token)
        self.assertFalse(outcome.ok)

    def test_a_failed_bill_is_reported_not_raised(self):
        outcome = self.gateway(FakeBills("failed")).buy(ELECTRICITY, 5_000, "bill_req1")
        self.assertEqual(outcome.status, vending.FAILED)
        self.assertIn("Nothing was charged", outcome.message)

    def test_a_refusal_is_failed_and_a_timeout_is_pending(self):
        refused = FakeBills()
        refused.refuse = FlutterwaveError(400, "Insufficient balance")
        outcome = self.gateway(refused).buy(ELECTRICITY, 5_000, "bill_req1")
        self.assertEqual(outcome.status, vending.FAILED)
        self.assertIn("nothing was charged", outcome.message)

        timed_out = FakeBills()
        timed_out.refuse = FlutterwaveError(0, "Could not reach Flutterwave")
        # It may have been placed, so it is re-read on the retry, never bought again.
        self.assertEqual(self.gateway(timed_out).buy(ELECTRICITY, 5_000, "bill_req1").status,
                         vending.PENDING)

    def test_airtime_is_bought_by_amount_on_a_234_number(self):
        outcome = self.gateway().buy(AIRTIME, 1_000, "bill_req1")
        self.assertEqual(outcome.status, vending.DELIVERED)
        self.assertIsNone(outcome.token)  # airtime has no meter token
        self.assertIsNone(outcome.units)
        self.assertEqual(self.bills.paid[0]["customer_id"], "+2348031234567")
        self.assertEqual(self.bills.paid[0]["item_code"], "AT099")

    def test_electricity_has_a_minimum(self):
        outcome = self.gateway().buy(ELECTRICITY, 300, "bill_req1")
        self.assertEqual(outcome.status, vending.FAILED)
        self.assertIn("least", outcome.message)
        self.assertEqual(self.bills.paid, [])

    def test_data_buys_its_plan_item(self):
        outcome = self.gateway().buy(DATA, 1_000, "bill_req1")
        self.assertEqual(outcome.status, vending.DELIVERED)
        self.assertEqual(self.bills.paid[0]["item_code"], "MD107")

    def test_a_plan_price_cannot_be_underpaid(self):
        outcome = self.gateway().buy(DSTV, 1_000, "bill_req1")
        self.assertEqual(outcome.status, vending.FAILED)
        self.assertEqual(outcome.code, "plan_price_mismatch")
        self.assertIn("1,800", outcome.message)
        self.assertEqual(self.bills.paid, [])

    def test_a_plan_bill_without_a_plan_is_refused(self):
        outcome = self.gateway().buy({**DSTV, "plan": None}, 1_800, "bill_req1")
        self.assertEqual(outcome.status, vending.FAILED)
        self.assertIn("plan", outcome.message)

    def test_an_unknown_provider_is_refused_not_recorded(self):
        outcome = self.gateway().buy({**AIRTIME, "provider": "Globacom Wireless"}, 500,
                                     "bill_req1")
        self.assertEqual(outcome.status, vending.FAILED)
        self.assertEqual(outcome.vendor, "none")
        self.assertIn("Nothing was charged", outcome.message)

    def test_water_has_no_vendor(self):
        outcome = self.gateway().buy(
            {"id": "bill_water", "kind": "water", "provider": "Lagos Water",
             "label": "Water", "reference": "1234"}, 1_000, "bill_req1")
        self.assertEqual(outcome.status, vending.FAILED)

    def test_without_flutterwave_nothing_is_sold(self):
        outcome = vending.VendingGateway(None).buy(AIRTIME, 1_000, "bill_req1")
        self.assertEqual(outcome.status, vending.FAILED)
        self.assertEqual(outcome.code, "not_available")

    def test_a_test_key_is_not_live(self):
        self.assertFalse(self.gateway().live)
        self.assertFalse(vending.VendingGateway(None).live)


class PaymentFlowTests(StoreCase):
    def service(self, gateway):
        return self.account.payments(gateway)

    def test_delivered_payment_is_charged_once_with_a_token(self):
        receipt = self.service(self.gateway()).pay(ELECTRICITY, 5_000)
        self.assertEqual(receipt["status"], vending.DELIVERED)
        self.assertTrue(receipt["token"])
        self.assertEqual(receipt["units"], 23.92)
        self.assertEqual(receipt["vendor"], "flutterwave")
        self.assertEqual(self.store.wallet(), {"balance_ngn": 59_200, "spent_ngn": 17_400})

    def test_pending_payment_holds_the_balance_but_is_not_spent(self):
        receipt = self.service(self.gateway("pending")).pay(ELECTRICITY, 5_000)
        self.assertEqual(receipt["status"], vending.PENDING)
        self.assertIsNone(receipt["token"])
        self.assertEqual(self.store.wallet(), {"balance_ngn": 59_200, "spent_ngn": SEED_SPENT})

    def test_a_held_balance_cannot_be_spent_twice(self):
        self.store.set_wallet(6_000, SEED_SPENT)
        service = self.service(self.gateway("pending"))
        service.pay(ELECTRICITY, 5_000)
        with self.assertRaises(payment_service.SpendError) as caught:
            service.pay(AIRTIME, 1_500)
        self.assertEqual(caught.exception.code, payment_service.INSUFFICIENT_BALANCE)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.wallet()["balance_ngn"], 1_000)

    def test_failed_payment_is_not_charged_and_is_recorded(self):
        with self.assertRaises(payment_service.SpendError) as caught:
            self.service(self.gateway("failed")).pay(ELECTRICITY, 5_000)
        self.assertEqual(caught.exception.code, payment_service.VENDOR_FAILED)
        self.assertEqual(self.store.wallet()["balance_ngn"], SEED_BALANCE)
        self.assertEqual(self.store.recent()[0]["status"], vending.FAILED)

    def test_a_metered_delivery_without_a_token_is_not_charged(self):
        class NoToken:
            def buy(self, bill, amount, request_id):
                return vending.VendingOutcome(
                    status=vending.DELIVERED, token=None, token_required=True
                )

            def requery(self, request_id, amount, *, token_required):
                raise AssertionError("should not be requeried yet")

        receipt = self.service(NoToken()).pay(ELECTRICITY, 5_000)
        self.assertEqual(receipt["status"], vending.PENDING)
        self.assertEqual(self.store.wallet()["spent_ngn"], SEED_SPENT)

    def test_a_retried_electricity_purchase_needs_its_token_before_charging(self):
        class Client:
            extra = None

            def bill_status(self, reference):
                return {"status": "successful", "code": "200", "extra": self.extra}

        client = Client()
        gateway = vending.VendingGateway(client)
        gateway.buy = lambda *_: vending.VendingOutcome(status=vending.PENDING,
                                                         vendor_ref="CF-1")
        service = self.service(gateway)
        service.pay(ELECTRICITY, 5_000)

        without_token = service.pay(ELECTRICITY, 5_000)
        self.assertEqual(without_token["status"], vending.PENDING)
        self.assertEqual(self.store.wallet()["spent_ngn"], SEED_SPENT)

        client.extra = "Token: 4821-0937-5512-8846-3019"
        delivered = service.pay(ELECTRICITY, 5_000)
        self.assertEqual(delivered["status"], vending.DELIVERED)
        self.assertEqual(delivered["token"], "4821 0937 5512 8846 3019")
        self.assertIsNotNone(delivered["units"])

    def test_a_purchase_flutterwave_never_answered_waits_then_is_given_up(self):
        gateway = ScriptedGateway([vending.VendingOutcome(status=vending.PENDING)])
        service = self.service(gateway)
        first = service.pay(ELECTRICITY, 5_000)

        self.assertEqual(service.pay(ELECTRICITY, 5_000)["id"], first["id"])
        self.assertEqual(gateway.requeried, [])

        self.account.db.query("UPDATE receipts SET created_at = $2 WHERE id = $1",
                              [first["id"], Clock.ago(minutes=31)])
        with self.assertRaises(payment_service.SpendError):
            service.pay(ELECTRICITY, 5_000)
        self.assertEqual(self.store.wallet()["balance_ngn"], SEED_BALANCE)
        self.assertEqual(self.store.recent()[0]["status"], vending.FAILED)

    def test_retry_reuses_the_request_id_and_charges_once(self):
        gateway = ScriptedGateway(
            [
                vending.VendingOutcome(status=vending.PENDING, code="200", vendor_ref="CF-1"),
                vending.VendingOutcome(status=vending.DELIVERED, token="4821 0937 5512 8846 3019",
                                       vendor_ref="CF-1"),
            ]
        )
        service = self.service(gateway)

        first = service.pay(ELECTRICITY, 5_000)
        self.assertEqual(first["status"], vending.PENDING)
        self.assertEqual(self.store.wallet(), {"balance_ngn": 59_200, "spent_ngn": SEED_SPENT})

        second = service.pay(ELECTRICITY, 5_000)
        self.assertEqual(second["id"], first["id"])  # same receipt, not a new sale
        self.assertEqual(second["status"], vending.DELIVERED)
        self.assertEqual(gateway.requeried, ["CF-1"])
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.wallet(), {"balance_ngn": 59_200, "spent_ngn": 17_400})

    def test_a_second_intent_after_delivery_is_a_new_purchase(self):
        gateway = ScriptedGateway(
            [
                vending.VendingOutcome(status=vending.DELIVERED, token="a"),
                vending.VendingOutcome(status=vending.DELIVERED, token="b"),
            ]
        )
        service = self.service(gateway)
        service.pay(ELECTRICITY, 5_000)
        service.pay(ELECTRICITY, 5_000)
        self.assertEqual(self.store.count(), 2)
        self.assertEqual(gateway.bought[0], gateway.bought[1])  # amount
        self.assertEqual(self.store.wallet()["balance_ngn"], 54_200)

    def test_tv_plan_is_charged_without_a_token(self):
        receipt = self.service(self.gateway()).pay(DSTV, 1_800)
        self.assertEqual(receipt["status"], vending.DELIVERED)
        self.assertIsNone(receipt["token"])
        self.assertEqual(self.store.wallet()["balance_ngn"], 62_400)

    def test_airtime_is_charged(self):
        receipt = self.service(self.gateway()).pay(AIRTIME, 1_000)
        self.assertEqual(receipt["status"], vending.DELIVERED)
        self.assertIsNone(receipt["token"])
        self.assertEqual(self.store.wallet()["balance_ngn"], 63_200)

    def test_a_plan_mismatch_is_never_bought(self):
        bills = FakeBills()
        with self.assertRaises(payment_service.SpendError) as caught:
            self.service(vending.VendingGateway(bills)).pay(DSTV, 5_000)
        self.assertEqual(caught.exception.code, payment_service.VENDOR_FAILED)
        self.assertEqual(bills.paid, [])  # the vendor was never called
        self.assertEqual(self.store.wallet()["balance_ngn"], SEED_BALANCE)

    def gateway(self, outcome="successful"):
        return vending.VendingGateway(FakeBills(outcome))


class CatalogTests(unittest.TestCase):
    """Read against `support.CATALOGUE`, a slice of the real test catalogue."""

    catalog = CATALOG

    def test_airtime_resolves_per_network(self):
        self.assertEqual(self.catalog.product("airtime", "MTN").biller_code, "BIL099")
        self.assertEqual(self.catalog.product("airtime", "GLO").biller_code, "BIL102")
        self.assertEqual(self.catalog.product("airtime", "9mobile").biller_code, "BIL103")
        # The old name for 9mobile still finds it.
        self.assertEqual(self.catalog.product("airtime", "etisalat").biller_code, "BIL103")

    def test_airtime_is_amount_mode_on_the_documented_item(self):
        glo = self.catalog.product("airtime", "Glo")
        self.assertEqual(glo.mode, "amount")
        # Glo lists AT133 first; AT102 is the one numbered like its biller.
        self.assertEqual(glo.item_code, "AT102")

    def test_data_and_tv_are_plan_mode(self):
        for kind, provider in (("data", "MTN"), ("tv", "DStv"), ("tv", "Startimes")):
            with self.subTest(kind=kind, provider=provider):
                self.assertEqual(self.catalog.product(kind, provider).mode, "plan")

    def test_repeated_rows_are_one_plan(self):
        mtn = self.catalog.product("data", "MTN")
        self.assertEqual([plan.code for plan in self.catalog.plans(mtn)], ["MD107", "MD108"])

    def test_electricity_is_ikejas_prepaid_item(self):
        ikeja = self.catalog.product("electricity", "Ikeja Electric")
        self.assertEqual((ikeja.biller_code, ikeja.item_code), ("BIL113", "UB159"))

    def test_every_disco_is_found_by_its_name_or_abbreviation(self):
        for provider, biller in [("Eko Electric", "BIL112"), ("EKEDC", "BIL112"),
                                 ("IKEDC", "BIL113"), ("Port Harcourt Electric", "BIL116"),
                                 ("Jos Electricity", "BIL215"), ("Benin Electric", "BIL140"),
                                 ("BEDC", "BIL140")]:
            with self.subTest(provider=provider):
                self.assertEqual(self.catalog.product("electricity", provider).biller_code,
                                 biller)

    def test_a_disco_is_never_vended_on_another_discos_item(self):
        self.assertIsNone(self.catalog.product("electricity", "Kano Electric"))
        self.assertIsNone(self.catalog.product("electricity", "Electric"))

    def test_plan_prices_come_from_the_catalogue(self):
        dstv = self.catalog.product("tv", "DStv")
        self.assertEqual(self.catalog.plan(dstv, "CB141").price_ngn, 1_800)

    def test_a_biller_code_finds_its_product(self):
        self.assertEqual(self.catalog.product("data", "BIL104").name, "MTN")

    def test_an_unknown_provider_has_no_product(self):
        self.assertIsNone(self.catalog.product("airtime", "Nothing Tel"))
        self.assertIsNone(self.catalog.product("tv", "Showmax"))
        self.assertIsNone(self.catalog.product("water", "Lagos Water"))

    def test_a_plan_that_does_not_exist_is_none(self):
        dstv = self.catalog.product("tv", "DStv")
        self.assertIsNone(self.catalog.plan(dstv, "CB999"))

    def test_with_no_catalogue_nothing_is_sold(self):
        from app.modules.vending.catalog import Catalog

        self.assertEqual(Catalog().products("airtime"), [])


class ScriptedGateway:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.bought: list[int] = []
        self.requeried: list[str] = []

    def buy(self, bill, amount_ngn, request_id):
        self.bought.append(amount_ngn)
        return self.outcomes.pop(0)

    def requery(self, request_id, amount_ngn, *, token_required):
        self.requeried.append(request_id)
        return self.outcomes.pop(0)

    def find(self, request_id, amount_ngn, *, token_required):
        """Flutterwave has no record of a purchase it never answered."""
        return None


def _receipt(
    receipt_id: str,
    *,
    request_id: str,
    status: str = "pending",
    created_at: str = "2026-10-20T00:00:00Z",
    amount_ngn: int = 5_000,
) -> dict:
    return {
        "id": receipt_id,
        "request_id": request_id,
        "bill_id": "bill_home_meter",
        "bill_label": "Home meter",
        "meter": "0101170026583",
        "amount_ngn": amount_ngn,
        "units": 23.92,
        "token": "4821 0937 5512 8846 3019",
        "tx_hash": None,
        "status": status,
        "vendor": "flutterwave",
        "vendor_code": "200",
        "vendor_message": "ok",
        "created_at": created_at,
    }


if __name__ == "__main__":
    unittest.main()
