"""Stark's agent layer: tools, routing, policy gate and the model loop.

This is M2. The agent takes what the user said, lets a model choose tool calls,
runs them under the vault's rules, and returns a sentence that can be spoken.

Two model backends, one loop:

- `FakeModel` — deterministic, no key, no network. Used by the stub server and by
  every test. It decides from regexes, but emits exactly the same tool-call
  envelope a real model does, so the loop, the tools and the policy gate are the
  real thing.
- `NearAiModel` — the real thing, POSTing to NEAR AI's OpenAI-compatible
  `/v1/chat/completions`. Needs `NEAR_AI_API_KEY`. **Not exercised here** — no key
  existed when this was written. Treat its request/response parsing as unproven.

The safety property that matters: the policy gate is enforced in `_run_tool`, not
by asking the model nicely. A model that hallucinates a ₦40,000 payment gets a
refusal and no signature.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app.modules.agent import memory
from app.modules.agent import policy as policy_rules

# What the deterministic model *proposes* when no figure was spoken — ₦5,000 is
# the design's own sample payment and exactly the per-payment cap. Proposing is
# all it does now: `_pay_bill` refuses an unpriced charge (see AMOUNT_REQUIRED
# below), so a number nobody said out loud can never reach the vendor.
DEFAULT_AMOUNT_NGN = 5_000

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
# On NEAR's own fleet (Private TEE) and tool-capable. `openai/gpt-5-nano` is
# Incognito (no end-to-end TEE) and was `is_ready: false` when checked 2026-10-22.
NEAR_AI_MODEL = os.environ.get("NEAR_AI_MODEL") or "Qwen/Qwen3.8-27B"

SYSTEM_PROMPT = """You are Stark, a calm assistant that pays household bills.

Rules:
- Money is Nigerian naira, written like ₦5,000. Never mention crypto, wallets,
  tokens, chains or contracts.
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
- To switch an appliance, call switch_appliance with a device_id from the devices
  in the account. Never invent one. A question about a device, like "is the TV
  on?", is not an instruction: answer it and switch nothing.
- A pronoun is a device. The devices in the account are the only things you can
  switch, so when it lists exactly one, "it", "that" and "the telly" are that
  device and "turn it off", "turn it on", "switch it on", "put it back on" and
  "turn it back on" are all orders to call switch_appliance now. Measured
  failure: with only tv-plug-1 saved, "turn it back on" was answered "which device
  did you want to switch on" instead of switch_appliance(device_id=tv-plug-1,
  on=true). Asking which device when the account holds one is a refusal to do the
  job. Ask which device only when two saved devices could be the one meant.
- Say only what the plug reported. "The TV is on" needs status on and confirmed
  true. Standby means the socket is live but the set is asleep, so say that. If
  the plug did not answer, the TV did not change. When the result says simulated,
  say it was a simulation.
- The devices list carries last_status only when Stark switched it in this
  session. Null means you do not know, and you say so instead of guessing.
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
- You can pay bills and switch the devices saved in the account, and nothing
  else. You cannot send or forward messages, receipts or money to WhatsApp,
  Telegram, email or SMS. Say plainly that you cannot do that yet, and never
  imply something was sent. Switching a saved device is something you can do, so
  never answer a switch order by saying you cannot control it.
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


# A question about a device, not an instruction to switch it. "Is the TV on?"
# must read, never flip the socket: the same failure the payment gate exists for,
# measured on the model that called pay_bill on "what's my recent subscription".
# An imperative is needed (`turn|switch|power|shut|cut` … `on|off`), and a
# sentence that opens as a question keeps its question unless it is asking
# permission ("can you turn it off" is the user saying yes in advance).
_SWITCH_IMPERATIVE = re.compile(
    r"\b(?:turn|switch|power|shut|cut)\b[^.]{0,24}\b(on|off)\b", re.IGNORECASE
)
_SWITCH_ASK = re.compile(
    r"^\s*(?:is|are|was|were|did|does|do|has|have|why|what|whats|what's|how|which"
    r"|show|tell|explain)\b",
    re.IGNORECASE,
)
_SWITCH_PERMISSION = re.compile(
    r"^\s*(?:can|could|would|will)\s+(?:you|u)\b", re.IGNORECASE
)


