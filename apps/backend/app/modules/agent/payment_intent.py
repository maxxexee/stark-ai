"""Did the user tell Stark to pay? A second, separate model judgment.

The agent's own model decides which tool to call, and it was eager: measured
2026-10-24, "if I pay DStv and top up 5 thousand, how much is left?" paid ₦5,000 of
airtime, and "I'm confused, DStv says I owe, what should I do?" tried to pay DStv.
A word list cannot cover every way people ask a question, so `pay_bill` asks a model
that has no tools, sees only the last exchange, and answers with one word. Any other
answer is NO: a judgment that cannot be read never pays.
"""

from __future__ import annotations

from enum import Enum

from app.modules.agent.model import Model

PROMPT = """You check one thing for a bill-paying assistant called Stark: does the
user's last message tell Stark to pay a bill now? Reply with exactly one word.

AGAIN: the message asks for a payment again. It says again, another, once more,
twice, or a second time. Or Stark has just said the same payment already went
through and asked if they meant a second one, and they say yes.

PAY: they ask or tell Stark to pay, top up, buy, renew or recharge something,
including asking permission ("can you pay my DStv") and answering yes, or giving
the amount, when Stark has just asked whether or how much to pay. Repeating an
instruction after Stark said it is done is PAY, not AGAIN: Stark checks for
repeats itself.

NO: anything else. A question about the balance, bills, meter or payments. A
question about what something would cost or what would be left ("if I pay DStv,
how much is left?"). Asking for advice ("should I?"). Confusion, a complaint, a
greeting. When unsure, NO."""


class PaymentIntent(Enum):
    PAY = "pay"
    PAY_AGAIN = "pay_again"
    NOT_PAYMENT = "not_payment"


class PaymentIntentJudge:
    """Asks `model`, with no tools on offer, whether an utterance is an instruction."""

    _VERDICTS = {"PAY": PaymentIntent.PAY, "AGAIN": PaymentIntent.PAY_AGAIN}

    def __init__(self, model: Model) -> None:
        self.model = model

    def judge(self, stark_said: str, user_said: str) -> PaymentIntent:
        """`stark_said` is Stark's previous reply in this chat, "" on a cold turn.
        A failed model call raises, and the payment it was checking does not run."""
        turn = self.model.turn([
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": (
                f"Stark said: {stark_said or '(nothing yet)'}\nUser said: {user_said}")},
        ], [])
        # Exactly one verdict word, wherever it sits: "PAY", "Pay.", "NO, a question".
        # Both PAY and NO in one answer is no answer.
        said = {word.strip(".,:;!\"'*").upper() for word in (turn.content or "").split()}
        verdicts = said & {"PAY", "AGAIN", "NO"}
        if len(verdicts) != 1:
            return PaymentIntent.NOT_PAYMENT
        return self._VERDICTS.get(verdicts.pop(), PaymentIntent.NOT_PAYMENT)
