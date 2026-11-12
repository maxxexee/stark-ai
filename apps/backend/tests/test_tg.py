"""M4 tests: the Telegram door, its gates, and the audio path.

Hermetic by design — the agent, file download, transcription
and sending are all injected fakes. The only real dependencies exercised are
`identity_repository.IdentityRepository` (the real Neon Postgres database, read from
`apps/backend/.env`) and, when `ffmpeg` is present,
`audio.transcode` on a WAV this test generates itself. No keys and no model calls —
the one network dependency is the Neon Postgres URL in `apps/backend/.env`.
"""

from __future__ import annotations

import io
import itertools
import os
import tempfile
import time
import unittest
import wave
from unittest import mock
from pathlib import Path

from app.modules.voice import audio
from app.modules.telegram import identity_repository
from app.database import neon
from tests import support as test_support
from app.modules.voice import stt
from app.modules.telegram import telegram
from app.modules.telegram.telegram import TelegramAdapter, TelegramError


def _tiny_wav(seconds: float = 0.05, rate: int = 16000) -> bytes:
    """A valid WAV built in memory — enough for ffmpeg to decode."""
    frames = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


class FakeAgent:
    def __init__(self):
        self.transcripts: list[str] = []
        self.threads: list[str | None] = []
        # Which account each turn was scoped to — the multi-tenant contract.
        self.users: list[str] = []

    def respond(self, user_id: str, said: str, thread: str):
        self.users.append(user_id)
        self.transcripts.append(said)
        self.threads.append(thread)

        class Reply:
            reply = "You've got about 11.4 units left."
            actions = ["pay_bill"]
            code = None
            receipt_id = "rcpt_1"
            token = None
            conversation = [{"role": "user", "content": said}]
        return Reply()


class FakeIdentities(identity_repository.IdentityRepository):
    """The real store, on the real database — test accounts are thrown away after."""

    def __init__(self):
        super().__init__()


# Telegram's dedupe is a primary key, and these tests share one database with every
# other run. A per-process offset keeps the ids unique across runs while staying
# stable within a test, which is what the duplicate tests need.
_RUN_OFFSET = int(time.time() * 1000) % 1_000_000_000
_BASE = _RUN_OFFSET * 10
_SEQ = itertools.count(_BASE)
# Tests that name an id get a range of their own, so `message_id=2` can never
# collide with the second auto-numbered update in the same run.
_EXPLICIT = _BASE + 5_000_000_000

# Every update gets an id of its own unless the test names one, so one test's
# message cannot make the next test's look like a re-delivery. Tests that *want*
# a repeat (the duplicate test) pass the same id twice and still get one.
def _update(chat_id=42, text="hello stark what's left", message_id=None,
            update_id=None, first_name="Tunde", voice=None):
    message_id = next(_SEQ) if message_id is None else _EXPLICIT + message_id
    update_id = next(_SEQ) if update_id is None else _EXPLICIT + update_id
    message = {
        "message_id": message_id,
        "chat": {"id": chat_id},
        "from": {"id": chat_id, "first_name": first_name},
    }
    if text is not None:
        message["text"] = text
    if voice is not None:
        message["voice"] = voice
    return {"update_id": update_id, "message": message}


class AdapterCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Two of the tables behind the chat door are deliberately global (a message
        # id is Telegram's, not an account's). Tests write to the same database the
        # app runs on, so a run has to start those two clean or the next run's first
        # message looks like a re-delivery and its first link attempt looks used up.
        db = neon.open_database()
        db.query("DELETE FROM processed_messages")
        db.query("DELETE FROM link_attempts")

    def setUp(self):
        # A real account, because a link code is a foreign key to one.
        self.account = test_support.TempAccount()
        self.addCleanup(self.account.close)

        self.agent = FakeAgent()
        self.ids = FakeIdentities()
        self.sent: list[tuple[int, str]] = []
        self.turns: list[dict] = []
        self.adapter = TelegramAdapter(
            agent=self.agent,
            identities=self.ids,
            bot_token="123:TEST",
            secret="s3cret",
            owner_user_id=self.account.id,
            send=lambda chat_id, text: self.sent.append((chat_id, text)) or True,
            on_turn=self.turns.append,
            # Voice stays off unless a test turns it on: unit tests never
            # reach for a voice provider, whatever is in the environment.
            speak=lambda text: None,
        )

    def linked(self, chat_id=42):
        code = self.ids.issue_code(self.account.id)
        self.ids.consume_code(code, telegram.CHANNEL, str(chat_id), "Tunde")


class TestWebhookSecret(AdapterCase):
    def test_unconfigured_adapter_refuses_everything(self):
        adapter = TelegramAdapter(agent=self.agent, identities=self.ids)
        self.assertFalse(adapter.enabled)
        with self.assertRaises(TelegramError) as caught:
            adapter.verify_secret("anything")
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(caught.exception.code, "webhook_unconfigured")

    def test_missing_secret_header_is_401(self):
        with self.assertRaises(TelegramError) as caught:
            self.adapter.verify_secret(None)
        self.assertEqual(caught.exception.code, "webhook_unverified")

    def test_wrong_secret_is_401(self):
        with self.assertRaises(TelegramError):
            self.adapter.verify_secret("not-the-secret")

    def test_right_secret_passes(self):
        self.adapter.verify_secret("s3cret")   # no exception


class TestIdentityGate(AdapterCase):
    def test_unlinked_sender_never_reaches_the_agent(self):
        reply = self.adapter._route(_update(text="hello stark pay 5000").get("message"),
                                    "hello stark pay 5000", "42", "Tunde", 42).reply
        # The agent was never called, and the reply is only linking instructions.
        self.assertEqual(self.agent.transcripts, [])
        self.assertIn("do not know this chat", (reply or "").lower())
        self.assertIn("link", (reply or "").lower())
        self.assertNotIn("11.4", (reply or ""))   # no state leaked

    def test_link_then_ask(self):
        self.linked()
        result = self.adapter.handle_update(_update(text="hello stark what's left"))
        self.assertEqual(result["handled"], "agent")
        self.assertEqual(self.agent.transcripts, ["hello stark what's left"])

    def test_link_command_binds_and_rejects_bad_codes(self):
        code = self.ids.issue_code(self.account.id)
        bad = self.adapter._route(_update(text="/link 999999").get("message"),
                                  "/link 999999", "42", None, 42).reply
        self.assertIn("did not work", bad)
        good = self.adapter._route(_update(text=f"/link {code}").get("message"),
                                   f"/link {code}", "42", "Tunde", 42).reply
        self.assertIn("Linked", good)
        self.assertEqual(self.ids.resolve(telegram.CHANNEL, "42"), self.account.id)

    def test_whoami_and_unlink(self):
        self.linked()
        self.assertIn(self.account.id, self.adapter._route(_update(text="/whoami").get("message"),
                                                        "/whoami", "42", None, 42).reply)
        self.adapter._route(_update(text="/unlink").get("message"), "/unlink", "42", None, 42).reply
        self.assertIsNone(self.ids.resolve(telegram.CHANNEL, "42"))

    def test_duplicate_update_is_processed_once(self):
        self.linked()
        self.adapter.handle_update(_update(message_id=7, update_id=7))
        self.adapter.handle_update(_update(message_id=7, update_id=7))
        self.assertEqual(len(self.agent.transcripts), 1)
        self.assertEqual(self.adapter.stats["duplicates"], 1)


class TestLinkCode(AdapterCase):
    """The app half of linking: mint a code, then redeem it from a chat."""

    def _say(self, text: str, chat_id: int = 42):
        return self.adapter._route(_update(text=text).get("message"), text,
                                   str(chat_id), "Tunde", chat_id).reply

    def test_payload_carries_a_code_and_a_deep_link(self):
        self.adapter.username_lookup = lambda token: "hellostarkai_bot"
        payload = self.adapter.link_code()
        self.assertRegex(payload["code"], r"^\d{6}$")
        self.assertEqual(payload["expires_in"], identity_repository.CODE_TTL_SECONDS)
        self.assertEqual(payload["bot_username"], "hellostarkai_bot")
        self.assertEqual(payload["deep_link"],
                         f"https://t.me/hellostarkai_bot?start={payload['code']}")

    def test_deep_link_redeems_the_code(self):
        code = self.adapter.link_code()["code"]
        self.assertIn("Linked", self._say(f"/start {code}"))
        self.assertEqual(self.ids.resolve(telegram.CHANNEL, "42"), self.account.id)

    def test_no_username_means_no_deep_link_but_the_code_still_works(self):
        self.adapter.username_lookup = lambda token: None
        payload = self.adapter.link_code()
        self.assertIsNone(payload["deep_link"])
        self.assertIn("Linked", self._say(f"/link {payload['code']}"))

    def test_start_without_a_code_stays_the_welcome_text(self):
        # A stray payload must not burn one of the chat's five attempts.
        self.assertEqual(self._say("/start hello"), telegram.HELP_TEXT)

    def test_a_code_never_rebinds_a_linked_chat(self):
        self.linked()
        code = self.adapter.link_code()["code"]
        self.assertIn("already linked", self._say(f"/start {code}"))


class TestPerAccountRouting(AdapterCase):
    """One bot, many accounts: a chat speaks for the account whose code it spent."""

    def test_each_chat_acts_on_its_own_account(self):
        # Before this, every linked chat ran on the owner's account: a second
        # sign-up could read and move the owner's money. Measured 2026-11-04.
        other = test_support.TempAccount()
        self.addCleanup(other.close)
        for chat, account in ((42, self.account.id), (99, other.id)):
            code = self.ids.issue_code(account)
            self.ids.consume_code(code, telegram.CHANNEL, str(chat), "Tunde")

        self.adapter.handle_update(_update(chat_id=42, text="hello stark what's left"))
        self.adapter.handle_update(_update(chat_id=99, text="hello stark what's left"))
        self.assertEqual(self.agent.users, [self.account.id, other.id])

    def test_a_link_code_is_minted_for_the_account_that_asks(self):
        # The Connect screen mints a code for the signed-in account, never for
        # whichever account the bot happens to call its owner.
        other = test_support.TempAccount()
        self.addCleanup(other.close)
        payload = self.adapter.link_code(other.id)
        self.ids.consume_code(payload["code"], telegram.CHANNEL, "77", "Tunde")
        self.assertEqual(self.ids.resolve(telegram.CHANNEL, "77"), other.id)

    def test_a_turn_is_logged_against_the_account_that_answered(self):
        other = test_support.TempAccount()
        self.addCleanup(other.close)
        code = self.ids.issue_code(other.id)
        self.ids.consume_code(code, telegram.CHANNEL, "88", "Tunde")
        self.adapter.handle_update(_update(chat_id=88, text="hello stark what's left"))
        self.assertEqual(self.turns[-1]["account_id"], other.id)


class TestVoice(AdapterCase):
    def setUp(self):
        super().setUp()
        self.wav = _tiny_wav()
        self.adapter.download = lambda file_id: self.wav
        self.linked()

    def test_voice_with_wake_word_is_transcribed_and_answered(self):
        self.adapter.transcribe = lambda wav: ("hello stark what's left", "ok")
        result = self.adapter.handle_update(
            _update(text=None, voice={"file_id": "f1"}))
        self.assertEqual(result["handled"], "agent")
        self.assertEqual(self.agent.transcripts, ["hello stark what's left"])

    def test_voice_without_wake_word_stays_silent(self):
        self.adapter.transcribe = lambda wav: ("what's the weather", "ok")
        result = self.adapter.handle_update(
            _update(text=None, voice={"file_id": "f1"}))
        self.assertEqual(result["handled"], "asleep")
        self.assertEqual(self.agent.transcripts, [])

    def test_no_speech_backend_says_so_instead_of_guessing(self):
        self.adapter.transcribe = stt.transcribe
        # No key, whatever the shell has: a real key would really transcribe.
        with mock.patch.dict(os.environ, {"NEAR_AI_API_KEY": ""}):
            result = self.adapter.handle_update(
                _update(text=None, voice={"file_id": "f1"}))
        self.assertEqual(result["handled"], "voice_unheard")
        self.assertEqual(self.agent.transcripts, [])
        self.assertIn("cannot hear voice notes", self.sent[-1][1])

    @unittest.skipUnless(audio.ffmpeg_available(), "ffmpeg not installed")
    def test_real_decode_of_generated_wav(self):
        wav, why = audio.transcode(self.wav)
        self.assertEqual(why, audio.OK)
        self.assertTrue(wav.startswith(b"RIFF"))


class TestVoiceReply(AdapterCase):
    """A voice note gets a voice note back — when the voice works.

    Every failure of the voice path (no synthesis, Telegram refusing the note)
    must land on the ordinary text reply: a spoken answer is a delight, not a
    dependency. Typed messages keep typed replies.
    """

    def setUp(self):
        super().setUp()
        self.linked()
        self.adapter.download = lambda file_id: _tiny_wav()
        self.adapter.transcribe = lambda wav: ("hello stark what's left", "ok")
        self.notes: list[tuple[int, bytes]] = []
        self.spoken: list[str] = []

    def speaking(self, note: bytes | None = b"OggS-fake-note"):
        self.adapter.speak = (
            lambda text: self.spoken.append(text) or note
        )
        self.adapter.send_voice = (
            lambda chat_id, ogg: self.notes.append((chat_id, ogg)) or True
        )

    def ask_by_voice(self):
        return self.adapter.handle_update(_update(text=None, voice={"file_id": "f1"}))

    def test_voice_question_comes_back_as_a_voice_note(self):
        self.speaking()
        result = self.ask_by_voice()
        self.assertEqual(result["handled"], "agent")
        self.assertEqual(self.notes, [(42, b"OggS-fake-note")])
        self.assertEqual(self.spoken, ["You've got about 11.4 units left."])
        self.assertEqual(self.sent, [])          # no text twin
        self.assertEqual(self.adapter.stats["spoken"], 1)

    def test_no_synthesis_falls_back_to_text(self):
        self.speaking(note=None)
        self.ask_by_voice()
        self.assertEqual(self.notes, [])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("11.4", self.sent[0][1])

    def test_telegram_refusal_falls_back_to_text(self):
        self.speaking()
        self.adapter.send_voice = lambda chat_id, ogg: False
        self.ask_by_voice()
        self.assertEqual(self.sent, [(42, "You've got about 11.4 units left.")])
        self.assertEqual(self.adapter.stats["spoken"], 0)

    def test_typed_message_keeps_a_typed_reply(self):
        self.speaking()
        result = self.adapter.handle_update(_update(text="hello stark what's left"))
        self.assertEqual(result["handled"], "agent")
        self.assertEqual(self.notes, [])         # never spoken to, so never spoken
        self.assertEqual(self.spoken, [])
        self.assertEqual(len(self.sent), 1)

    def test_wake_gate_reply_stays_text(self):
        self.speaking()
        self.adapter.transcribe = lambda wav: ("what's the weather", "ok")
        result = self.ask_by_voice()
        self.assertEqual(result["handled"], "asleep")
        self.assertEqual(self.notes, [])
        self.assertEqual(len(self.sent), 1)

    def test_commands_stay_text(self):
        self.speaking()
        result = self.adapter.handle_update(_update(text="/help"))
        self.assertEqual(result["handled"], "command")
        self.assertEqual(self.notes, [])
        self.assertEqual(self.spoken, [])


class TestSttFallback(unittest.TestCase):
    def test_no_key_is_honest_not_hallucinated(self):
        text, why = stt.transcribe(_tiny_wav(), api_key="")
        self.assertIsNone(text)
        self.assertEqual(why, stt.NO_KEY)


class TestAudioGuards(unittest.TestCase):
    def test_empty_and_oversized_inputs_are_refused(self):
        self.assertEqual(audio.transcode(b"")[1], audio.DECODE_FAILED)
        self.assertEqual(audio.transcode(b"x" * 100, max_input_bytes=10)[1], audio.TOO_LARGE)

    @unittest.skipUnless(audio.ffmpeg_available(), "ffmpeg not installed")
    def test_garbage_is_refused_not_guessed(self):
        self.assertEqual(audio.transcode(b"this is not audio at all" * 20)[1],
                         audio.DECODE_FAILED)


class TestChatContext(AdapterCase):
    """The chat is the thread, and every answered update reaches the log.

    Measured 2026-10-25: with no memory, "top up my airtime" → "how much?" →
    "500" → "which bill would you like to pay 500 for?" looped forever, because
    each reply forgot the other half of the answer.
    """

    def test_a_chat_is_named_as_the_thread(self):
        self.linked()
        self.adapter.handle_update(_update(chat_id=42, text="500"))
        self.assertEqual(self.agent.threads, ["telegram:42"])

    def test_two_chats_are_two_conversations(self):
        self.linked(chat_id=42)
        self.linked(chat_id=77)
        self.adapter.handle_update(_update(chat_id=42, text="top up my airtime"))
        self.adapter.handle_update(_update(chat_id=77, text="500", message_id=2,
                                           update_id=101))
        self.assertEqual(self.agent.threads, ["telegram:42", "telegram:77"])

    def test_an_answered_turn_carries_what_was_heard_and_said(self):
        self.linked()
        self.adapter.handle_update(_update(text="what's left"))

        self.assertEqual(len(self.turns), 1)
        turn = self.turns[0]
        self.assertEqual(turn["outcome"], "agent")
        self.assertEqual(turn["heard"], "what's left")
        self.assertEqual(turn["said"], "what's left")
        self.assertEqual(turn["reply"], "You've got about 11.4 units left.")
        # The agent's own result travels with it, so the log can keep the
        # actions and the whole exchange, not just the sentence.
        self.assertEqual(turn["result"].actions, ["pay_bill"])

    def test_a_refused_voice_note_is_logged_as_asleep(self):
        self.linked()
        adapter = TelegramAdapter(
            agent=self.agent, identities=self.ids, bot_token="1:T", secret="s",
            download=lambda file_id: _tiny_wav(),
            transcribe=lambda clip: ("what's the weather", "ok"),
            send=lambda chat_id, text: True,
            on_turn=self.turns.append,
        )
        adapter.handle_update(_update(voice={"file_id": "f1"}, text=None))
        self.assertEqual([t["outcome"] for t in self.turns], ["asleep"])
        self.assertEqual(self.turns[0]["heard"], "what's the weather")
        self.assertIsNone(self.turns[0]["said"])
        self.assertEqual(self.agent.transcripts, [])

    def test_a_broken_log_never_breaks_the_reply(self):
        self.linked()

        def boom(turn):
            raise RuntimeError("disk full")

        adapter = TelegramAdapter(
            agent=self.agent, identities=self.ids, bot_token="1:T", secret="s",
            send=lambda chat_id, text: self.sent.append((chat_id, text)) or True,
            on_turn=boom,
        )
        result = adapter.handle_update(_update(text="what's left"))
        self.assertEqual(result["handled"], "agent")
        self.assertEqual(self.sent[-1][1], "You've got about 11.4 units left.")


if __name__ == "__main__":
    unittest.main()


class TestConcurrentChats(unittest.TestCase):
    """Two chats at once on the one shared adapter: each keeps its own deposit.

    Hermetic — no database. Chat 1's reply delivery is held open while chat 2's
    whole update runs, which is exactly the window in which chat 1 used to read
    chat 2's result off the adapter and send chat 2's deposit address to chat 1.
    """

    def test_a_chat_is_never_sent_another_chats_deposit(self):
        import threading

        class Identities:
            def claim_message(self, channel, message_id):
                return True

            def resolve(self, channel, channel_user_id):
                return {"1": "acct_victim", "2": "acct_attacker"}.get(channel_user_id)

        def deposit_for(user_id):
            return {"id": f"dep_{user_id}", "method": "crypto", "amount_ngn": 50_000,
                    "pay": {"asset": "USDT", "chain": "tron", "amount": "33.5",
                            "address": f"ADDR_{user_id}", "memo": None}}

        class Agent:
            def respond(self, user_id, said, thread):
                class Reply:
                    reply = "Here's how to add ₦50,000."
                    deposit = deposit_for(user_id)
                    actions, code, receipt_id, token, conversation = [], None, None, None, []
                return Reply()

        sent: dict[int, list[str]] = {1: [], 2: []}
        chat_two_done = threading.Event()

        def send(chat_id, text):
            if chat_id == 1 and not sent[1]:
                chat_two_done.wait(5)     # hold chat 1 mid-delivery
            sent[chat_id].append(text)
            return True

        adapter = TelegramAdapter(agent=Agent(), identities=Identities(),
                                  bot_token="123:TEST", secret="s", send=send,
                                  speak=lambda text: None)

        def update(chat_id, message_id):
            return {"update_id": message_id, "message": {
                "message_id": message_id, "chat": {"id": chat_id},
                "from": {"id": chat_id}, "text": "stark add 50000 with usdt"}}

        victim = threading.Thread(target=adapter.handle_update, args=(update(1, 101),))
        victim.start()
        adapter.handle_update(update(2, 102))
        chat_two_done.set()
        victim.join(5)

        self.assertIn("ADDR_acct_victim", sent[1][-1])
        self.assertNotIn("ADDR_acct_attacker", "".join(sent[1]))
        self.assertIn("ADDR_acct_attacker", sent[2][-1])
