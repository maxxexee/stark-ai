"""Stark's agent: the model loop, the account snapshot, and tool routing.

The agent takes what the user said, lets a model choose tool calls, runs them under
the owner's rules, and returns a sentence that can be spoken. The pieces:

- `prompt.py` and `tools.py`: what the model is told and may call.
- `model.py`: the NEAR AI client. Without `NEAR_AI_API_KEY` every turn fails and the
  user hears that Stark lost connection; nothing is paid.
- `payment_gate.py`: every rule a payment must pass, in code.
- `payment_intent.py`: a second model call that decides whether the user asked to pay.

The safety property that matters: the gate is enforced in `_run_tool`, not by asking
the model nicely. A model that hallucinates a ₦40,000 payment gets a refusal and no
signature.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.modules.agent import memory
from app.modules.agent.errors import PaymentError, ToolRefusal
from app.modules.agent.model import Model, NearAiModel, ToolCall
from app.modules.agent.payment_gate import PaymentGate, Utterance
from app.modules.agent.payment_intent import PaymentIntentJudge
from app.modules.agent.prompt import SYSTEM_PROMPT
from app.modules.agent.toolbox import Limits, ToolBox
from app.modules.agent.tools import READ_ONLY_TOOLS, TOOLS
from app.modules.bill.dtos.create_bill_dto import CreateBillDto

log = logging.getLogger("stark.agent")

LINK_STARTS = ("http://", "https://", "www.")
# Intent judgments in flight, one per turn, beside that turn's own model call.
_JUDGING = ThreadPoolExecutor(max_workers=8, thread_name_prefix="stark-intent")


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
    # Model attempts that failed and were retried during this turn, oldest first
    # (see `NearAiModel.retries`). Empty on the ordinary turn; non-empty is the
    # only evidence of *why* a slow turn was slow.
    retries: list[dict] = field(default_factory=list)
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
        intent: PaymentIntentJudge,
        max_turns: int = 5,
        threads: memory.Threads | None = None,
    ):
        self.model = model
        self.toolbox = toolbox
        self.limits = limits
        self.intent = intent
        self.gate = PaymentGate(toolbox)
        self.max_turns = max_turns
        # What the last few turns of a chat said, when the caller names one. A
        # caller that passes no thread gets exactly the old one-shot behaviour.
        self.threads = threads or memory.Threads()

    @staticmethod
    def _tools_for(has_snapshot: bool) -> list[dict]:
        """The tools this turn offers.

        With a snapshot the read tools are withheld: they carry nothing the snapshot
        does not, and each call is a round trip (measured 2026-10-24, a 1.2s answer
        became 2.5s when the model read what it had already been given). No snapshot
        (the read itself failed) puts every tool back, because a wrong number is
        worse than a slow one. Whether a question may pay is not decided here:
        `pay_bill` asks the intent judge before anything else.
        """
        if not has_snapshot:
            return TOOLS
        return [t for t in TOOLS if t["function"]["name"] not in READ_ONLY_TOOLS]

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
            # The owner's number lives only as the airtime bill's reference, which
            # is why the model used to answer "what's my phone number?" three
            # different ways in one conversation (measured 2026-10-24). Naming it
            # turns a guess into a read. Absent when no airtime bill is saved:
            # there is then nowhere real to get it from, and inventing one is the
            # failure this exists to prevent.
            # An unconfirmed line is not theirs until they say so in the app.
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
        begin = getattr(self.model, "begin_turn", None)
        if callable(begin):
            begin()
        system, has_snapshot = self._system_message()
        history = self.threads.history(thread)
        messages: list[dict] = [system, *history, {"role": "user", "content": transcript}]
        # The intent judge reads the reply before this message: a bare "yes" pays
        # only when Stark has just offered to. Judged on every turn, read only by
        # `pay_bill`: a question costs one unused call, a payment no extra wait.
        stark_said = history[-1]["content"] if history else ""
        said = Utterance(transcript, _JUDGING.submit(self.intent.judge, stark_said, transcript))
        reply = AgentReply(reply="Sorry, I didn't catch that.")
        effect: dict[str, Any] = {}

        try:
            applied = self._drive(messages, reply, effect, has_snapshot, said)
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
        applied.reply = self._without_links(applied.reply)
        # Every path returns this same `reply` object, so the exchange the model
        # actually saw — prompt, account, tool results, answers — is attached once.
        applied.conversation = messages
        seen = getattr(self.model, "retries", None)
        applied.retries = seen() if callable(seen) else []
        # A turn the model never answered is not context; keeping the apology
        # would make the next reply reason about a failure that is already over.
        if thread and applied.code != "model_unavailable":
            self.threads.remember(thread, transcript, applied.reply)
        return applied

    def _drive(self, messages: list[dict], reply: AgentReply, effect: dict,
               has_snapshot: bool, said: Utterance) -> AgentReply:
        """The model loop. Kept separate so one failure can be caught above it."""
        for _ in range(self.max_turns):
            turn = self.model.turn(
                messages, self._tools_for(has_snapshot))
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
                result = self._run_tool(call, effect, said)
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
            # snapshot from before the payment it just made. A read-only call
            # cannot have changed anything, and rebuilding costs several
            # database reads before the next model round can start, so the
            # rebuild is skipped when nothing was written.
            if any(call.name not in READ_ONLY_TOOLS for call in turn.tool_calls):
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
        reply.deposit = effect.get("deposit")
        return reply

    # --- tool routing --------------------------------------------------------

    def _run_tool(self, call: ToolCall, effect: dict[str, Any],
                  said: Utterance) -> dict:
        try:
            if call.name == "get_state":
                return {"ok": True, "data": self.toolbox.get_state()}
            if call.name == "list_bills":
                return {"ok": True, "data": self.toolbox.list_bills()}
            if call.name == "recent_activity":
                return {"ok": True, "data": self.toolbox.recent_activity()}
            if call.name == "pay_bill":
                return self.gate.pay(call.arguments, effect, said, self.limits)
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

    @staticmethod
    def _without_links(text: str) -> str:
        """Every word holding a web link, from the link on, becomes "(link removed)"."""
        pieces: list[str] = []
        word = ""
        for char in text + " ":
            if not char.isspace():
                word += char
                continue
            lowered = word.lower()
            starts = [at for at in (lowered.find(start) for start in LINK_STARTS) if at >= 0]
            pieces.append(word[:min(starts)] + "(link removed)" if starts else word)
            pieces.append(char)
            word = ""
        return "".join(pieces)[:-1]


def build_agent(toolbox: ToolBox, limits: Limits) -> Agent:
    """The account's agent, on NEAR AI. The intent judge shares the model's pool."""
    model = NearAiModel()
    return Agent(model=model, toolbox=toolbox, limits=limits,
                 intent=PaymentIntentJudge(model))
