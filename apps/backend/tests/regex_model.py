"""A deterministic stand-in for NEAR AI, for tests only.

It classifies intent with regexes but emits the same tool-call envelope the real
model does, so the agent loop, the tools and the policy gate under test are the
real ones. It is never used by the app: `build_agent` always builds `NearAiModel`,
and app-level tests swap this in with `support.use_test_model()`.
"""

from __future__ import annotations

import re

from app.modules.agent.agent import (
    ModelTurn,
    ToolCall,
    _loads,
    asks_instead_of_paying,
    parse_amount,
)

# What it proposes when no figure was spoken. Proposing is all it does: the gate
# refuses an unpriced charge, so this never reaches the vendor.
DEFAULT_AMOUNT_NGN = 5_000


_PAY_RE = re.compile(r"\b(top\s*(it\s*)?up|topup|buy|pay|recharge|send)\b")
_BILLS_RE = re.compile(r"\b(my\s+)?bills\b")
# Adding money to the balance, not paying a bill: "fund my wallet with 20k",
# "add 5000 to my balance", "deposit 10k with usdt".
_FUND_RE = re.compile(
    r"\b(?:fund|deposit)\b"
    r"|\b(?:add|top\s*up|load|put)\b.*\b(?:wallet|balance|account|money)\b")
_COIN_RE = re.compile(r"\b(usdt|usdc|btc|eth|sol|near)\b")
_ACTIVITY_RE = re.compile(r"\b(activity|history|recent|last payment|receipts?)\b")
_STATE_RE = re.compile(
    r"\b(balance|unit|units|how much|left|spend|spent|bill)\b"
)
_METER_RE = re.compile(r"\b(light|lights|electric|electricity|meter|nepa|prepaid|units?)\b")
# Naming a product that is not saved must not fall through to whatever is first.
_PRODUCT_RE = re.compile(
    r"\b(data|airtime|tv|cable|dstv|gotv|startimes|showmax|water|internet|subscription)\b"
)


def _label_match(bills: list[dict], heard: str) -> dict | None:
    for bill in bills:
        labels = (bill.get("label", ""), bill.get("provider", ""), bill.get("kind", ""))
        words = {w for label in labels for w in re.findall(r"[a-z]+", label.lower())
                 if len(w) > 2}
        if words and any(word in heard for word in words):
            return bill
    return None


def _choose_bill(bills: list[dict], user_text: str) -> dict | None:
    """Which bill a payment is for, as a careful model would infer it.

    Naming the light or the meter means the electricity bill and nothing else, and
    naming a product that is not saved means **no** bill — paying for something
    else because it happened to be first in the list would be a real mistake.
    """
    if not bills:
        return None
    heard = user_text.lower()
    if _METER_RE.search(heard):
        return next((b for b in bills if b.get("kind") == "electricity"), None)

    matched = _label_match(bills, heard)
    if matched is not None:
        return matched
    if _PRODUCT_RE.search(heard):
        return None
    return bills[0]


def _default_amount(bill: dict) -> int:
    """A plan-priced bill costs what the plan costs, not the sample ₦5,000."""
    price = bill.get("plan_price_ngn")
    return int(price) if isinstance(price, int) and price > 0 else DEFAULT_AMOUNT_NGN


