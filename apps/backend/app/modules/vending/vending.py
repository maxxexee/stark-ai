"""Vending: turn a saved bill into the actual purchase, through Flutterwave bills.

| Kind | Flutterwave | Shape |
|---|---|---|
| electricity | every disco's prepaid meter item (see `catalog.DISCOS`) | amount, ₦500 minimum |
| airtime | MTN, Airtel, Glo, 9mobile | amount |
| data | `… DATA BUNDLE` | **plan** (an `MD…` item) |
| tv | DSTV, GOTV, STARTIMES | **plan** (a `CB…` item) |

The two shapes are not interchangeable. Airtime is a number of naira. Data and TV
are a *plan* with a fixed price — so the bill carries a `plan` (the item code) and
the amount must equal that plan's price.

Two rules every purchase keeps:

1. **Delivered means Flutterwave's status read says `successful`.** The payment
   call itself only says the order was taken ("we will first return the pending
   status"), so a status read follows it. Pending is not success, and the caller
   must not charge for it.
2. **A retry never buys again.** It re-reads the purchase by Flutterwave's `tx_ref`,
   saved on the receipt. A purchase that has no `tx_ref` got no answer at all (the
   order call timed out), yet may have been placed, so it is looked up by our own
   `reference` (`find`); `PaymentService` gives it up only when Flutterwave has no
   record of it after a while.

Without Flutterwave configured nothing is sold: the gateway refuses every purchase
with `not_available`, and nothing is charged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.modules.flutterwave.flutterwave import FlutterwaveClient, FlutterwaveError
from app.modules.vending.catalog import AMOUNT, CATALOG, PLAN, Catalog

log = logging.getLogger("stark.vending")

DELIVERED = "delivered"
PENDING = "pending"
FAILED = "failed"

ELECTRICITY_MIN_NGN = 500
TOKEN_RE = re.compile(r"\d{4}(?:[ -]?\d{4}){4}")


@dataclass(frozen=True)
class ProductSpec:
    """What to buy at Flutterwave, and how to check the amount before buying."""

    biller_code: str
    item_code: str
    mode: str
    token_required: bool = False
    min_ngn: int | None = None
    plan_price_ngn: int | None = None


@dataclass(frozen=True)
class VendingOutcome:
    status: str
    token: str | None = None
    units: float | None = None
    vendor: str = "flutterwave"
    code: str = ""
    message: str = ""
    token_required: bool = False
    vendor_ref: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == DELIVERED


class VendingGateway:
    def __init__(self, client: FlutterwaveClient | None, *, tariff_ngn_per_kwh: float = 209.0,
                 catalog: Catalog = CATALOG):
        self.client = client
        self.tariff = tariff_ngn_per_kwh
        self.catalog = catalog

    @property
    def live(self) -> bool:
        """True when purchases reach Flutterwave's live (not test) environment."""
        return self.client is not None and not self.client.test_mode

    # --- resolution ----------------------------------------------------------

    def spec_for(self, bill: dict) -> tuple[ProductSpec | None, str]:
        """`(spec, refusal)`. Exactly one is meaningful."""
        kind = bill["kind"]
        product = self.catalog.product(kind, bill["provider"])
        if product is None:
            return None, (f"I can't find {bill['provider']} for {kind}. "
                          "Nothing was charged.")
        if product.mode == AMOUNT:
            assert product.item_code is not None
            electricity = kind == "electricity"
            return ProductSpec(
                biller_code=product.biller_code, item_code=product.item_code, mode=AMOUNT,
                token_required=electricity,
                min_ngn=ELECTRICITY_MIN_NGN if electricity else None,
            ), ""

        code = bill.get("plan") or ""
        if not code:
            return None, (f"{bill['label']} needs a plan chosen first. "
                          "Nothing was charged.")
        plan = self.catalog.plan(product, code)
        if plan is None:
            return None, (f"I don't have a '{code}' plan for {product.name}. "
                          "Nothing was charged.")
        return ProductSpec(biller_code=product.biller_code, item_code=plan.code, mode=PLAN,
                           plan_price_ngn=plan.price_ngn), ""

    # --- purchase ------------------------------------------------------------

    def buy(self, bill: dict, amount_ngn: int, request_id: str) -> VendingOutcome:
        """Buy for a bill. Never raises for a vendor or plan problem."""
        if self.client is None:
            return VendingOutcome(status=FAILED, vendor="none", code="not_available",
                                  message="Paying bills isn't set up yet. Nothing was charged.")
        spec, refusal = self.spec_for(bill)
        if spec is None:
            return VendingOutcome(status=FAILED, vendor="none", message=refusal)

        problem = _amount_problem(spec, amount_ngn)
        if problem:
            return VendingOutcome(status=FAILED, vendor="none", code=problem[0],
                                  message=problem[1])

        try:
            placed = self.client.pay_bill(
                biller_code=spec.biller_code, item_code=spec.item_code,
                customer_id=_customer_id(bill), amount_ngn=amount_ngn, reference=request_id,
            )
        except FlutterwaveError as err:
            log.warning("bill %s refused by Flutterwave: %s", request_id, err)
            if err.transient:
                # It may have been placed: stay pending and re-read it on the retry.
                return VendingOutcome(status=PENDING, code=str(err.status),
                                      message=err.message,
                                      token_required=spec.token_required)
            return VendingOutcome(status=FAILED, code=str(err.status),
                                  message=_spoken(err.message),
                                  token_required=spec.token_required)
        return self._read(placed["tx_ref"], amount_ngn, spec.token_required,
                          placed.get("recharge_token"))

    def requery(self, vendor_ref: str, amount_ngn: int, *,
                token_required: bool) -> VendingOutcome:
        """Ask Flutterwave about a purchase that came back pending."""
        return self._read(vendor_ref, amount_ngn, token_required)

    def find(self, request_id: str, amount_ngn: int, *,
             token_required: bool) -> VendingOutcome | None:
        """Look up, by our own `reference`, a purchase whose order call got no answer.

        None means Flutterwave has no record of it: a 400 or 404 for the reference,
        or no Flutterwave to ask. Anything else it cannot answer (unreachable, rate
        limited, refused) is pending, because a purchase that may have been placed
        must not be refunded on a guess. A record found is read like any other, and
        the reference becomes the receipt's `vendor_ref` for the next check.
        """
        if self.client is None:
            return None
        try:
            bill = self.client.bill_status(request_id)
        except FlutterwaveError as err:
            if err.status in (400, 404):
                return None
            return VendingOutcome(status=PENDING, code=str(err.status), message=err.message,
                                  token_required=token_required)
        return self._outcome(bill, request_id, amount_ngn, token_required)

    def _read(self, vendor_ref: str, amount_ngn: int, token_required: bool,
              recharge_token: str | None = None) -> VendingOutcome:
        assert self.client is not None
        try:
            bill = self.client.bill_status(vendor_ref)
        except FlutterwaveError as err:
            return VendingOutcome(status=PENDING, code=str(err.status), message=err.message,
                                  token_required=token_required, vendor_ref=vendor_ref)
        return self._outcome(bill, vendor_ref, amount_ngn, token_required, recharge_token)

    def _outcome(self, bill: dict, vendor_ref: str, amount_ngn: int, token_required: bool,
                 recharge_token: str | None = None) -> VendingOutcome:
        """What Flutterwave's status read of one purchase means for the receipt."""
        status = bill["status"].lower()
        if status in ("successful", "success"):
            # Flutterwave's docs name all three places a token can arrive.
            token = (_display_token(recharge_token or bill.get("token") or bill.get("extra"))
                     if token_required else None)
            # Flutterwave does not report units; they are worked out from the tariff.
            units = round(amount_ngn / self.tariff, 2) if token_required else None
            return VendingOutcome(status=DELIVERED, token=token, units=units,
                                  code=bill["code"], token_required=token_required,
                                  vendor_ref=vendor_ref)
        if status in ("failed", "fail", "error"):
            return VendingOutcome(status=FAILED, code=bill["code"],
                                  message="That payment didn't go through. Nothing was charged.",
                                  token_required=token_required, vendor_ref=vendor_ref)
        return VendingOutcome(status=PENDING, code=bill["code"], token_required=token_required,
                              vendor_ref=vendor_ref)