def asks_instead_of_switching(transcript: str) -> bool:
    """True when the utterance is about a device, not an order to flip it.

    Conservative in both directions: with no imperative switch phrase there is
    nothing to act on ("is the TV on?", "why is the TV off?", "the TV"), and a
    question about the past stays a question even though it contains the verb
    ("did you turn it off?"). Permission still switches.
    """
    said = _WAKE.sub("", transcript or "")
    if not _SWITCH_IMPERATIVE.search(said) and not _PUT_ON.search(said):
        return True
    if _SWITCH_ASK.search(said) and not _SWITCH_PERMISSION.search(said):
        return True
    return False


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
            "name": "list_devices",
            "description": (
                "List the saved devices (a plug, a TV) with their ids, labels and "
                "the last state Stark observed. The instructions already carry "
                "these, so call this only when a device is not in that list."
            ),
            "parameters": {"type": "object", "properties": {},
                           "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_appliance",
            "description": (
                "Turn a saved device's power on or off through its plug. Use a "
                "device_id from the devices in your instructions — never invent "
                "one. Only call this when the user clearly asked to switch it: a "
                "question about a device is not an instruction. The result says "
                "what the plug read back; claim only that."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Id from the devices in your instructions.",
                    },
                    "on": {
                        "type": "boolean",
                        "description": "true to switch it on, false to switch it off.",
                    },
                },
                "required": ["device_id", "on"],
                "additionalProperties": False,
            },
        },
    },
]

# Reads the snapshot already carries, so they are not offered when it is present
# (see Agent._tools_for). The definitions stay in TOOLS: `pay_bill` is the only
# tool the model needs that the prompt cannot answer, and a failed snapshot read
# puts every read back in play.
READ_ONLY_TOOLS = frozenset({"get_state", "list_bills", "recent_activity",
                             "list_devices"})


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


# --- fake model --------------------------------------------------------------


_PAY_RE = re.compile(r"\b(top\s*(it\s*)?up|topup|buy|pay|recharge|send)\b")
_BILLS_RE = re.compile(r"\b(my\s+)?bills\b")
_ACTIVITY_RE = re.compile(r"\b(activity|history|recent|last payment|receipts?)\b")
_STATE_RE = re.compile(
    r"\b(balance|unit|units|how much|left|spend|spent|bill)\b"
)
_METER_RE = re.compile(r"\b(light|lights|electric|electricity|meter|nepa|prepaid|units?)\b")
# Naming a product that is not saved must not fall through to whatever is first.
_PRODUCT_RE = re.compile(
    r"\b(data|airtime|tv|cable|dstv|gotv|startimes|showmax|water|internet|subscription)\b"
)
# A switch, and the thing being switched. Both are needed: "turn it off" names
# no device, and "the TV" on its own is not an order to do anything.
_SWITCH_RE = re.compile(
    r"\b(?:turn|switch|power|shut|cut)\b[^.]{0,24}\b(?:on|off)\b", re.IGNORECASE
)
_DEVICE_RE = re.compile(r"\b(tv|telly|television|plug|device|socket)\b", re.IGNORECASE)
# "turn it back on" names the device the way people actually talk after they have
# just mentioned it. Measured live 2026-11-04: without this, that sentence read as
# no device at all, so the switch was never even offered and Stark asked which one.
_PRONOUN_DEVICE = re.compile(r"\b(?:it|that|this|them)\b", re.IGNORECASE)
# "Put it back on" is how people say it, and `put` is not one of the switch
# verbs. Narrow on purpose — a pronoun or a device, then on/off — because
# "put 500 on my meter" is a payment and must never read as a switch.
_PUT_ON = re.compile(
    r"\bput\s+(?:it|that|this|them|the\s+(?:tv|telly|television|plug|device|socket))"
    r"\s+(?:back\s+)?(on|off)\b",
    re.IGNORECASE,
)
_SWITCH_ON = re.compile(r"\b(on|off)\b", re.IGNORECASE)