class RegexModel:
    """Deterministic stand-in for NEAR AI.

    It classifies intent with regexes, but everything downstream — tool schema,
    tool routing, the policy gate, the reply payload — is exactly what the real
    model drives. That is the point: the loop is real, only the language model
    is fake.
    """

    name = "regex"

    def turn(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        last = messages[-1]
        user_text = self._last_user_text(messages)

        if last.get("role") == "tool":
            return self._after_tool(last, user_text)

        if last.get("role") != "user":
            return ModelTurn(content="What would you like me to do?")

        heard = user_text.lower()
        if _ACTIVITY_RE.search(heard):
            return ModelTurn(tool_calls=[ToolCall("recent_activity", {})])
        if _FUND_RE.search(heard) and not asks_instead_of_paying(user_text):
            amount = parse_amount(user_text)
            if amount is None:
                return ModelTurn(content="How much would you like to add?")
            coin = _COIN_RE.search(heard)
            return ModelTurn(tool_calls=[ToolCall("add_money", {
                "method": "crypto" if coin or "crypto" in heard else "bank",
                "amount_ngn": amount,
                "asset": coin.group(1).upper() if coin else "",
                "chain": "",
            })])
        if _PAY_RE.search(heard):
            # Read the bill list first, exactly as a careful model would.
            return ModelTurn(tool_calls=[ToolCall("list_bills", {})])
        if _BILLS_RE.search(heard):
            return ModelTurn(tool_calls=[ToolCall("list_bills", {})])
        if _STATE_RE.search(heard):
            return ModelTurn(tool_calls=[ToolCall("get_state", {})])
        return ModelTurn(
            content="I can check your bill or top it up. Which one?"
        )

    @staticmethod
    def _last_user_text(messages: list[dict]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return message.get("content") or ""
        return ""

    def _after_tool(self, message: dict, user_text: str) -> ModelTurn:
        result = _loads(message.get("content"))
        name = message.get("name") or ""

        if name == "list_bills" and _PAY_RE.search(user_text.lower()):
            bills = result.get("data") or []
            if not bills:
                return ModelTurn(content="There are no bills saved yet.")
            chosen = _choose_bill(bills, user_text)
            if chosen is None:
                return ModelTurn(
                    content=(
                        "I don't have a bill saved for that. Add it and I'll pay it "
                        "next time."
                    )
                )
            amount = parse_amount(user_text)
            if amount is None:
                amount = _default_amount(chosen)
            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        "pay_bill",
                        {"bill_id": (chosen or {}).get("id", ""),
                         "amount_ngn": amount},
                    )
                ]
            )

        if name == "get_state":
            data = result.get("data") or {}
            units = data.get("units_left")
            days = data.get("days_left")
            spoken = f"You've got ₦{data.get('balance_ngn', 0):,} in your wallet"
            if units is not None:
                spoken += f" and about {units:g} units left"
                if days is not None:
                    spoken += f", roughly {days} days at this rate"
            return ModelTurn(content=spoken + ".")

        if name == "list_bills":
            bills = result.get("data") or []
            labels = [b.get("label", "a bill") for b in bills]
            if not labels:
                return ModelTurn(content="There are no bills saved yet.")
            joined = ", ".join(labels[:-1]) + f" and {labels[-1]}" if len(labels) > 1 else labels[0]
            return ModelTurn(content=f"You've got {len(labels)} bills set up: {joined}.")

        if name == "recent_activity":
            receipts = result.get("data") or []
            if not receipts:
                return ModelTurn(content="Nothing has been paid yet.")
            latest = receipts[0]
            return ModelTurn(
                content=(
                    f"Your last payment was ₦{latest.get('amount_ngn', 0):,} "
                    f"to {latest.get('bill_label', 'a bill')}."
                )
            )

        if name == "add_money":
            if not result.get("ok"):
                return ModelTurn(content=(result.get("error") or {}).get("message")
                                 or "I couldn't start that. Nothing was taken.")
            data = result.get("data") or {}
            where = "link" if data.get("method") == "bank" else "address"
            return ModelTurn(content=(
                f"Here's how to add ₦{data.get('amount_ngn', 0):,}. The {where} is below "
                "and works for an hour."))

        if name == "pay_bill":
            if not result.get("ok"):
                error = result.get("error") or {}
                return ModelTurn(
                    content=error.get("message") or "That payment didn't go through."
                )
            data = result.get("data") or {}
            amount = data.get("amount_ngn", 0)
            label = data.get("bill_label", "your bill")
            if data.get("status") == "pending":
                return ModelTurn(
                    content=(
                        f"₦{amount:,} for {label} is still going through. "
                        "I'll bring you the token as soon as it lands."
                    )
                )
            if data.get("token"):
                return ModelTurn(
                    content=(
                        f"Done. ₦{amount:,} paid to {label}. "
                        f"Your token is {data['token']}. "
                        "I've put it in your activity too."
                    )
                )
            return ModelTurn(content=f"Done. ₦{amount:,} paid to {label}.")

        return ModelTurn(content="I couldn't do that one. Want to try again?")