def _amount_problem(spec: ProductSpec, amount_ngn: int) -> tuple[str, str] | None:
    """Check the amount against the product *before* calling the vendor."""
    if spec.mode == PLAN:
        if amount_ngn != spec.plan_price_ngn:
            return ("plan_price_mismatch",
                    f"That plan costs ₦{spec.plan_price_ngn:,}. Nothing was charged.")
        return None
    if spec.min_ngn is not None and amount_ngn < spec.min_ngn:
        return ("bad_amount",
                f"The least you can put on that is ₦{spec.min_ngn:,}. Nothing was charged.")
    return None


def _customer_id(bill: dict) -> str:
    """Flutterwave wants phone numbers as `+234…`; meters and smartcards go as they are."""
    reference = bill["reference"]
    if bill["kind"] in ("airtime", "data") and reference.startswith("0"):
        return "+234" + reference[1:]
    return reference


def _display_token(extra: str | None) -> str | None:
    """Group the 20-digit prepaid token in fours, the way it is printed and read aloud."""
    if not extra:
        return None
    match = TOKEN_RE.search(extra)
    if match is None:
        return extra.strip()
    digits = re.sub(r"\D", "", match.group(0))
    return " ".join(digits[i:i + 4] for i in range(0, 20, 4))


def _spoken(message: str) -> str:
    """Flutterwave's refusal, said the way Stark talks. Its own text is kept for the
    receipt by the caller; this is what the user hears."""
    lowered = message.lower()
    if "insufficient" in lowered or "balance" in lowered:
        return "I can't buy that right now, so nothing was charged. Try again in a few minutes."
    if "customer" in lowered or "invalid" in lowered:
        return "I couldn't find that number. Can you check it? Nothing was charged."
    return "That payment didn't go through. Nothing was charged."
