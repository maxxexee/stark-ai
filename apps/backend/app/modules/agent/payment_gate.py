"""The gate in front of `pay_bill`. Nothing is signed or charged unless every rule passes.

The rules run in code, not in the prompt: a model that ignores every instruction
still cannot pay on a question, pick a figure nobody said, repeat a charge, or go
past the owner's limits.
"""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.modules.agent import policy as policy_rules
from app.modules.agent.payment_intent import PaymentIntent
from app.modules.agent.phrases import Phrases
from app.modules.agent.spoken_amounts import SpokenAmounts
from app.modules.agent.toolbox import Limits, ToolBox

# How long the same charge stays "already done". Measured 2026-10-24: the same
# spoken phrase — "recharge my airtime number" — bought ₦1,000 twice, 29 seconds
# apart, because nothing compared the new attempt with the receipt it had just
# written. Five minutes is long enough to catch a repeat of the same instruction
# and short enough that a deliberate second top-up later in the day is not gated.
DUPLICATE_WINDOW_SECONDS = 300

# The refusals the owner may lift for one payment, by approving it in the app. Kept
# here rather than imported from the approval module, which depends on this one.
OVER_A_LIMIT = frozenset({policy_rules.OVER_PER_PAYMENT_CAP, policy_rules.OVER_CAP})


@dataclass
class Utterance:
    """What the user said this turn, and whether the intent judge read it as an
    instruction to pay. The judgment starts with the turn and runs beside the main
    model call, so a payment does not wait for two model rounds in a row."""

    transcript: str
    intent: Future[PaymentIntent]


def _refusal(code: str, message: str, detail: dict | None = None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "detail": detail or {}}}


