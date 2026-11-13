"""Stark's agent layer: tools, routing, policy gate and the model loop.

This is M2. The agent takes what the user said, lets a model choose tool calls,
runs them under the vault's rules, and returns a sentence that can be spoken.

One model backend: `NearAiModel`, POSTing to NEAR AI's OpenAI-compatible
`/v1/chat/completions` with `NEAR_AI_API_KEY`. Without a key every turn fails and
the user hears that Stark lost connection; nothing is paid. Tests drive the same
loop with scripted models from `tests/`.

The safety property that matters: the policy gate is enforced in `_run_tool`, not
by asking the model nicely. A model that hallucinates a ₦40,000 payment gets a
refusal and no signature.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import ssl
import threading
import time
import urllib.error
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.modules.agent import memory
from app.modules.agent import policy as policy_rules
from app.modules.bill.dtos.create_bill_dto import CreateBillDto

log = logging.getLogger("stark.agent")

# How long the same charge stays "already done". Measured 2026-10-24: the same
# spoken phrase — "recharge my airtime number" — bought ₦1,000 twice, 29 seconds
# apart, because nothing compared the new attempt with the receipt it had just
# written. Five minutes is long enough to catch a repeat of the same instruction
# and short enough that a deliberate second top-up later in the day is not gated.
DUPLICATE_WINDOW_SECONDS = 300

# The refusals the owner may lift for one payment, by approving it in the app. Kept
# here rather than imported from the approval module, which depends on this one.
OVER_A_LIMIT = frozenset({policy_rules.OVER_PER_PAYMENT_CAP, policy_rules.OVER_CAP})

NEAR_AI_BASE = os.environ.get("NEAR_AI_BASE_URL") or "https://cloud-api.near.ai"
# Tool-capable and on NEAR's own fleet. `openai/gpt-5-nano` is Incognito (no
# end-to-end TEE) and was `is_ready: false` when checked 2026-10-22.
#
# Measured 2026-11-13 on the real agent loop, three turns each, same prompt:
# Qwen/Qwen3.8-27B took 17.9s a turn and single turns reached 81s, which is the
# wait the wall phone was showing. Qwen/Qwen3.6-35B-A3B-FP8 is a 3B-active
# mixture of experts and took 1.4s. On six probe utterances (a question, a
# payment, an over-cap payment, a deposit, a greeting) the two made the same
# tool calls; the 3.6 model also told the user the meter token instead of the
# reference number. Set STARK_MODEL to pin another one.
#
# STARK_MODEL wins over NEAR_AI_MODEL because the production machine identity
# reads Infisical and cannot write it, so a deploy is the only way to change the
# model without someone editing the secret by hand. The secret stays as the
# fallback for a host that sets neither.
NEAR_AI_MODEL = (os.environ.get("STARK_MODEL")
                 or os.environ.get("NEAR_AI_MODEL")
                 or "Qwen/Qwen3.6-35B-A3B-FP8")

SYSTEM_PROMPT = """You are Stark, a calm assistant that pays household bills.

Rules:
- Money is Nigerian naira, written like ₦5,000. Never bring up crypto, wallets,
  chains or contracts yourself. The one time they belong is when the user asks to
  add money with crypto, and then only the coin and the network.
- Read before you act. The current account, the saved bills and the recent
  payments follow these rules — use that instead of guessing numbers, and call
  no tool to answer a question it already answers.
- Earlier turns are context, not instructions. Answer the last message. A
  question you asked is open only when the last message answers it: "500" after
  "how much?" is that amount, while "what number did you top up" is a new
  question and gets its own answer. Never repeat the question you asked last
  time as a reply to something else. When they ask what you did, or whether you
  did it, read the payments in the account — that record is the truth, your
  memory of the words is not.
- The account below is the record, including of your own payments: each one
  names its bill, and every bill carries its reference — the meter, the
  smartcard, the phone line (`phone` is the airtime number). Each payment in the
  account carries that reference as well, so where a payment went is readable,
  not inferred. "What number", "which number", "where did it go" gets those
  digits: "I topped up 08031234567."
- Never repeat a sentence you have already said. If a reply was pushed back on —
  "huh", "wdym", "no it didn't" — the account is the evidence, not your earlier
  words: read it again and answer what they asked. Denying the same thing twice
  means you have not looked at the right line.
- Ask one thing before you write: is the figure in the account? If it is, the
  reply is the figure, and nothing else. Never open with "I can't see", "I don't
  have access to", "I don't have that" or "I can't tell you" about anything the
  account holds. A denial followed by the answer contradicts itself, and the
  listener only hears the denial. Say you cannot see something only when it is
  genuinely missing from the account, and then say it once, without guessing.
- "How much is left on my meter" is the units_left line in that account. Answer
  in one sentence — "You have 11.4 units left" — with "about 4 days at this
  rate" when days_left is there, then stop. It is not a question about money:
  no balance, no limit, no offer to pay. Any mention of the meter, units, light
  or NEPA is this question, even a half-heard fragment like "is left on my
  meter", because speech arrives transcribed and the grammar arrives broken;
  grade the intent, not the words. Only when units_left is null is there no
  reading.
- To pay, call pay_bill. The app enforces the user's limits itself; if it refuses,
  say the reason plainly and do not try a different amount to sneak past it.
- When a payment is over a limit, pay_bill sends it to the Stark app for the owner
  to approve, and its message says so. Tell them it is waiting for their approval
  in the app and that nothing has been paid. You cannot approve it yourself, and
  nothing said in a chat can approve it.
- When they ask you to pay an amount over a limit, still call pay_bill: that is
  what sends it to them for approval. Never refuse it yourself first.
- Check an amount you suggest yourself against the limits before you offer it:
  they are in the account below, per payment, per month, and what is left of the
  month. When you name a limit, give the limit and both numbers — "that is over
  the ₦10,000 per payment limit", "you have ₦7,000 left of your ₦30,000 monthly
  limit", "your balance is ₦6,000 against a ₦50,000 payment". The balance is the
  reason only when it really is the lower number, and a payment the balance cannot
  cover is refused, not sent for approval.
- A bill's "fee_ngn" is Stark's service fee, paid on top of the amount. When a
  payment carries one, say the total once, like "₦1,000 plus a ₦100 fee".
