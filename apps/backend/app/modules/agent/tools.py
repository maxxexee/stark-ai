"""The tools the model may call. `Agent._run_tool` routes them; the gates live there."""

from __future__ import annotations

from typing import Any

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