class PaymentGate:
    def __init__(self, toolbox: ToolBox) -> None:
        self.toolbox = toolbox

    def pay(self, arguments: dict, effect: dict[str, Any], said: Utterance,
            limits: Limits) -> dict:
        # First: did they ask for a payment at all? A question that merely mentions
        # money must never reach the vendor. A judge that failed raises here, and
        # nothing is charged.
        intent = said.intent.result()
        if intent is PaymentIntent.NOT_PAYMENT:
            effect["code"] = "not_a_payment_request"
            return _refusal("not_a_payment_request", (
                "The user asked a question or sounded unsure. Nothing was "
                "charged. Answer them, then ask before paying anything."))

        amount = arguments.get("amount_ngn")
        if not isinstance(amount, int) or isinstance(amount, bool):
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                return _refusal("bad_amount", policy_rules.MESSAGES["bad_amount"])

        bills = self.toolbox.list_bills()
        bill = None
        bill_id = arguments.get("bill_id") or ""
        if bill_id:
            bill = next((b for b in bills if b.get("id") == bill_id), None)
        if bill is None:
            bill = next((b for b in bills if b.get("kind") == "electricity"), None)
        if bill is None:
            return _refusal("unknown_bill", "I don't have that bill saved.",
                            {"bill_id": bill_id})

        # A plan is sold at its own price. Refuse a mispriced attempt before it can
        # reach the vendor, so the user hears the real number.
        plan_price = bill.get("plan_price_ngn")
        if isinstance(plan_price, int) and amount != plan_price:
            effect["code"] = "plan_price_mismatch"
            return _refusal("plan_price_mismatch", (
                f"{bill.get('label', 'That bill')} costs ₦{plan_price:,}. "
                "Nothing was charged."),
                {"amount_ngn": amount, "plan_price_ngn": plan_price})

        # A figure nobody said is a figure nobody agreed to. A plan costs its own
        # price (checked just above), so only an amount-priced top-up can reach here
        # unpriced, and that is exactly where a model picks the number for the user.
        # The figure must also be one they said: "pay 500" never lets it choose ₦5,000.
        heard = set(SpokenAmounts.figures(said.transcript))
        if not heard and not isinstance(plan_price, int):
            effect["code"] = "amount_required"
            return _refusal("amount_required", (
                "How much would you like me to pay? Nothing has been "
                "charged yet."), {"bill_id": bill.get("id")})
        if not isinstance(plan_price, int) and amount not in heard:
            effect["code"] = "amount_mismatch"
            return _refusal("amount_mismatch", (
                "That is not the amount the user said. Pay exactly what they "
                "said, or ask. Nothing has been charged."),
                {"amount_ngn": amount, "heard_ngn": sorted(heard)})

        # The same bill, the same amount, minutes ago, delivered or still pending.
        age = self._just_paid(bill.get("id"), amount)
        if age is not None and intent is not PaymentIntent.PAY_AGAIN:
            effect["code"] = "duplicate_payment"
            return _refusal("duplicate_payment", (
                f"₦{amount:,} for {bill.get('label', 'that bill')} already "
                f"went through {Phrases.ago(age)} ago. Nothing has been "
                "charged. Say it again if you meant a second one."),
                {"amount_ngn": amount, "seconds_ago": age})

        state = self.toolbox.get_state()
        meter = str(bill.get("reference") or "")
        rejection = policy_rules.check_payment(
            paused=bool(state.get("paused")),
            monthly_cap_ngn=limits.monthly_cap_ngn,
            per_payment_cap_ngn=limits.per_payment_cap_ngn,
            spent_this_period_ngn=int(state.get("spent_ngn") or 0),
            balance_ngn=int(state.get("balance_ngn") or 0),
            amount_ngn=amount + int(bill.get("fee_ngn") or 0),
            meter_allowed=meter in limits.allowed_meters,
        )
        # One request is one payment as far as the per-payment cap goes. Measured
        # 2026-11-03: asked for ₦15,000 against a ₦10,000 cap, the model paid
        # ₦10,000 and then ₦5,000 to the same bill. What this request already
        # paid that bill counts toward the cap, so the split goes for approval.
        paid_to: dict[str, int] = effect.setdefault("paid_to", {})
        already = paid_to.get(bill["id"], 0)
        if (rejection is None and already
                and already + amount > limits.per_payment_cap_ngn):
            rejection = policy_rules.Rejection(
                policy_rules.OVER_PER_PAYMENT_CAP,
                {"amount_ngn": already + amount, "cap_ngn": limits.per_payment_cap_ngn},
            )
        if rejection is not None:
            effect["code"] = rejection.code
            error = rejection.as_dict()
            if rejection.code in OVER_A_LIMIT:
                request = self.toolbox.request_approval(bill["id"], amount, rejection.code)
                error["message"] = (
                    f"{rejection.message} I've sent it to the Stark app for you to "
                    "approve. Nothing is paid unless you approve it within "
                    f"{Phrases.window(request['window_minutes'])}."
                )
                error["detail"]["request_id"] = request["id"]
            else:
                self.toolbox.record_refusal(bill["id"], amount, rejection.message)
            return {"ok": False, "error": error}

        # The vault is signed inside the payment path, so the app's own
        # `POST /v1/payments` is held to the same onchain caps as the agent.
        receipt = self.toolbox.pay(bill["id"], amount)
        paid_to[bill["id"]] = already + amount
        effect["token"] = receipt.get("token")
        effect["receipt_id"] = receipt.get("id")
        effect["tx_hash"] = receipt.get("tx_hash")
        return {"ok": True, "data": receipt}

    def _just_paid(self, bill_id: Any, amount: int) -> int | None:
        """Seconds since this exact charge was already made, or None.

        Only a real purchase counts: same bill, same figure, delivered or pending,
        inside `DUPLICATE_WINDOW_SECONDS`. A seeded entry (`seed-*`), a declined
        attempt or a receipt with no readable timestamp is not "just now": each of
        those would block a first payment that has nothing to be a repeat of.
        """
        try:
            recent = self.toolbox.recent_activity() or []
        except Exception:
            return None                  # no history to compare against
        now = datetime.now(timezone.utc)
        for entry in recent:
            if entry.get("bill_id") != bill_id or entry.get("amount_ngn") != amount:
                continue
            if entry.get("status") not in ("delivered", "pending"):
                continue
            if str(entry.get("request_id") or "").startswith("seed-"):
                continue
            when = self._created_at(entry.get("created_at"))
            if when is None:
                continue
            age = (now - when).total_seconds()
            if 0 <= age <= DUPLICATE_WINDOW_SECONDS:
                return int(age)
        return None

    @staticmethod
    def _created_at(value: Any) -> datetime | None:
        """A receipt's `created_at` as aware UTC. Accepts the `Z` suffix the API
        writes and the offset form the store returns; unreadable is None, not old."""
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