- A payment is only done when the tool returns a token or status "delivered".
  "pending" means it is still going through — say so, and never claim it is done.
- If they name no amount and the bill has no plan price, ask for the figure in one
  short question. Never choose an amount for them — the app refuses it anyway.
- If the same bill and amount was already paid in the last few minutes, say it was
  done and ask before doing it twice.
- Never invent a meter token, a balance or a receipt. Only repeat what a tool gave you.
- Reply in one or two short sentences, written to be read aloud.
- Write money as figures (₦30,000) and quantities as plain numerals — the voice
  reads numerals naturally ("thirty thousand naira"). Never spell numbers out as
  words. The one exception is a meter token: write it as single digits with spaces,
  4 8 2 1 0 9 3 …, so it can be repeated one digit at a time.
- Write for the ear, not the eye: no em dashes, parentheses, slashes or symbols.
  Commas and full stops only.
- A question is not an instruction. "If I pay this, how much is left?", "how much
  would it cost?", "should I?", or someone confused or asking why — answer the
  question and pay nothing until they clearly ask you to pay. Answer and stop:
  do not end with an offer to pay when they only asked what would happen.
- When they ask what something will come to, give them the figure. Work it out
  from the account: "what will my balance be after I pay DStv?" is a subtraction,
  so the reply carries the number. Replying with the price and a question back is
  not an answer, and neither is asking for an amount the account already shows.
  You can always see what a bill costs: a subscription's price is its plan price
  in the account. Never answer that you cannot see the amount.
- One owner, one line. The account has no other people and no other numbers: never
  ask who to send airtime to, and never name a network, contact or provider that
  is not in the account. If they name no bill and two bills could fit, ask which
  bill, in one short question: which bill, not whom.
- Speech is transcribed and can be wrong. If a word looks misheard, work out what it
  must have been from the account and the recent payments. If two readings would pay
  different bills or different amounts, ask one short question instead of acting.
- A subscription is a bill with a plan or a renewal date. "My meter number" is the
  bill's reference; prepaid and postpaid meters are the same field. Read the digits
  you were given, never make any up.
- The account below already carries each bill's plan, price, reference and renewal
  date, plus the last five payments. Never ask for a detail that is already there.
  Never say a payment happened, or when it happened, unless it is in that list.
  It is also the read: pay_bill takes an id straight out of it, so a payment does
  not need a second call to list the bills first.
- `phone` in the account is the owner's own number. Read it out when asked for a
  phone number — it is not a secret, and it is the same digits as the airtime bill.
- For a hypothetical about money, do the arithmetic on the numbers in the account and
  answer with the figure. "If I pay A and top up B, how much is left?" is a
  subtraction, not a request to pay either one.
- You can pay bills, save a new bill, and add money to the balance. Nothing else.
  You cannot send or forward messages, receipts or money to Telegram, email or
  anywhere else, and you cannot withdraw. Say plainly that you cannot do that yet,
  and never imply something was sent.
- To save a bill, call add_bill with the kind, the provider and the reference the
  user gave: the meter number, smartcard number or phone line. Never make up or
  complete a reference. Data and TV are sold as plans, so call find_plans first and
  pass the plan's code; if they did not say which plan, name two or three by price
  and ask. After saving, read the reference back so a misheard digit is caught,
  and say the owner must confirm the new bill in the Stark app before it can be
  paid. A bill marked needs_confirmation cannot be paid until they do.
- To add money, call add_money with the amount and how they want to pay: "bank"
  for bank transfer, card or USSD, or "crypto" with the coin, like USDT, and the
  network when they named one. If they did not say how, ask bank or crypto, in one
  short question. The funding line in the account says which ways are switched on.
- The app shows the payment link or the deposit address right under your reply.
  Never write a link, an address or a crypto amount yourself. Say how much is being
  added, that the link or address is below, and that it works for an hour. Money is
  only added when the deposit says "credited": until then say it has not arrived.
- When the account shows something worth acting on before being asked — units
  or days low, a bill renewing within the week, the monthly limit nearly used —
  end with one short sentence saying so, plainly. Once, not after every reply,
  and only when it is true of the numbers above. If the user already knows or
  has just been told, do not repeat it.