def _window_phrase(minutes: int) -> str:
    """How long a request waits, said the way a person would say it."""
    if minutes % 1440 == 0:
        days = minutes // 1440
        return "a day" if days == 1 else f"{days} days"
    if minutes % 60 == 0:
        hours = minutes // 60
        return "an hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minutes"


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


def _choose_device(devices: list[dict], user_text: str) -> dict | None:
    """Which device to switch, or None when the words do not name one.

    Same rule as bills: a label match wins, a single device is unambiguous, and
    two devices with no match is a question rather than a guess.
    """
    if not devices:
        return None
    matched = _label_match(devices, user_text.lower())
    if matched is not None:
        return matched
    return devices[0] if len(devices) == 1 else None


def _default_amount(bill: dict) -> int:
    """A plan-priced bill costs what the plan costs, not the sample ₦5,000."""
    price = bill.get("plan_price_ngn")
    return int(price) if isinstance(price, int) and price > 0 else DEFAULT_AMOUNT_NGN


def _switch_sentence(data: dict) -> str:
    """What a switch may be said to have done, from the plug's own read-back.

    Shared by the model's tool result and the deterministic path below it, so no
    sentence can ever be more confident than the result behind it.
    """
    label = data.get("label", "The device")
    status = data.get("status")
    if not data.get("confirmed"):
        return f"{label} didn't answer, so I can't confirm it changed."
    if status == "on":
        spoken = f"{label} is on."
    elif status == "standby":
        spoken = f"Power's on but {label} is still asleep. Its remote will wake it."
    elif status == "off":
        spoken = f"{label} is off."
    else:
        spoken = f"{label} is {status}."
    if data.get("simulated"):
        spoken += " That was the simulated plug."
    return spoken


class FakeModel:
    """Deterministic stand-in for the LLM.

    It classifies intent with regexes, but everything downstream — tool schema,
    tool routing, the policy gate, the reply payload — is exactly what the real
    model drives. That is the point: the loop is real, only the language model
    is fake.
    """

    name = "fake"

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
        if (_DEVICE_RE.search(heard) or _PRONOUN_DEVICE.search(heard)) and (
                _SWITCH_RE.search(heard) or _PUT_ON.search(heard)
                or _SWITCH_ASK.search(heard)):
            # The device list is what names a device, so read it first, exactly
            # as a careful model would before calling switch_appliance.
            return ModelTurn(tool_calls=[ToolCall("list_devices", {})])
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
                    spoken += f" — roughly {days} days at this rate"
            return ModelTurn(content=spoken + ".")

        if name == "list_devices":
            devices = result.get("data") or []
            chosen = _choose_device(devices, user_text)
            if chosen is None:
                return ModelTurn(content="I don't have that device saved yet.")
            if asks_instead_of_switching(user_text):
                label = chosen.get("label", "the device")
                last = chosen.get("last_status")
                if last is None:
                    return ModelTurn(
                        content=f"I haven't switched {label} yet, so I don't know."
                    )
                spoken = {"on": "on", "off": "off", "standby": "on standby"}[last]
                return ModelTurn(content=f"{label} is {spoken}.")
            wanted = _SWITCH_ON.search(user_text)
            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        "switch_appliance",
                        {"device_id": chosen["id"],
                         "on": bool(wanted and wanted.group(1).lower() == "on")},
                    )
                ]
            )

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
                        f"Done — ₦{amount:,} paid to {label}. "
                        f"Your token is {data['token']}. "
                        "I've put it in your activity too."
                    )
                )
            return ModelTurn(content=f"Done — ₦{amount:,} paid to {label}.")

        if name == "switch_appliance":
            if not result.get("ok"):
                error = result.get("error") or {}
                return ModelTurn(
                    content=error.get("message") or "That didn't work."
                )
            return ModelTurn(
                content=_switch_sentence(result.get("data") or {})
            )

        return ModelTurn(content="I couldn't do that one. Want to try again?")


