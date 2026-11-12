"""turnlog — the conversation log, and the handlers that write to it.

Two layers, because a log nobody actually emits is not a log:

  * **The module**: the entry shapes, the files it writes, and the rule that a
    failing log never fails the request it is watching.
  * **The wire**: `server.h_voice` and `server.h_speak` append a line for every
    exit — answered, asleep, unheard — with the stage timings a person reads
    afterwards. The agent and the synthesiser are faked, so no model call is
    made and no state moves: only the logging is under test.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.modules.turnlog import turnlog
from app.modules.agent.agent import AgentReply
from tests.regex_model import RegexModel


class EntryShapeTests(unittest.TestCase):
    def test_turn_carries_what_the_agent_did(self) -> None:
        entry = turnlog.turn(
            outcome="answered", heard="hello stark pay 5000", said="Stark, pay 5000",
            reply="Paid.", actions=["pay_bill"], receipt_id="r_1", token="4821",
            speak=False, model="google/gemini-2.5-flash-lite",
            ms={"total": 900, "agent": 800},
        )
        self.assertEqual(entry["kind"], "turn")
        self.assertEqual(entry["outcome"], "answered")
        self.assertEqual(entry["actions"], ["pay_bill"])
        self.assertEqual(entry["receipt_id"], "r_1")
        self.assertFalse(entry["speak_requested"])
        self.assertEqual(entry["ms"]["agent"], 800)

    def test_turn_defaults_are_empty_not_missing(self) -> None:
        entry = turnlog.turn(outcome="asleep")
        self.assertEqual(entry["heard"], "")
        self.assertIsNone(entry["said"])
        self.assertEqual(entry["actions"], [])
        self.assertEqual(entry["ms"], {})

    def test_turn_records_where_it_came_from(self) -> None:
        entry = turnlog.turn(outcome="answered", channel="telegram")
        self.assertEqual(entry["channel"], "telegram")
        # Absent, not empty, on anything written before the channel existed.
        self.assertNotIn("channel", turnlog.turn(outcome="answered"))

    def test_speak_records_what_the_voice_was_given(self) -> None:
        entry = turnlog.speak(text="You have ₦64,200.", ms=420, reason="ok",
                              stream=True, provider="elevenlabs")
        self.assertEqual(entry["kind"], "speak")
        # The words on screen keep the sign; the provider gets the spoken form.
        self.assertEqual(entry["spoken"], "You have 64,200 naira.")
        self.assertEqual(entry["text"], "You have ₦64,200.")
        self.assertTrue(entry["stream"])
        self.assertEqual(entry["ms"], 420)


class RecordingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"STARK_TURN_LOG": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = Path(self.tmp.name)

    def test_records_one_json_line_per_call(self) -> None:
        turnlog.record(turnlog.turn(outcome="answered", heard="hello stark"))
        turnlog.record(turnlog.turn(outcome="asleep", heard="what time is it"))
        entries = turnlog.lines(self.folder)
        self.assertEqual([e["outcome"] for e in entries], ["answered", "asleep"])
        self.assertTrue(all(e["ts"] for e in entries))
        self.assertTrue(all(e["kind"] == "turn" for e in entries))

    def test_clip_is_saved_beside_the_log_and_referenced(self) -> None:
        clip = b"RIFF" + b"\x00" * 32
        turnlog.record(turnlog.turn(outcome="answered"), clip=clip,
                       mime="audio/webm;codecs=opus")
        entry = turnlog.lines(self.folder)[0]
        self.assertEqual(entry["mime"], "audio/webm;codecs=opus")
        self.assertEqual(entry["audio_bytes"], len(clip))
        saved = self.folder / entry["audio"]
        self.assertTrue(saved.exists(), entry["audio"])
        self.assertEqual(saved.suffix, ".webm")
        self.assertEqual(saved.read_bytes(), clip)

    def test_unknown_mime_falls_back_to_bin(self) -> None:
        turnlog.record(turnlog.turn(outcome="answered"), clip=b"x", mime="application/x")
        entry = turnlog.lines(self.folder)[0]
        self.assertTrue(entry["audio"].endswith(".bin"))

    def test_lines_survives_a_ragged_file(self) -> None:
        target = self.folder / turnlog.LOG_NAME
        self.folder.mkdir(parents=True, exist_ok=True)
        target.write_text('{"kind": "turn"}\nnot json at all\n\n', encoding="utf-8")
        self.assertEqual([e["kind"] for e in turnlog.lines(self.folder)], ["turn"])

    def test_off_by_default_writes_nothing(self) -> None:
        with mock.patch.dict(os.environ, {"STARK_TURN_LOG": "0"}):
            turnlog.record(turnlog.turn(outcome="answered"))
        self.assertFalse((self.folder / turnlog.LOG_NAME).exists())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(turnlog.enabled())

    def test_flag_1_means_the_default_directory(self) -> None:
        with mock.patch.dict(os.environ, {"STARK_TURN_LOG": "1"}):
            self.assertTrue(turnlog.enabled())
            self.assertEqual(turnlog.log_dir().name, "turns")
            self.assertEqual(turnlog.log_dir().parent,
                             Path(turnlog.__file__).resolve().parents[3] / "logs")

    def test_an_unwritable_target_never_raises(self) -> None:
        # A path that is already a file: `mkdir` will fail on it, which is
        # exactly the kind of failure that must not reach the request.
        blocker = self.folder / "blocked"
        blocker.write_text("x", encoding="utf-8")
        with mock.patch.dict(os.environ, {"STARK_TURN_LOG": str(blocker)}):
            turnlog.record(turnlog.turn(outcome="answered"), clip=b"RIFF")
        self.assertIsNone(turnlog.record(turnlog.turn(outcome="answered")))


class _FakeAgent:
    """Stands in for the built agent: no model call, no state, no network."""

    model = SimpleNamespace(model="test-model", name="fake")

    def __init__(self) -> None:
        self.seen: list[str] = []

    def respond(self, said: str) -> AgentReply:
        self.seen.append(said)
        return AgentReply(
            reply="Your balance is 64,200 naira.",
            # What the model was shown, in order — the entry must keep it.
            conversation=[
                {"role": "system", "content": "You are Stark."},
                {"role": "user", "content": said},
                {"role": "assistant", "content": "Your balance is 64,200 naira."},
            ],
        )


class ServerTurnLogTests(unittest.TestCase):
    """The wire: every exit of `POST /v1/voice` leaves a line behind."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"STARK_TURN_LOG": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)

        from app.modules.voice import tts
        from tests import support as test_support

        # The real app, signed in as a throwaway account whose agent is a fake.
        self.account = test_support.TempAccount(balance_ngn=64_200, spent_ngn=23_000)
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.client = self.api.client
        self.agent = _FakeAgent()
        self.api.state().agent = self.agent
        # `speak: true` is exercised too, so synthesis must not reach a provider.
        tts_patch = mock.patch.object(tts, "synthesize",
                                      return_value=(b"RIFF" + b"\x00" * 8, "ok"))
        tts_patch.start()
        self.addCleanup(tts_patch.stop)
        self.folder = Path(self.tmp.name)

    def test_answered_turn_logs_transcript_reply_and_timings(self) -> None:
        response = self.client.post("/v1/voice", json={
            "transcript_hint": "hello stark what's my balance", "speak": False})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Your balance is 64,200 naira.")
        entry = [e for e in turnlog.lines(self.folder) if e["kind"] == "turn"][0]
        self.assertEqual(entry["outcome"], "answered")
        self.assertEqual(entry["heard"], "hello stark what's my balance")
        self.assertEqual(entry["said"], "hello stark what's my balance")
        self.assertEqual(entry["reply"], "Your balance is 64,200 naira.")
        self.assertEqual(entry["model"], "test-model")
        self.assertFalse(entry["speak_requested"])
        # A missing stage key means "this stage did not run" — no clip, no
        # synthesis — rather than a stage that finished in 0 ms.
        self.assertIn("total", entry["ms"])
        self.assertIn("agent", entry["ms"])
        self.assertNotIn("stt", entry["ms"])
        self.assertNotIn("tts", entry["ms"])
        self.assertNotIn("audio", entry)

    def test_speak_true_records_the_synthesis_time(self) -> None:
        self.client.post("/v1/voice", json={"transcript_hint": "hello stark what's my balance"})
        entry = [e for e in turnlog.lines(self.folder) if e["kind"] == "turn"][0]
        self.assertTrue(entry["speak_requested"])
        self.assertIn("tts", entry["ms"])

    def test_wake_gate_refusal_is_logged_not_silent(self) -> None:
        response = self.client.post("/v1/voice", json={
            "transcript_hint": "tell me a joke", "speak": "false"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ignored"])
        self.assertEqual(self.agent.seen, [])          # the agent was not asked
        entry = [e for e in turnlog.lines(self.folder) if e["kind"] == "turn"][0]
        self.assertEqual(entry["outcome"], "asleep")
        self.assertEqual(entry["heard"], "tell me a joke")
        self.assertIsNone(entry["said"])
        self.assertIsNone(entry["reply"])

    def test_a_failing_log_does_not_fail_the_turn(self) -> None:
        with mock.patch.object(turnlog, "_append", side_effect=OSError("disk full")):
            response = self.client.post("/v1/voice", json={
                "transcript_hint": "hello stark what's my balance", "speak": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Your balance is 64,200 naira.")

    def test_a_telegram_turn_is_written_like_a_voice_turn(self) -> None:
        # Until 2026-10-25 only /v1/voice wrote to the log, so the channel being
        # demoed read back as `count: 0` — the conversation could not be reviewed
        # after the fact at all.
        result = SimpleNamespace(
            reply="I topped up your airtime for ₦1,000.",
            actions=["pay_bill"], code=None, receipt_id="rcpt_9", token=None,
            conversation=[{"role": "user", "content": "top up my airtime"}],
        )
        self.api.module.telegram.log_turn({
            "outcome": "agent", "heard": "top up my airtime",
            "said": "top up my airtime",
            "reply": result.reply, "result": result,
        })

        entry = [e for e in turnlog.lines(self.folder) if e["kind"] == "turn"][0]
        self.assertEqual(entry["channel"], "telegram")
        self.assertEqual(entry["outcome"], "agent")
        self.assertEqual(entry["heard"], "top up my airtime")
        self.assertEqual(entry["actions"], ["pay_bill"])
        self.assertEqual(entry["reply"], "I topped up your airtime for ₦1,000.")
        self.assertEqual(entry["receipt_id"], "rcpt_9")
        # The whole exchange travels with it: "why did it say that" needs the
        # messages, not the sentence.
        self.assertEqual(entry["conversation"][0]["content"], "top up my airtime")

    def test_speak_handler_logs_provider_and_spoken_text(self) -> None:
        response = self.client.post("/v1/speak", json={"text": "You have ₦64,200."})

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["audio"])
        entry = [e for e in turnlog.lines(self.folder) if e["kind"] == "speak"][0]
        self.assertEqual(entry["text"], "You have ₦64,200.")
        self.assertEqual(entry["spoken"], "You have 64,200 naira.")
        self.assertFalse(entry["stream"])
        self.assertEqual(entry["tts"], "ok")
        self.assertEqual(entry["provider"], "elevenlabs")
        self.assertIsInstance(entry["ms"], int)


class ConversationTests(unittest.TestCase):
    """The whole exchange, so "why did it say that" has an answer."""

    def test_entry_carries_the_conversation_when_there_is_one(self) -> None:
        entry = turnlog.turn(
            outcome="answered", heard="hello stark", reply="Paid.",
            conversation=[
                {"role": "system", "content": "You are Stark."},
                {"role": "user", "content": "hello stark"},
            ],
        )
        self.assertEqual([m["role"] for m in entry["conversation"]],
                         ["system", "user"])

    def test_a_turn_the_agent_never_saw_has_no_conversation_key(self) -> None:
        # asleep and unheard turns must not grow an empty list that every
        # reader has to skip.
        for outcome in ("asleep", "unheard"):
            with self.subTest(outcome=outcome):
                self.assertNotIn("conversation", turnlog.turn(outcome=outcome))

    def test_the_conversation_is_copied_not_shared(self) -> None:
        shared = [{"role": "user", "content": "hello"}]
        entry = turnlog.turn(outcome="answered", conversation=shared)
        entry["conversation"][0]["content"] = "rewritten"
        self.assertEqual(shared[0]["content"], "hello")

    def test_agent_replies_carry_the_exchange_they_produced(self) -> None:
        from tests.test_agent import FakeToolbox  # the double lives with the agent tests

        from app.modules.agent import agent as agent_mod
        toolbox = FakeToolbox()
        reply = agent_mod.Agent(
            model=RegexModel(), toolbox=toolbox,
            limits=agent_mod.Limits(monthly_cap_ngn=30_000,
                                    per_payment_cap_ngn=5_000,
                                    allowed_meters=frozenset({"0101170026583"})),
        ).respond("hello stark whats my balance")

        roles = [m["role"] for m in reply.conversation]
        self.assertEqual(roles[0], "system")       # prompt + account snapshot
        self.assertEqual(roles[1], "user")
        self.assertIn("assistant", roles)
        # It must not leak into the frozen /v1/voice shape.
        self.assertNotIn("conversation", reply.as_voice_payload("hello stark"))


class TurnLogEndpointTests(unittest.TestCase):
    """`GET /v1/turnlog` — the log, readable from outside the box."""

    def setUp(self) -> None:
        from tests import support as test_support

        self.account = test_support.TempAccount()
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def turnlog(self, limit: str | None = None) -> tuple[int, dict]:
        response = self.api.client.get(
            "/v1/turnlog", params={} if limit is None else {"limit": limit})
        return response.status_code, response.json()

    def test_off_is_a_404_not_an_empty_log(self) -> None:
        with mock.patch.dict(os.environ, {"STARK_TURN_LOG": "0"}):
            status, payload = self.turnlog()
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], "turnlog_off")

    def test_on_returns_every_line_it_has(self) -> None:
        with mock.patch.dict(os.environ, {"STARK_TURN_LOG": self.tmp.name}):
            turnlog.record(turnlog.turn(outcome="answered", heard="hello stark",
                                        reply="Hi."))
            turnlog.record(turnlog.turn(outcome="asleep", heard="tell me a joke"))
            status, payload = self.turnlog()

        self.assertEqual(status, 200)
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual([e["outcome"] for e in payload["entries"]],
                         ["answered", "asleep"])

    def test_limit_keeps_the_newest(self) -> None:
        with mock.patch.dict(os.environ, {"STARK_TURN_LOG": self.tmp.name}):
            for heard in ("one", "two", "three"):
                turnlog.record(turnlog.turn(outcome="answered", heard=heard))
            status, payload = self.turnlog("1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["entries"][0]["heard"], "three")

    def test_limit_zero_means_the_whole_file(self) -> None:
        with mock.patch.dict(os.environ, {"STARK_TURN_LOG": self.tmp.name}):
            for heard in ("one", "two", "three"):
                turnlog.record(turnlog.turn(outcome="answered", heard=heard))
            _, payload = self.turnlog("0")
        self.assertEqual(payload["count"], 3)

    def test_a_ragged_limit_falls_back_to_the_default(self) -> None:
        with mock.patch.dict(os.environ, {"STARK_TURN_LOG": self.tmp.name}):
            turnlog.record(turnlog.turn(outcome="answered", heard="one"))
            status, payload = self.turnlog("nonsense")
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)

    def test_the_answered_turn_reaches_the_file_with_its_conversation(self) -> None:
        env = mock.patch.dict(os.environ, {"STARK_TURN_LOG": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.api.state().agent = _FakeAgent()

        self.api.client.post("/v1/voice", json={
            "transcript_hint": "hello stark whats my balance", "speak": False})

        entry = [e for e in turnlog.lines(self.folder) if e["kind"] == "turn"][0]
        self.assertEqual([m["role"] for m in entry["conversation"]],
                         ["system", "user", "assistant"])


if __name__ == "__main__":
    unittest.main()