"""

# A question about money, not an instruction to move it. Both models were eager:
# measured 2026-10-24, "if I pay DStv and top up 5 thousand, how much is left?"
# called pay_bill twice and actually topped up ₦5,000 of airtime, and "I'm confused,
# DStv says I owe, what should I do?" tried to pay DStv. Instructions in a prompt are
# not a gate, so the refusal lives here and runs before any amount is even parsed.
_QUESTION_NOT_PAYMENT = re.compile(
    r"\b(?:"
    r"if\s+(?:i|we)\b|what\s+if\b|suppose|supposing|imagine|hypothetically"
    r"|how\s+much\s+(?:would|will)\b|what\s+would\b"
    r"|should\s+i\b|do\s+you\s+think\b"
    r"|i(?:'|\u2019)?m\s+confused|i\s+am\s+confused|i\s+don(?:'|\u2019)?t\s+understand"
    r"|why\s+(?:did|was|is|are|has|have)\b|explain\b"
    r")",
    re.IGNORECASE,
)


# A question *about* the account, as opposed to permission to pay it. "Can you pay
# my DStv?" is a request; "what's my most recent subscription?" is not, but with
# `pay_bill` the only tool offered a model will reach for it — measured 2026-10-24,
# that read question attempted a DStv payment (blocked by the cap, not by sense).
_READ_QUESTION = re.compile(
    r"^\s*(?:what|whats|what's|which|who|when|where|how|read|show|list|tell|explain"
    r"|do\s+i|did\s+i|does|is|are|was|were|can\s+you\s+(?:tell|read|show|see))\b",
    re.IGNORECASE,
)
# The one interrogative shape that *is* a payment request: asking permission.
# "When does my DStv renew" opens like a question and stays one; "can you pay my
# DStv" is the user saying yes in advance, and must still pay.
_PERMISSION = re.compile(
    r"^\s*(?:can|could|would|will)\s+(?:you|u)\s+(?:\w+\s+){0,2}"
    r"(?:pay|top\s*up|topup|buy|renew|recharge|fund|load|purchase)\b",
    re.IGNORECASE,
)
_WAKE = re.compile(r"^\s*(?:hey\s+|ok\s+|okay\s+)?stark[,\s]+", re.IGNORECASE)

# A web link in the model's reply. See `Agent.respond`.
_LINK = re.compile(r"(?:https?://|www\.)\S+", re.I)

# The words that turn a refused repeat into an intended one. The duplicate gate
# below stops the same charge twice in five minutes, but a user who is asked
# "you already did that — still want it?" and answers "again" must not be stuck
# in a loop of their own confirmation. Nothing here is a payment instruction on
# its own; it only ever loosens the duplicate check.
_REPEAT_OK = re.compile(
    r"\b(?:again|one\s+more|twice|second\s+time|second\s+one|confirm(?:ed)?"
    r"|yes|yeah|sure|certainly|do\s+it|go\s+ahead|really|meant\s+it)\b",
    re.IGNORECASE,
)


def asks_instead_of_paying(transcript: str) -> bool:
    """True when the utterance is a question about money, not a request to spend.

    Deliberately conservative in both directions: a hypothetical or an advice
    question can never pay, and neither can a read question with no payment verb.
    A bare "yes" is a confirmation, not a read question, so it still pays — the
    model may have just asked "should I pay the ₦7,900?".
    """
    said = _WAKE.sub("", transcript or "")
    if _QUESTION_NOT_PAYMENT.search(said):
        return True
    if not _READ_QUESTION.search(said):
        return False
    return not _PERMISSION.search(said)


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_state",
            "description": (
                "Read the wallet balance, the monthly limit, how much is spent, and "
                "how many electricity units and days are left. The instructions "
                "already carry this as a current snapshot, so call this only when "
                "the snapshot is missing or a value is not in it."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bills",
            "description": (
                "List the saved bills (electricity, airtime, data, TV, internet, water) "
                "with their ids, labels and references. The snapshot in the "
                "instructions already carries these, so call this only when it is "
                "missing or a bill is not in it."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_activity",
            "description": "The most recent payments, newest first.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pay_bill",
            "description": (
                "Pay a saved bill. Only call this when the user clearly asked to pay. "
                "The amount is in whole naira. If the user did not name an amount, use "
                "the bill's plan price when it has one — otherwise ask them for the "
                "figure instead of choosing it: an unpriced call is refused. A plan "
                "costs its own price. The app checks the user's limits before anything "
                "is charged."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                "bill_id": {
                    "type": "string",
                    "description": (
                        "Id from the saved bills in your instructions. "
                        "Empty means the main electricity meter."
                    ),
                },
                    "amount_ngn": {
                        "type": "integer",
                        "description": "Whole naira, e.g. 5000.",
                    },
                },
                "required": ["amount_ngn"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_plans",
            "description": (
                "The data or TV plans a provider sells, each with its code and price. "
                "Call before saving a data or TV bill, or when asked what plans exist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["data", "tv"]},
                    "provider": {"type": "string",
                                 "description": "MTN, Airtel, Glo, 9mobile, DStv, GOtv…"},
                },
                "required": ["kind", "provider"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_bill",
            "description": (
                "Save a new bill so it can be paid. Only call this when the user asked "
                "to add or save one and gave its reference."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": [
                        "electricity", "airtime", "data", "tv", "internet", "water"]},
                    "provider": {"type": "string", "description": (
                        "The network, TV provider or electricity company, e.g. MTN, "
                        "DStv, Ikeja Electric.")},
                    "reference": {"type": "string", "description": (
                        "Meter number, smartcard number or phone number, exactly as "
                        "the user gave it.")},
                    "label": {"type": "string",
                              "description": "A short name, e.g. Home meter. Optional."},
                    "plan": {"type": "string",
                             "description": "Plan code from find_plans; data and TV only."},
                },
                "required": ["kind", "provider", "reference"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_money",
            "description": (
                "Start adding money to the balance. Bank gives a checkout link for "
                "bank transfer, card or USSD; crypto gives an address to send a coin "
                "to. Nothing is taken until the user pays."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["bank", "crypto"]},
                    "amount_ngn": {"type": "integer",
                                   "description": "Whole naira to add, e.g. 20000."},
                    "asset": {"type": "string",
                              "description": "Crypto only: the coin, e.g. USDT, USDC."},
                    "chain": {"type": "string", "description": (
                        "Crypto only: the network they named, e.g. tron, sol, eth. "
                        "Leave empty if they did not say.")},
                },
                "required": ["method", "amount_ngn"],
                "additionalProperties": False,
            },
        },
    },
]

# Reads the snapshot already carries, so they are not offered when it is present
# (see Agent._tools_for). The definitions stay in TOOLS: a failed snapshot read puts
# every read back in play.
READ_ONLY_TOOLS = frozenset({"get_state", "list_bills", "recent_activity"})
# What a question may still call: a lookup changes nothing, so "what plans does MTN
# have?" can be answered while every tool that spends or saves stays off the table.
LOOKUP_TOOLS = frozenset({"find_plans"})


# --- model interface ---------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }


@dataclass
class ModelTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def assistant_message(self) -> dict:
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [call.as_dict() for call in self.tool_calls],
        }


class Model(Protocol):
    name: str

    def turn(self, messages: list[dict], tools: list[dict]) -> ModelTurn: ...


# --- amount parsing ----------------------------------------------------------


_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def parse_amount(text: str) -> int | None:
    """Pull a naira amount out of what the user said.

    Handles "₦5,000", "5000", "5k", "1.5k" and spoken numbers up to the
    thousands ("five thousand", "two thousand five hundred"). Returns `None`
    when no amount was named, which is the signal to use the default.
    """
    heard = text.lower().replace(",", "").replace("₦", " ").replace("naira", " ")

    suffixed = re.search(r"\b(\d+(?:\.\d+)?)\s*k\b", heard)
    if suffixed:
        return int(round(float(suffixed.group(1)) * 1000))

    digits = re.search(r"\b(\d{1,9})\b", heard)
    if digits:
        return int(digits.group(1))

    words = re.findall(r"[a-z]+", heard)
    total = 0
    current = 0
    seen = False
    for word in words:
        if word in _ONES:
            current += _ONES[word]
            seen = True
        elif word in _TENS:
            current += _TENS[word]
            seen = True
        elif word == "hundred":
            current = max(current, 1) * 100
            seen = True
        elif word == "thousand":
            total += max(current, 1) * 1000
            current = 0
            seen = True
        elif seen and word not in ("and",):
            # A new unrelated word after a number ends the amount.
            break
    amount = total + current
    return amount if seen and amount > 0 else None


def heard_amounts(text: str) -> set[int]:
    """Every naira figure the user said, for checking the one the model chose.

    `parse_amount` keeps only the first, which is right for a default and wrong for
    a check: "home with 5000 and office with 3000" names two payments. Same forms
    as `parse_amount`; each run of spoken number words is one figure.
    """
    heard = text.lower().replace(",", "").replace("₦", " ").replace("naira", " ")
    found = {int(round(float(m) * 1000)) for m in re.findall(r"\b(\d+(?:\.\d+)?)\s*k\b", heard)}
    # Not the halves of a decimal: "1.5k" is ₦1,500, not also ₦1.
    found |= {int(m) for m in re.findall(r"(?<![\d.])\b(\d{1,9})\b(?!\.\d)", heard)}
    total = current = 0
    seen = False
    # A trailing "" closes the last run.
    for word in [*re.findall(r"[a-z]+", heard), ""]:
        if word in _ONES:
            current += _ONES[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word == "thousand":
            total += max(current, 1) * 1000
            current = 0
        elif word == "and" and seen:
            continue
        else:
            if total + current > 0:
                found.add(total + current)
            total = current = 0
            seen = False
            continue
        seen = True
    return found


# --- recency ----------------------------------------------------------------


def _now() -> datetime:
    """The clock, behind a name so a test can pin it without patching time."""
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    """A receipt's `created_at` as aware UTC, or None when it is unreadable.

    Accepts the `Z` suffix the API writes and the offset form the store may
    return. Unreadable is not "old": it returns None and the caller treats the
    receipt as not-recent rather than guessing.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _ago_phrase(seconds: int) -> str:
    """"30 seconds" / "2 minutes" — short enough to be spoken."""
    if seconds < 60:
        return f"{max(seconds, 1)} seconds"
    minutes = round(seconds / 60)
    return f"{minutes} minute" + ("s" if minutes != 1 else "")