def _loads(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# --- NEAR AI model -----------------------------------------------------------


class NearAiModel:
    """NEAR AI's OpenAI-compatible chat endpoint.

    Unproven: written from the documented shape, never run with a key. The
    request/response handling is deliberately narrow — one POST, tool calls only.
    """

    name = "near-ai"

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
        if not self.api_key:
            raise ValueError("NEAR_AI_API_KEY is not set")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def turn(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
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
        """
        last: RuntimeError | None = None
        for attempt in range(self.ATTEMPTS):
            request = urllib.request.Request(
                f"{self.base_url}/v1/chat/completions",
                data=json.dumps(payload).encode(),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    return json.loads(resp.read() or b"{}")
            except urllib.error.HTTPError as err:
                try:
                    detail = err.read().decode("utf-8", "replace")[:300]
                finally:
                    err.close()
                message = f"NEAR AI returned HTTP {err.code}: {detail}"
                if not (err.code == 429 or err.code >= 500):
                    raise RuntimeError(message) from err
                last = RuntimeError(message)
            except urllib.error.URLError as err:
                last = RuntimeError(f"Could not reach NEAR AI: {err.reason}")
            except (OSError, json.JSONDecodeError) as err:
                # ssl.SSLEOFError, a reset connection, a truncated body.
                last = RuntimeError(f"Could not reach NEAR AI: {err}")
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


class ToolBox(Protocol):
    """What the agent may touch. `server.py` implements it over its mock state."""

    def get_state(self) -> dict: ...
    def list_bills(self) -> list[dict]: ...
    def recent_activity(self) -> list[dict]: ...
    def pay(self, bill_id: str, amount_ngn: int) -> dict: ...
    def list_devices(self) -> list[dict]: ...
    def switch_appliance(self, device_id: str, on: bool) -> dict: ...
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

        - **A question gets no tools at all.** With `pay_bill` the only thing on
          offer, gemini-flash-lite called it on "what's my most recent
          subscription", and on "if I pay DStv, how much is left" it paid the
          airtime. Nothing can be called on a turn that has nothing to call.
        - **With a snapshot, the read tools are withheld.** They carry nothing
          the snapshot does not, and each call is a round trip: a 1.2s answer
          became 2.5s when the model read what it had already been given.
        - **No snapshot** (the read itself failed) puts every tool back, because
          a wrong number is worse than a slow one.
        """
        if not has_snapshot:
            return TOOLS
        if asks_instead_of_paying(transcript):
            return []
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
            bills = self.toolbox.list_bills()
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
            # A device is named the same way a bill is. `last_status` is what the
            # plug last read back in this session; null means nobody has switched
            # it, which is a fact to say rather than a state to guess.
            try:
                snapshot["devices"] = self.toolbox.list_devices()
            except Exception:
                snapshot["devices"] = []
            # One saved device means a pronoun has an answer, and saying so is
            # what turns "switch it on" into a call. Measured 2026-11-04 against
            # the live model: with only tv-plug-1 saved, "turn it back on" and
            # "switch it on" were answered "which device did you want to switch",
            # because a prompt rule is advice and the account is the record. The
            # note names the device, never its state, so nothing is claimed here
            # that the plug has not read back.
            saved = snapshot["devices"] if isinstance(snapshot["devices"], list) else []
            if len(saved) == 1 and isinstance(saved[0], dict):
                snapshot["note"] = (
                    f"Only one device is saved: {saved[0].get('label')} "
                    f"(device_id {saved[0].get('id')}). Any 'it', 'that' or other "
                    "pronoun in a switch order means this device, so switch it "
                    "instead of asking which one."
                )
            # The owner's number lives only as the airtime bill's reference, which
            # is why the model used to answer "what's my phone number?" three
            # different ways in one conversation (measured 2026-10-24). Naming it
            # turns a guess into a read. Absent when no airtime bill is saved:
            # there is then nowhere real to get it from, and inventing one is the
            # failure this exists to prevent.
            phone = next((str(b.get("reference") or "") for b in bills
                          if isinstance(b, dict) and b.get("kind") == "airtime"
                          and b.get("reference")), "")
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
            # A clear order for the only saved device has to end in a switch, not
            # in the model talking itself out of one. Measured live 2026-11-04:
            # "put it back on" came back "I cannot switch it on without a clear
            # command" with one device saved and nothing left to disambiguate.
            applied = self._do_the_obvious_switch(applied, transcript)
        except Exception as err:
            # The model is unreachable, timed out, or answered something that is
            # not a turn. The user still gets a sentence: the alternative is a
            # 500 JSON blob the wall phone renders as silence (measured
            # 2026-10-24 — `stub_error: Could not reach NEAR AI`).
            print(f"  agent model failed after {len(reply.actions)} action(s): {err}")
            # Effects first: whether the sentence may claim a payment went
            # through depends on the receipt, not on the reply's fields yet.
            applied = self._apply_effects(reply, effect)
            applied.reply = self._lost_reply(applied)
            applied.code = applied.code or "model_unavailable"
        # Every path returns this same `reply` object, so the exchange the model
        # actually saw — prompt, account, tool results, answers — is attached once.
        applied.conversation = messages
        # A turn the model never answered is not context; keeping the apology
        # would make the next reply reason about a failure that is already over.
        if thread and applied.code != "model_unavailable":
            self.threads.remember(thread, transcript, applied.reply)
        return applied

    def _unacted_switch(self, transcript: str) -> dict | None:
        """The switch an unambiguous order asked for, if there is one.

        Only the case with nothing left to reason about: one device saved and an
        imperative switch phrase. Every other reading stays the model's job.
        """
        if asks_instead_of_switching(transcript):
            return None
        said = _WAKE.sub("", transcript or "")
        # A sentence that also names money is not a bare switch: "turn it off and
        # pay my DStv" has to reach the model with both halves intact, or the
        # payment silently disappears behind a switch that did happen.
        if _PAY_RE.search(said) or _BILLS_RE.search(said) or _ACTIVITY_RE.search(said):
            return None
        direction = _PUT_ON.search(said) or _SWITCH_IMPERATIVE.search(said)
        if direction is None:
            return None
        try:
            devices = self.toolbox.list_devices()
        except Exception:
            return None
        if len(devices) != 1 or not isinstance(devices[0], dict):
            return None
        return {
            "device_id": devices[0].get("id", ""),
            "on": direction.group(1).lower() == "on",
        }

    def _do_the_obvious_switch(self, reply: AgentReply, transcript: str) -> AgentReply:
        """Do the order the model only talked about.

        The switch goes through `_switch_appliance`, so it meets the same
        registry check and the same read-back as any other switch — this path
        can refuse or report an unconfirmed plug exactly as the model's can.
        """
        if "switch_appliance" in reply.actions:
            return reply
        arguments = self._unacted_switch(transcript)
        if arguments is None:
            return reply
        try:
            result = self._switch_appliance(arguments, transcript)
        except Exception as err:  # a refusal lands the way a tool call's does
            reply.reply = getattr(err, "message", "") or reply.reply
            return reply
        if not result.get("ok"):
            error = result.get("error") or {}
            reply.reply = error.get("message") or reply.reply
            return reply
        reply.actions.append("switch_appliance")
        reply.reply = _switch_sentence(result.get("data") or {})
        return reply

    def _is_plain_switch(self, transcript: str) -> bool:
        """An order that names a switch and nothing else.

        One saved device, an imperative, and no payment, bill or activity words
        (all of that lives in `_unacted_switch`) — then there is nothing for a
        model to route and nothing for it to word, so the turn is the plug's
        read-back and nothing more.
        """
        return self._unacted_switch(transcript) is not None

    def _drive(self, messages: list[dict], reply: AgentReply, effect: dict,
               has_snapshot: bool, transcript: str) -> AgentReply:
        """The model loop. Kept separate so one failure can be caught above it."""
        # The order is unambiguous, so the switch runs first and the model is
        # never asked: on the demo box a model turn costs 1.3-1.5s of silence
        # that comes *after* the seconds spent waiting for the set to report
        # itself dark, and it can only re-say what the plug already reported.
        if self._is_plain_switch(transcript):
            applied = self._do_the_obvious_switch(reply, transcript)
            messages.append({"role": "assistant", "content": applied.reply})
            return applied
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
            # A switch the plug has already answered is a finished answer, so it
            # is not sent back to the model to be put into words: that costs a
            # round trip of silence (1.1-2.2s measured on the demo box, and a
            # second one when the model replies empty) after a switch that just
            # spent seconds waiting for the set to admit it went dark. The
            # sentence below comes from the same read-back the model would quote.
            if (len(turn.tool_calls) == 1
                    and turn.tool_calls[0].name == "switch_appliance"
                    and results and results[0].get("ok")):
                reply.reply = _switch_sentence(results[0].get("data") or {})
                return self._apply_effects(reply, effect)
            # The tools may have moved money; the next turn must not read a
            # snapshot from before the payment it just made.
            messages[0], has_snapshot = self._system_message()

        return self._apply_effects(reply, effect)

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
        return reply

    # --- tool routing --------------------------------------------------------

    def _run_tool(self, call: ToolCall, effect: dict[str, Any],
                  transcript: str = "") -> dict:
        try:
            if call.name == "get_state":
                return {"ok": True, "data": self.toolbox.get_state()}
            if call.name == "list_bills":
                return {"ok": True, "data": self.toolbox.list_bills()}
            if call.name == "recent_activity":
                return {"ok": True, "data": self.toolbox.recent_activity()}
            if call.name == "pay_bill":
                return self._pay_bill(call.arguments, effect, transcript)
            if call.name == "list_devices":
                return {"ok": True, "data": self.toolbox.list_devices()}
            if call.name == "switch_appliance":
                return self._switch_appliance(call.arguments, transcript)
            return {"ok": False, "error": {"code": "unknown_tool",
                                           "message": f"Unknown tool {call.name}",
                                           "detail": {}}}
        except PaymentError as err:
            effect["code"] = err.code
            return {"ok": False,
                    "error": {"code": err.code, "message": err.message,
                              "detail": err.detail}}
        except Exception as err:  # a tool must never take the agent down
            return {"ok": False,
                    "error": {"code": "tool_error", "message": str(err), "detail": {}}}

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
        if parse_amount(transcript) is None and not isinstance(plan_price, int):
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
            amount_ngn=amount,
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

    def _switch_appliance(self, arguments: dict, transcript: str = "") -> dict:
        """Flip one socket, under two rules: no question acts, no device is invented.

        There is no money here — no wallet row, no receipt, no signature — so
        none of the payment caps apply. What applies is the truth: the result is
        whatever the plug read back, and a plug that did not answer is an error
        the reply has to repeat, never a confident "it's off".
        """
        if asks_instead_of_switching(transcript):
            return {
                "ok": False,
                "error": {
                    "code": "not_a_switch_request",
                    "message": (
                        "The user asked about the device rather than telling you to "
                        "switch it. Nothing was switched. Answer from the account, "
                        "then ask before switching anything."
                    ),
                    "detail": {},
                },
            }

        device_id = str(arguments.get("device_id") or "")
        on = arguments.get("on")
        if not isinstance(on, bool):
            return {
                "ok": False,
                "error": {"code": "bad_switch",
                          "message": "Say on or off. Nothing was switched.",
                          "detail": {}},
            }

        try:
            devices = self.toolbox.list_devices()
        except Exception:
            devices = []
        if not any(d.get("id") == device_id for d in devices):
            return {
                "ok": False,
                "error": {"code": "unknown_device",
                          "message": "I don't have that device saved.",
                          "detail": {"device_id": device_id}},
            }

        # A refusal here (device_unreachable) becomes a PaymentError and lands in
        # `_run_tool`'s handler, so the code and the message reach the reply.
        return {"ok": True, "data": self.toolbox.switch_appliance(device_id, on)}

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
    """Real model when a key is configured, deterministic model otherwise.

    The server calls this, so the key stays a config value and a checkout with no
    key still runs.
    """
    if os.environ.get("NEAR_AI_API_KEY"):
        return Agent(model=NearAiModel(), toolbox=toolbox, limits=limits)
    return Agent(model=FakeModel(), toolbox=toolbox, limits=limits)