# --- spoken phrases ----------------------------------------------------------


def _window_phrase(minutes: int) -> str:
    """How long a request waits, said the way a person would say it."""
    if minutes % 1440 == 0:
        days = minutes // 1440
        return "a day" if days == 1 else f"{days} days"
    if minutes % 60 == 0:
        hours = minutes // 60
        return "an hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minutes"


def _loads(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# --- NEAR AI model -----------------------------------------------------------


class _Connection:
    """One keep-alive HTTPS connection to the model host, and its lock."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.conn = http.client.HTTPSConnection(
            host, port, timeout=timeout, context=ssl.create_default_context()
        )
        self.lock = threading.Lock()


class NearAiModel:
    """NEAR AI's OpenAI-compatible chat endpoint.

    The only model backend. The request/response handling is deliberately narrow:
    one POST, tool calls only. Without a key it is still built, so an account's
    routes work, and every turn fails before any request — the agent turns that
    into a spoken "lost connection" and pays nothing.

    Connections are kept alive and reused. A TLS handshake to the model costs
    0.68s from Lagos (measured 2026-11-13) and a call on an open connection 0.40s,
    so a fresh connection per turn paid that handshake again for every model
    round — twice on any turn that calls a tool. The pool is the same borrow and
    return the database layer uses, for the same reason: the server handles each
    request on a new thread, so a thread-local connection would be a new
    handshake every time.
    """

    name = "near-ai"
    MAX_IDLE = 8

    # The builder's egress drops TLS mid-response: measured 2026-10-24 on
    # geddon.hellostark.xyz, [SSL: UNEXPECTED_EOF_WHILE_READING] arrived on about
    # one turn in 18 and the server handed the client a 500 with nothing to say.
    # A retry costs nothing when the network is healthy and turns a dropped
    # reply into the answer that was asked for.
    ATTEMPTS = 3
    RETRY_DELAYS = (0.3, 0.9)

    def __init__(
        self,
        api_key: str | None = None,
        model: str = NEAR_AI_MODEL,
        base_url: str = NEAR_AI_BASE,
        timeout: int = 30,
    ):
        self.api_key = api_key or os.environ.get("NEAR_AI_API_KEY")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        endpoint = urlsplit(self.base_url)
        self._host = endpoint.hostname or "cloud-api.near.ai"
        self._port = endpoint.port or 443
        self._path = (endpoint.path.rstrip("/") or "") + "/v1/chat/completions"
        self._idle: list[_Connection] = []
        self._mutex = threading.Lock()

    # --- connection ----------------------------------------------------------

    def _acquire(self) -> _Connection:
        with self._mutex:
            if self._idle:
                return self._idle.pop()
        return _Connection(self._host, self._port, self.timeout)

    def _release(self, wire: _Connection) -> None:
        with self._mutex:
            if len(self._idle) < self.MAX_IDLE:
                self._idle.append(wire)
                return
        self._close(wire)

    @staticmethod
    def _close(wire: _Connection) -> None:
        try:
            wire.conn.close()
        except Exception:
            pass

    def turn(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        if not self.api_key:
            raise RuntimeError("NEAR_AI_API_KEY is not set")
        payload = {"model": self.model, "messages": messages, "temperature": 0}
        # A question is offered no tools. Some providers (DeepSeek on NEAR AI) reject
        # `tools: []` with a 400, so the field is left out rather than sent empty.
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        body = self._post(payload)

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("NEAR AI returned no choices")
        message = choices[0].get("message") or {}

        calls = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            calls.append(
                ToolCall(
                    name=function.get("name", ""),
                    arguments=_loads(function.get("arguments")),
                    id=raw.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                )
            )
        return ModelTurn(content=message.get("content"), tool_calls=calls)

    def _post(self, payload: dict) -> dict:
        """One completion, retried only where the failure is the network's.

        A 4xx means the request itself is wrong (bad key, bad shape): retrying
        is just a slower failure, so it raises at once. Everything else — a
        dropped TLS handshake, a reset socket, a body cut in half, 429, 5xx —
        gets `ATTEMPTS` goes before it becomes a real error.

        A pooled connection can be reaped while it sits idle; the retry then
        runs on a fresh one, which is why the borrow happens inside the loop.
        """
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        last: RuntimeError | None = None
        for attempt in range(self.ATTEMPTS):
            wire: _Connection | None = None
            retryable = False
            try:
                wire = self._acquire()
                with wire.lock:
                    wire.conn.request("POST", self._path, body, headers)
                    response = wire.conn.getresponse()
                    status = response.status
                    raw = response.read()
                self._release(wire)
                wire = None
            except (http.client.HTTPException, OSError, urllib.error.URLError) as err:
                # ssl.SSLEOFError, a reset connection, a truncated body.
                if wire is not None:
                    self._close(wire)
                    wire = None
                last, retryable = RuntimeError(f"Could not reach NEAR AI: {err}"), True
            else:
                detail = raw.decode("utf-8", "replace")[:300]
                if status == 429 or status >= 500:
                    last, retryable = RuntimeError(
                        f"NEAR AI returned HTTP {status}: {detail}"), True
                elif status >= 400:
                    raise RuntimeError(f"NEAR AI returned HTTP {status}: {detail}")
                else:
                    try:
                        return json.loads(raw or b"{}")
                    except json.JSONDecodeError as err:
                        last, retryable = RuntimeError(
                            f"Could not reach NEAR AI: {err}"), True
            if not retryable:
                break
            if attempt < self.ATTEMPTS - 1:
                time.sleep(self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)])
        raise last if last else RuntimeError("NEAR AI failed without a reason")


# --- toolbox -----------------------------------------------------------------


class PaymentError(Exception):
    """A payment the app refused or that failed downstream."""

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


class ToolRefusal(Exception):
    """A non-payment action the app refused (a bad reference, a rail switched off).
    Its message is written for the user and goes back to the model as is."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ToolBox(Protocol):
    """What the agent may touch. `AccountToolbox` implements it over one account."""

    def get_state(self) -> dict: ...
    def list_bills(self) -> list[dict]: ...
    def recent_activity(self) -> list[dict]: ...
    # Which ways of adding money are on, and the last few deposits.
    def funding(self) -> dict: ...
    def pay(self, bill_id: str, amount_ngn: int) -> dict: ...
    def add_bill(self, dto: CreateBillDto) -> dict: ...
    def find_plans(self, kind: str, provider: str) -> list[dict]: ...
    # A deposit in `DepositService.shape`: its `pay` is the link or the address.
    def add_money(self, method: str, amount_ngn: int, asset: str, chain: str) -> dict: ...
    # A payment over a limit, filed for the owner to approve in the app. Returns
    # the request with its `window_minutes`.
    def request_approval(self, bill_id: str, amount_ngn: int, reason: str) -> dict: ...
    # An activity row for a payment the rules refused, so the owner can see it.
    def record_refusal(self, bill_id: str, amount_ngn: int, reason: str) -> None: ...


@dataclass(frozen=True)
class Limits:
    """The owner's policy, mirrored from the vault's `get_policy()`."""

    monthly_cap_ngn: int
    per_payment_cap_ngn: int
    allowed_meters: frozenset[str]

    def __post_init__(self) -> None:
        if self.per_payment_cap_ngn > self.monthly_cap_ngn:
            raise ValueError("per-payment cap cannot exceed the monthly cap")


# --- agent -------------------------------------------------------------------


@dataclass
class AgentReply:
    reply: str
    token: str | None = None
    receipt_id: str | None = None
    tx_hash: str | None = None
    code: str | None = None
    actions: list[str] = field(default_factory=list)
    # A deposit `add_money` started, link or address included. The door shows it
    # under the reply, so the model never has to copy an address character by character.
    deposit: dict | None = None
    # What the model was shown and what it said back, in order — the whole
    # exchange, snapshot included, so a strange answer can be judged against
    # the exact words behind it. Read by `turnlog`, never by /v1/voice: that
    # payload is built by hand in `as_voice_payload`.
    conversation: list[dict] = field(default_factory=list)

    def as_voice_payload(self, transcript: str) -> dict:
        """The frozen `/v1/voice` shape. Extra fields are additive."""
        return {
            "transcript": transcript,
            "ignored": False,
            "reply": self.reply,
            "token": self.token,
            "receipt_id": self.receipt_id,
            # Additive (contract rule: additive only).
            "actions": self.actions,
            "tx_hash": self.tx_hash,
            "deposit": self.deposit,
        }


class Agent:
    def __init__(
        self,
        *,
        model: Model,
        toolbox: ToolBox,
        limits: Limits,
        max_turns: int = 5,
        threads: memory.Threads | None = None,
    ):
        self.model = model
        self.toolbox = toolbox
        self.limits = limits
        self.max_turns = max_turns
        # What the last few turns of a chat said, when the caller names one. A
        # caller that passes no thread gets exactly the old one-shot behaviour.
        self.threads = threads or memory.Threads()

    @staticmethod
    def _tools_for(has_snapshot: bool, transcript: str = "") -> list[dict]:
        """The tools this turn offers.

        Three rules, each measured on 2026-10-24:

        - **A question gets lookups only.** With `pay_bill` the only thing on
          offer, gemini-flash-lite called it on "what's my most recent
          subscription", and on "if I pay DStv, how much is left" it paid the
          airtime. Nothing that spends or saves can be called on a turn that does
          not offer it.
        - **With a snapshot, the read tools are withheld.** They carry nothing
          the snapshot does not, and each call is a round trip: a 1.2s answer
          became 2.5s when the model read what it had already been given.
        - **No snapshot** (the read itself failed) puts every tool back, because
          a wrong number is worse than a slow one.
        """
        if not has_snapshot:
            return TOOLS
        if asks_instead_of_paying(transcript):
            return [t for t in TOOLS if t["function"]["name"] in LOOKUP_TOOLS]
        return [t for t in TOOLS
                if t["function"]["name"] not in READ_ONLY_TOOLS]

    def _system_message(self) -> tuple[dict, bool]:
        """The prompt plus what the app already knows, and whether it got it.

        The snapshot is ~2KB, cheaper than a round trip, so a question is
        answered on the first call. Rebuilt after every tool batch so a payment
        never answers from the balance it started with.
        """
        try:
            recent = self.toolbox.recent_activity()
            bills = [self._as_seen(b) for b in self.toolbox.list_bills()]
            # A receipt names its bill, not its destination. On 2026-10-25 the
            # model was asked "what number" straight after a ₦500 airtime
            # top-up and answered "I can't see the number that was topped up" —
            # the digits were in the bill's reference, two joins away, and a
            # model that has already denied something keeps denying it. Copies,
            # so the toolbox's own dicts are never annotated.
            reference_by_id = {b.get("id"): b.get("reference") for b in bills
                               if isinstance(b, dict)}
            payments = []
            for payment in (recent if isinstance(recent, list) else [])[:5]:
                if not isinstance(payment, dict):
                    payments.append(payment)
                    continue
                line = dict(payment)
                reference = reference_by_id.get(line.get("bill_id"))
                if reference:
                    line["reference"] = reference
                payments.append(line)
            snapshot = {
                "state": self.toolbox.get_state(),
                "bills": bills,
                "recent_payments": payments,
            }
            # The owner's number lives only as the airtime bill's reference, which
            # is why the model used to answer "what's my phone number?" three
            # different ways in one conversation (measured 2026-10-24). Naming it
            # turns a guess into a read. Absent when no airtime bill is saved:
            # there is then nowhere real to get it from, and inventing one is the
            # failure this exists to prevent.
            # An unconfirmed line is not theirs until they say so in the app.
            phone = next((str(b.get("reference") or "") for b in bills
                          if isinstance(b, dict) and b.get("kind") == "airtime"
                          and b.get("reference") and not b.get("needs_confirmation")), "")
            if phone:
                snapshot["phone"] = phone
            # The gate's own numbers, so a refusal can be explained before the
            # gate runs. Until 2026-10-24 the model only ever saw these when a
            # tool had already refused, so the one time it never called a tool —
            # "pay ₦50,000 for electricity" — it justified the hold-up with the
            # balance ("your balance is only ₦63,200") instead of the ₦10,000
            # per-payment cap that actually decides it.
            state = snapshot.get("state") or {}
            limits = {
                "monthly_cap_ngn": self.limits.monthly_cap_ngn,
                "per_payment_cap_ngn": self.limits.per_payment_cap_ngn,
            }
            if state.get("remaining_cap_ngn") is not None:
                limits["remaining_cap_ngn"] = int(state["remaining_cap_ngn"])
            elif state.get("cap_ngn") is not None and state.get("spent_ngn") is not None:
                limits["remaining_cap_ngn"] = max(
                    int(state["cap_ngn"]) - int(state["spent_ngn"]), 0
                )
            snapshot["limits"] = limits
            snapshot["funding"] = self.toolbox.funding()
        except Exception:  # a broken read must not cost the answer
            return {"role": "system", "content": SYSTEM_PROMPT}, False
        return ({
            "role": "system",
            "content": SYSTEM_PROMPT + "\n\nCurrent account:\n"
            + json.dumps(snapshot, ensure_ascii=False),
        }, True)

    def respond(self, transcript: str, thread: str | None = None) -> AgentReply:
        """Answer one already-gated utterance, in the context of its chat.

        The wake word check happens in the server, not here — Telegram and the
        wall phone share it there.

        `thread` names the conversation (a chat id, a room). With one, the last
        few exchanges go in front of the new message, which is the difference
        between "which bill would you like to pay 500 for?" and knowing that
        the 500 was the answer to "how much?". Without one, this is the single
        cold turn it has always been.
        """
        system, has_snapshot = self._system_message()
        messages: list[dict] = [system]
        messages.extend(self.threads.history(thread))
        messages.append({"role": "user", "content": transcript})
        reply = AgentReply(reply="Sorry, I didn't catch that.")
        effect: dict[str, Any] = {}

        try:
            applied = self._drive(messages, reply, effect, has_snapshot, transcript)
        except Exception as err:
            # The model is unreachable, timed out, or answered something that is
            # not a turn. The user still gets a sentence: the alternative is a
            # 500 JSON blob the wall phone renders as silence (measured
            # 2026-10-24 — `stub_error: Could not reach NEAR AI`).
            log.warning("agent model failed after %d action(s): %s",
                        len(reply.actions), err)
            # Effects first: whether the sentence may claim a payment went
            # through depends on the receipt, not on the reply's fields yet.
            applied = self._apply_effects(reply, effect)
            applied.reply = self._lost_reply(applied)
            applied.code = applied.code or "model_unavailable"
        # Links reach the user only from the deposit itself (`deposit`), never from
        # the model's words: a link it writes is one something it read put there.
        applied.reply = _LINK.sub("(link removed)", applied.reply)
        # Every path returns this same `reply` object, so the exchange the model
        # actually saw — prompt, account, tool results, answers — is attached once.
        applied.conversation = messages
        # A turn the model never answered is not context; keeping the apology
        # would make the next reply reason about a failure that is already over.
        if thread and applied.code != "model_unavailable":
            self.threads.remember(thread, transcript, applied.reply)
        return applied

    def _drive(self, messages: list[dict], reply: AgentReply, effect: dict,
               has_snapshot: bool, transcript: str) -> AgentReply:
        """The model loop. Kept separate so one failure can be caught above it."""
        for _ in range(self.max_turns):
            turn = self.model.turn(
                messages, self._tools_for(has_snapshot, transcript))
            messages.append(turn.assistant_message())

            if not turn.tool_calls:
                reply.reply = (turn.content or "").strip() or reply.reply
                if not (turn.content or "").strip():
                    # An empty final message, not a hang: measured 2026-10-24 on
                    # google/gemini-2.5-flash-lite, which returns zero tokens
                    # when tools are offered but the answer is already in hand.
                    # Ask once with the tools taken away. A second call is worth
                    # more than telling the user "I didn't catch that" after a
                    # payment already went through.
                    messages.append({
                        "role": "user",
                        "content": "Answer now in one or two sentences, using the results above.",
                    })
                    again = self.model.turn(messages, [])
                    reply.reply = (again.content or "").strip() or reply.reply
                return self._apply_effects(reply, effect)

            results = []
            for call in turn.tool_calls:
                reply.actions.append(call.name)
                result = self._run_tool(call, effect, transcript)
                results.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(result),
                    }
                )
            # The tools may have moved money; the next turn must not read a
            # snapshot from before the payment it just made.
            messages[0], has_snapshot = self._system_message()

        return self._apply_effects(reply, effect)

    @staticmethod
    def _as_seen(bill: dict) -> dict:
        """A bill as the model may read it.

        An unconfirmed bill's label and provider are whatever was said to Stark,
        stored and then read back into every later prompt: a place to plant an
        instruction. Until the owner confirms it, the model sees its kind only.
        """
        if not bill.get("needs_confirmation"):
            return bill
        return {**bill, "label": f"unconfirmed {bill.get('kind')} bill",
                "provider": "unconfirmed"}

    @staticmethod
    def _lost_reply(reply: AgentReply) -> str:
        """A sentence a person can act on, never a stack trace.

        What it may claim follows what is already known: a receipt or a token is
        proof it went through, tools that ran without one are not.
        """
        if reply.token or reply.receipt_id:
            return "That went through. I lost the reply after it, so check your activity."
        if reply.actions:
            return "I lost connection partway. Check your activity before you try again."
        return "Sorry, I lost connection for a second. Say that again?"

    @staticmethod
    def _apply_effects(reply: AgentReply, effect: dict[str, Any]) -> AgentReply:
        reply.token = effect.get("token")
        reply.receipt_id = effect.get("receipt_id")
        reply.tx_hash = effect.get("tx_hash")
        reply.code = effect.get("code")
        reply.deposit = effect.get("deposit")
        return reply

    # --- tool routing --------------------------------------------------------

    def _run_tool(self, call: ToolCall, effect: dict[str, Any],
                  transcript: str = "") -> dict:
        try:
            if call.name == "get_state":
                return {"ok": True, "data": self.toolbox.get_state()}
            if call.name == "list_bills":
                return {"ok": True,
                        "data": [self._as_seen(b) for b in self.toolbox.list_bills()]}
            if call.name == "recent_activity":
                return {"ok": True, "data": self.toolbox.recent_activity()}
            if call.name == "pay_bill":
                return self._pay_bill(call.arguments, effect, transcript)
            if call.name == "find_plans":
                args = call.arguments
                return {"ok": True, "data": self.toolbox.find_plans(
                    str(args.get("kind") or ""), str(args.get("provider") or ""))}
            if call.name == "add_bill":
                return {"ok": True,
                        "data": self.toolbox.add_bill(CreateBillDto(**call.arguments))}
            if call.name == "add_money":
                return self._add_money(call.arguments, effect)
            return {"ok": False, "error": {"code": "unknown_tool",
                                           "message": f"Unknown tool {call.name}",
                                           "detail": {}}}
        except ToolRefusal as err:
            return {"ok": False,
                    "error": {"code": err.code, "message": err.message, "detail": {}}}
        except PaymentError as err:
            effect["code"] = err.code
            return {"ok": False,
                    "error": {"code": err.code, "message": err.message,
                              "detail": err.detail}}
        except Exception:  # a tool must never take the agent down
            # Logged in full here; the model only learns that it failed, so a
            # database or provider message is never read out to the user.
            log.exception("agent tool %s failed", call.name)
            return {"ok": False,
                    "error": {"code": "tool_error",
                              "message": "That didn't work just now. Nothing was charged.",
                              "detail": {}}}

    def _pay_bill(self, arguments: dict, effect: dict[str, Any],
                  transcript: str = "") -> dict:
        """The gate. Nothing is signed or charged unless every rule passes."""
        # First gate: did they ask for a payment at all? A question that merely
        # mentions money must never reach the vendor (see _QUESTION_NOT_PAYMENT).
        if asks_instead_of_paying(transcript):
            effect["code"] = "not_a_payment_request"
            return {
                "ok": False,
                "error": {
                    "code": "not_a_payment_request",
                    "message": (
                        "The user asked a question or sounded unsure. Nothing was "
                        "charged. Answer them, then ask before paying anything."
                    ),
                    "detail": {},
                },
            }

        amount = arguments.get("amount_ngn")
        if not isinstance(amount, int) or isinstance(amount, bool):
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                return {"ok": False,
                        "error": {"code": "bad_amount",
                                  "message": policy_rules.MESSAGES["bad_amount"],
                                  "detail": {}}}

        bills = self.toolbox.list_bills()
        bill = None
        bill_id = arguments.get("bill_id") or ""
        if bill_id:
            bill = next((b for b in bills if b.get("id") == bill_id), None)
        if bill is None:
            bill = next((b for b in bills if b.get("kind") == "electricity"), None)
        if bill is None:
            return {"ok": False,
                    "error": {"code": "unknown_bill",
                              "message": "I don't have that bill saved.",
                              "detail": {"bill_id": bill_id}}}

        # A bill this agent saved is not payable until its owner confirms it in the
        # app: a voice in the room must not be able to name a number and pay it.
        if bill.get("needs_confirmation"):
            effect["code"] = "bill_unconfirmed"
            return {
                "ok": False,
                "error": {
                    "code": "bill_unconfirmed",
                    "message": (
                        f"That {bill.get('kind')} bill is saved but not confirmed. "
                        "Confirm it in the Stark app, then I can pay it. Nothing was "
                        "charged."
                    ),
                    "detail": {"bill_id": bill.get("id")},
                },
            }

        # A plan is sold at its own price. Refuse a mispriced attempt before it can
        # reach the vendor, so the user hears the real number.
        plan_price = bill.get("plan_price_ngn")
        if isinstance(plan_price, int) and amount != plan_price:
            effect["code"] = "plan_price_mismatch"
            return {
                "ok": False,
                "error": {
                    "code": "plan_price_mismatch",
                    "message": (
                        f"{bill.get('label', 'That bill')} costs ₦{plan_price:,}. "
                        "Nothing was charged."
                    ),
                    "detail": {"amount_ngn": amount, "plan_price_ngn": plan_price},
                },
            }

        # Two more gates, both about the user's agreement rather than the
        # account's limits — so they run before the policy check.

        # 1. A figure nobody said is a figure nobody agreed to. A plan costs its
        #    own price (checked just above), so only an amount-priced top-up can
        #    reach here unpriced — and that is exactly where a model picks the
        #    number for the user: measured 2026-10-24, "recharge my airtime
        #    number" bought ₦1,000 twice, 29 seconds apart.
        #    The figure must also be one they said, not merely some figure: "pay
        #    500" must never let the model choose ₦5,000.
        heard = heard_amounts(transcript)
        if not heard and not isinstance(plan_price, int):
            effect["code"] = "amount_required"
            return {
                "ok": False,
                "error": {
                    "code": "amount_required",
                    "message": (
                        "How much would you like me to pay? Nothing has been "
                        "charged yet."
                    ),
                    "detail": {"bill_id": bill.get("id")},
                },
            }
        if not isinstance(plan_price, int) and amount not in heard:
            effect["code"] = "amount_mismatch"
            return {
                "ok": False,
                "error": {
                    "code": "amount_mismatch",
                    "message": (
                        "That is not the amount the user said. Pay exactly what they "
                        "said, or ask. Nothing has been charged."
                    ),
                    "detail": {"amount_ngn": amount, "heard_ngn": sorted(heard)},
                },
            }

        # 2. The same bill, the same amount, minutes ago — delivered or still
        #    pending. Seeded history is skipped: it is artboard data, not
        #    something Stark did just now.
        age = self._just_paid(bill.get("id"), amount)
        if age is not None and not _REPEAT_OK.search(transcript):
            effect["code"] = "duplicate_payment"
            return {
                "ok": False,
                "error": {
                    "code": "duplicate_payment",
                    "message": (
                        f"₦{amount:,} for {bill.get('label', 'that bill')} already "
                        f"went through {_ago_phrase(age)} ago. Nothing has been "
                        "charged. Say it again if you meant a second one."
                    ),
                    "detail": {"amount_ngn": amount, "seconds_ago": age},
                },
            }

        state = self.toolbox.get_state()
        meter = str(bill.get("reference") or "")
        rejection = policy_rules.check_payment(
            paused=bool(state.get("paused")),
            monthly_cap_ngn=self.limits.monthly_cap_ngn,
            per_payment_cap_ngn=self.limits.per_payment_cap_ngn,
            spent_this_period_ngn=int(state.get("spent_ngn") or 0),
            balance_ngn=int(state.get("balance_ngn") or 0),
            amount_ngn=amount + int(bill.get("fee_ngn") or 0),
            meter_allowed=meter in self.limits.allowed_meters,
        )
        # One request is one payment as far as the per-payment cap goes. Measured
        # 2026-11-03: asked for ₦15,000 against a ₦10,000 cap, the model paid
        # ₦10,000 and then ₦5,000 to the same bill. What this request already
        # paid that bill counts toward the cap, so the split goes for approval.
        paid_to: dict[str, int] = effect.setdefault("paid_to", {})
        already = paid_to.get(bill["id"], 0)
        if (rejection is None and already
                and already + amount > self.limits.per_payment_cap_ngn):
            rejection = policy_rules.Rejection(
                policy_rules.OVER_PER_PAYMENT_CAP,
                {"amount_ngn": already + amount,
                 "cap_ngn": self.limits.per_payment_cap_ngn},
            )
        if rejection is not None:
            effect["code"] = rejection.code
            error = rejection.as_dict()
            if rejection.code in OVER_A_LIMIT:
                request = self.toolbox.request_approval(bill["id"], amount, rejection.code)
                error["message"] = (
                    f"{rejection.message} I've sent it to the Stark app for you to "
                    "approve. Nothing is paid unless you approve it within "
                    f"{_window_phrase(request['window_minutes'])}."
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

    def _add_money(self, arguments: dict, effect: dict[str, Any]) -> dict:
        """Start a deposit. The model sees what to tell the user, not the link or the
        address: those travel on the reply, straight from the deposit, to the door."""
        deposit = self.toolbox.add_money(
            str(arguments.get("method") or ""), int(arguments.get("amount_ngn") or 0),
            str(arguments.get("asset") or ""), str(arguments.get("chain") or ""))
        effect["deposit"] = deposit
        told = {"amount_ngn": deposit["amount_ngn"], "method": deposit["method"],
                "status": deposit["status"], "expires_at": deposit["expires_at"],
                "shown_to_user": "the link" if deposit["method"] == "bank"
                else "the address and exact amount"}
        if deposit["method"] == "crypto":
            told["asset"] = deposit["pay"]["asset"]
            told["chain"] = deposit["pay"]["chain"]
        return {"ok": True, "data": told}

    def _just_paid(self, bill_id: Any, amount: int) -> int | None:
        """Seconds since this exact charge was already made, or None.

        The repeat guard for the same instruction twice in a row. Only a real
        purchase counts: same bill, same figure, delivered or pending, inside
        `DUPLICATE_WINDOW_SECONDS`. A seeded entry (`seed-*`), a declined attempt
        or a receipt with no readable timestamp is not "just now" — each of
        those would block a first payment that has nothing to be a repeat of.

        A read, not a model call: `recent_activity` is the local store.
        """
        try:
            recent = self.toolbox.recent_activity() or []
        except Exception:
            return None                  # no history to compare against
        now = _now()
        for entry in recent:
            if not isinstance(entry, dict):
                continue
            if entry.get("bill_id") != bill_id or entry.get("amount_ngn") != amount:
                continue
            if entry.get("status") not in ("delivered", "pending"):
                continue
            if str(entry.get("request_id") or "").startswith("seed-"):
                continue
            when = _parse_ts(entry.get("created_at"))
            if when is None:
                continue
            age = (now - when).total_seconds()
            if 0 <= age <= DUPLICATE_WINDOW_SECONDS:
                return int(age)
        return None


def build_agent(toolbox: ToolBox, limits: Limits) -> Agent:
    """The account's agent, on NEAR AI."""
    return Agent(model=NearAiModel(), toolbox=toolbox, limits=limits)
