"""The Telegram door: verify, identify, gate, answer (M4).

One brain, many doors (HANDOFF §8A). This file is transport and identity only —
every utterance that passes the gates ends in `Agent.respond`, the same call
`/v1/voice` uses, and the policy gate sits inside that agent. Nothing here may
spend money or read state on its own.

Order of checks, and why:

1. **Webhook secret, before parsing.** `X-Telegram-Bot-Api-Secret-Token` is
   compared in constant time against `TELEGRAM_WEBHOOK_SECRET`. No secret is
   configured → the adapter refuses everything (`disabled`), because an open
   webhook is a wallet anyone on the internet can talk to.
2. **Dedupe.** Telegram re-delivers updates; each `update_id` is claimed in
   `processed_messages` before any work, so a retry cannot double-pay.
3. **Identity.** An unlinked chat gets link instructions and nothing else —
   never state, never the agent, never a payment. The only claim that counts is
   a 6-digit code minted by the app (`identity_repository.py`).
4. **Wake gate, for voice only.** A voice note must open with an attempt at the
   wake word — the same `wake.py` rule `/v1/voice` enforces, mishearings and all —
   because a voice note can be recorded by accident.
   A typed message in a DM with the bot is deliberate — no wake word needed.
   That split is deliberate; it is not a second brain, it is a UI courtesy.

Nothing here is live until `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET`
are set. With no `NEAR_AI_API_KEY`, voice notes are answered with a plain
sentence saying they cannot be heard — never a guessed transcript.

A **voice note gets a voice note back**: when the reply answers one,
ElevenLabs (`tts.voice_note`, `ELEVENLABS_API_KEY`) speaks it and it ships as
OGG/Opus via `sendVoice`. Every failure of that path — no key, no ffmpeg,
a Telegram refusal — lands on the ordinary text reply, because a spoken
answer is a delight, not a dependency. Typed messages keep typed replies.
"""

from __future__ import annotations

import hmac
import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from app.modules.voice import audio
from app.modules.voice import stt
from app.modules.voice import tts
from app.modules.voice import wake
from app.modules.telegram.identity_repository import CODE_TTL_SECONDS

CHANNEL = "telegram"

TELEGRAM_API = "https://api.telegram.org"

LINK_HELP = (
    "You are not linked to a Stark account yet.\n"
    "Open the Stark app, tap Connect Telegram, and send me the 6-digit code it "
    "shows: link 482913"
)
NOT_LINKED_REPLY = (
    "I do not know this chat yet. Get a 6-digit code from the Stark app and "
    "send: link 000000"
)
VOICE_NO_STT = (
    "I cannot hear voice notes right now. "
    "Type what you need instead."
)
VOICE_ASLEEP = "I'm here. Say 'stark' first, then your question."
HELP_TEXT = (
    "Stark pays your household bills inside your limits.\n"
    "Try: 'hello stark how much is left' or 'hello stark pay 5000 for electricity'.\n"
    "Commands: /pause, /resume, /whoami, /unlink, /help"
)


class TelegramError(Exception):
    """What the HTTP layer turns into a refusal."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


class AgentLike(Protocol):
    # `user_id` is the account this chat is linked to, never the bot's owner, so
    # one bot can serve every account.
    def respond(self, user_id: str, said: str, thread: str) -> Any: ...


class ControlsLike(Protocol):
    def pause(self, account_id: str) -> dict[str, Any]: ...
    def resume(self, account_id: str) -> dict[str, Any]: ...


class IdentityLike(Protocol):
    def resolve(self, channel: str, channel_user_id: str) -> str | None: ...
    def issue_code(self, user_id: str) -> str: ...
    def consume_code(self, code: str, channel: str, channel_user_id: str,
                     display_name: str | None = None) -> str | None: ...
    def unlink(self, channel: str, channel_user_id: str) -> bool: ...
    def claim_message(self, channel: str, message_id: str) -> bool: ...


# --- transport (real network; injected in tests) -----------------------------


def download_file(file_id: str, *, bot_token: str,
                  timeout: float = 20.0, max_bytes: int = 5 * 1024 * 1024) -> bytes | None:
    """Fetch a Telegram file, bounded. Returns None on any failure."""
    try:
        with urllib.request.urlopen(
            f"{TELEGRAM_API}/bot{bot_token}/getFile?file_id={file_id}",
            timeout=timeout,
        ) as res:
            info = json.loads(res.read() or b"{}")
        path = (info.get("result") or {}).get("file_path")
        if not path:
            return None
        with urllib.request.urlopen(
            f"{TELEGRAM_API}/file/bot{bot_token}/{path}", timeout=timeout
        ) as res:
            data = res.read(max_bytes + 1)
        return data if len(data) <= max_bytes else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def send_message(chat_id: int, text: str, *, bot_token: str,
                 timeout: float = 15.0) -> bool:
    """One reply. Never raises — a chat that cannot be reached is not an error."""
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
        data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def pay_note(deposit: dict[str, Any]) -> str:
    """What to do with a deposit `add_money` started, written from the deposit itself
    so a link or an address is never retyped by the model."""
    pay = deposit["pay"]
    if deposit["method"] == "bank":
        return (f"Add ₦{deposit['amount_ngn']:,} by bank transfer, card or USSD:\n"
                f"{pay['checkout_url']}\n\nThe link works for an hour.")
    lines = [f"Send exactly {pay['amount']} {pay['asset']} on {pay['chain']} to:",
             pay["address"]]
    if pay.get("memo"):
        lines.append(f"Memo: {pay['memo']}")
    lines.append(f"\nThis adds ₦{deposit['amount_ngn']:,}. The address works for an "
                 "hour, and your balance updates once it lands. Only send on that network.")
    return "\n".join(lines)


_USERNAME_CACHE: dict[str, str | None] = {}


def bot_username(bot_token: str | None, *, timeout: float = 8.0) -> str | None:
    """The bot's own @username, for a `t.me` deep link.

    Cached per token — a username never changes, and the Connect screen asks
    every time it opens. Failures are deliberately *not* cached: a box that was
    offline when it booted should not be stuck without a deep link for life.
    """
    if not bot_token:
        return None
    if bot_token in _USERNAME_CACHE:
        return _USERNAME_CACHE[bot_token]
    try:
        with urllib.request.urlopen(
            f"{TELEGRAM_API}/bot{bot_token}/getMe", timeout=timeout
        ) as res:
            info = json.loads(res.read() or b"{}")
        username = (info.get("result") or {}).get("username")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    _USERNAME_CACHE[bot_token] = username
    return username


def send_voice_note(chat_id: int, ogg: bytes, *, bot_token: str,
                    timeout: float = 30.0) -> bool:
    """One voice note (OGG/Opus). Never raises — same rule as `send_message`:
    a chat that cannot be reached is not an error."""
    boundary = f"----starkvoice{uuid.uuid4().hex}"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n'
        f'{chat_id}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="voice"; '
        f'filename="voice.ogg"\r\nContent-Type: audio/ogg\r\n\r\n'
    ).encode() + ogg + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{TELEGRAM_API}/bot{bot_token}/sendVoice",
        data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


# --- adapter -----------------------------------------------------------------


@dataclass
class Turn:
    """What one update did. Local to its update, never stored on the adapter.

    The adapter is shared by every webhook request, and Telegram delivers updates
    from different chats concurrently. When these fields lived on the adapter, a
    chat could be sent the deposit address another chat's turn had just made:
    paying it credited the other account.
    """

    outcome: str
    reply: str | None = None
    user_id: str | None = None
    heard: str | None = None
    said: str | None = None
    result: Any = None
    speak: bool = False


@dataclass
class TelegramAdapter:
    agent: AgentLike
    identities: IdentityLike
    # The off switch, so a linked chat can stop payments without opening the app.
    controls: ControlsLike | None = None
    bot_token: str | None = None
    secret: str | None = None
    # The account this bot serves. A callable is resolved per use, so the account
    # can be created by a sign-up after the server has already booted.
    owner_user_id: str | Callable[[], str] = ""
    download: Callable[[str], bytes | None] | None = None
    transcribe: Callable[[bytes], tuple[str | None, str]] | None = None
    send: Callable[[int, str], bool] | None = None
    # Resolving the bot's @username for a deep link. Injected in tests so the
    # Connect screen's payload is asserted without a network call.
    username_lookup: Callable[[str | None], str | None] | None = None
    # Speaking the reply: text → OGG/Opus bytes, and how those bytes go out.
    # Both injected in tests; live they default to tts.voice_note / the API.
    speak: Callable[[str], bytes | None] | None = None
    send_voice: Callable[[int, bytes], bool] | None = None
    # One callback per update that reached the agent, so the server can write the
    # turn to `turnlog`. Injected in tests; wired live in server.py.
    on_turn: Callable[[dict], None] | None = None
    log: Callable[[str], None] = lambda line: None
    stats: dict[str, int] = field(default_factory=lambda: {
        "updates": 0, "duplicates": 0, "unlinked": 0, "agent": 0,
        "commands": 0, "voice": 0, "ignored": 0, "spoken": 0,
    })

    @property
    def enabled(self) -> bool:
        """Both secrets present. Otherwise every update is refused."""
        return bool(self.bot_token and self.secret)

    def link_code(self, account_id: str | None = None) -> dict[str, Any]:
        """Mint one single-use code for an account, plus the deep link that spends it.

        The code is the only thing that binds a chat to this account (see
        `identity_repository.py`), so it is returned exactly once and never logged.
        `deep_link` is None when the bot has no token or Telegram could not be
        reached — the code still works, typed by hand as `link 482913`.

        The account is the one asking, not the bot's owner: a chat speaks for the
        account whose code it spent, so every new sign-up can bind its own
        Telegram instead of everyone sharing the owner's wallet.
        """
        account = (account_id or "").strip() or (
            self.owner_user_id() if callable(self.owner_user_id) else self.owner_user_id
        )
        if not account:
            raise TelegramError(409, "not_configured", "No account to link this chat to.")
        code = self.identities.issue_code(account)
        lookup = self.username_lookup or bot_username
        username = lookup(self.bot_token)
        return {
            "code": code,
            "channel": CHANNEL,
            "expires_in": CODE_TTL_SECONDS,
            "bot_username": username,
            "deep_link": f"https://t.me/{username}?start={code}" if username else None,
        }

    def verify_secret(self, header_value: str | None) -> None:
        """Raise TelegramError unless the webhook is authenticated."""
        if not self.enabled:
            raise TelegramError(401, "webhook_unconfigured",
                                "Telegram secrets are not set; refusing all updates.")
        if not header_value:
            raise TelegramError(401, "webhook_unverified",
                                "Missing X-Telegram-Bot-Api-Secret-Token.")
        if not hmac.compare_digest(header_value.encode(), self.secret.encode()):
            raise TelegramError(401, "webhook_unverified", "Bad webhook secret.")

    # --- entry point ---------------------------------------------------------

    def handle_update(self, update: dict[str, Any]) -> dict[str, Any]:
        self.stats["updates"] += 1
        update_id = str(update.get("update_id") or "")
        message = update.get("message") or update.get("channel_post") or {}
        message_id = str(message.get("message_id") or update_id or "")

        if update_id or message_id:
            if not self.identities.claim_message(CHANNEL, message_id or update_id):
                self.stats["duplicates"] += 1
                return {"ok": True, "handled": "duplicate", "update_id": update.get("update_id")}

        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None:
            self.stats["ignored"] += 1
            return {"ok": True, "handled": "ignored", "update_id": update.get("update_id")}

        sender = message.get("from") or {}
        channel_user_id = str(sender.get("id") or chat_id)
        display_name = sender.get("first_name") or sender.get("username")
        text = (message.get("text") or message.get("caption") or "").strip()

        try:
            turn = self._route(message, text, channel_user_id, display_name, chat_id)
        except Exception as err:  # a bad update must not 500 the webhook
            self.log(f"telegram update failed: {err}")
            turn = Turn(outcome="failed",
                        reply="Something went wrong handling that. Nothing was charged.")

        if turn.reply:
            self._deliver(chat_id, turn.reply, spoken=turn.speak)
        # Always text, even after a voice note: an address is copied, not listened to.
        deposit = getattr(turn.result, "deposit", None)
        if deposit:
            self._send(chat_id, pay_note(deposit))
        self._emit_turn(turn)
        return {"ok": True, "handled": turn.outcome, "update_id": update.get("update_id")}

    def _emit_turn(self, turn: Turn) -> None:
        """Hand the exchange to the log, if anything is listening.

        `turnlog` used to be written only by `/v1/voice`, so the channel people
        actually demo had no record at all — the first Telegram conversation
        could not be read back (`count: 0`), and "why did it say that" had to be
        answered by replaying it locally.
        """
        if self.on_turn is None:
            return
        try:
            self.on_turn({
                "outcome": turn.outcome,
                "heard": turn.heard or "",
                "said": turn.said,
                "reply": turn.reply,
                "result": turn.result,
                "account_id": turn.user_id,
            })
        except Exception as err:  # a broken log must not break the reply
            self.log(f"telegram turn log failed: {err}")

    def _send(self, chat_id: int, text: str) -> None:
        if self.send is not None:
            self.send(chat_id, text)
        elif self.bot_token:
            send_message(chat_id, text, bot_token=self.bot_token)
        else:
            self.log(f"telegram reply to {chat_id}: {text}")

    def _deliver(self, chat_id: int, text: str, *, spoken: bool) -> None:
        """Voice note when Stark was spoken to and the voice works; text otherwise.

        Fail-closed like everything else here: no voice, no ffmpeg, or a
        Telegram refusal, and the reply still arrives — as text.
        """
        if spoken:
            synth = self.speak if self.speak is not None else tts.voice_note
            ogg = synth(text)
            if ogg and self._send_voice(chat_id, ogg):
                self.stats["spoken"] += 1
                return
        self._send(chat_id, text)

    def _send_voice(self, chat_id: int, ogg: bytes) -> bool:
        if self.send_voice is not None:
            return bool(self.send_voice(chat_id, ogg))
        if not self.bot_token:
            self.log("telegram voice reply skipped: no bot token")
            return False
        return send_voice_note(chat_id, ogg, bot_token=self.bot_token)

    # --- routing -------------------------------------------------------------

    def _route(self, message: dict, text: str, channel_user_id: str,
               display_name: str | None, chat_id: int) -> Turn:
        if text.startswith("/"):
            self.stats["commands"] += 1
            return Turn(outcome="command", heard=text,
                        reply=self._command(text, channel_user_id, display_name))

        user_id = self.identities.resolve(CHANNEL, channel_user_id)
        if user_id is None:
            self.stats["unlinked"] += 1
            return Turn(outcome="unlinked", heard=text or None, reply=NOT_LINKED_REPLY)

        transcript = None
        said = None            # what the agent reads: the transcript, addressed
        from_voice = False
        if message.get("voice") or message.get("audio"):
            from_voice = True
            self.stats["voice"] += 1
            transcript = self._transcribe(message)
            if transcript is None:
                return Turn(outcome="voice_unheard", reply=VOICE_NO_STT)
            # Same wake rule as /v1/voice (wake.py): a misheard wake word is
            # still an address, anything else stays silent, not chatty.
            said = wake.wake_attempt(transcript)
            if said is None:
                self.stats["ignored"] += 1
                return Turn(outcome="asleep", heard=transcript, reply=VOICE_ASLEEP)
        elif text:
            transcript = said = text
        else:
            self.stats["ignored"] += 1
            return Turn(outcome="ignored",
                        reply="I can only read text and voice notes for now.")

        self.stats["agent"] += 1
        # What was said stays out of the platform's logs: it can carry phone and
        # meter numbers. The turn log (operator-only) keeps it when switched on.
        self.log(f"telegram turn user={user_id} voice={from_voice} chars={len(said)}")
        # The chat is the thread: a bare "500" is only an amount because the
        # previous line asked how much. Memory is per chat, so two people
        # messaging the bot cannot answer each other's questions.
        result = self.agent.respond(user_id, said, thread=f"{CHANNEL}:{chat_id}")
        # Spoken only when the question was a voice note: you spoke to Stark,
        # Stark speaks back. A typed message gets a typed reply.
        return Turn(outcome="agent", reply=result.reply, user_id=user_id,
                    heard=transcript, said=said, result=result, speak=from_voice)

    def _transcribe(self, message: dict) -> str | None:
        voice = message.get("voice") or message.get("audio") or {}
        file_id = voice.get("file_id")
        if not file_id:
            return None
        fetch = self.download
        if fetch is None:
            if not self.bot_token:
                return None
            fetch = lambda fid: download_file(fid, bot_token=self.bot_token)
        raw = fetch(file_id)
        if not raw:
            return None
        wav, why = audio.transcode(raw)
        if wav is None:
            self.log(f"telegram audio decode failed: {why}")
            return None
        speak = self.transcribe or stt.transcribe
        text, why = speak(wav)
        if text is None:
            self.log(f"telegram stt failed: {why}")
        return text

    def link_with(self, code: str, channel_user_id: str,
                  display_name: str | None) -> str:
        """Redeem a link code for this chat — the `/link` and deep-link path."""
        if self.identities.resolve(CHANNEL, channel_user_id):
            return "This chat is already linked. /whoami to check, /unlink to remove."
        if not code:
            return "Send the code from the app like this: link 482913"
        user_id = self.identities.consume_code(code, CHANNEL, channel_user_id, display_name)
        if user_id is None:
            return ("That code did not work. Codes expire after 10 minutes and "
                    "work once. Get a fresh one in the app.")
        return "Linked. Ask me for your balance, or say 'hello stark pay 5000 for electricity'."

    def _command(self, text: str, channel_user_id: str, display_name: str | None) -> str:
        parts = text.split()
        verb = parts[0].split("@")[0].lower()

        if verb in ("/start", "/help"):
            # A deep link (t.me/<bot>?start=482913) arrives as "/start 482913".
            # Only a six-digit payload is treated as a code: anything else must
            # stay the welcome text, because every failed redeem burns one of
            # the chat's five attempts in `identity_repository.py`.
            payload = parts[1] if len(parts) > 1 else ""
            if len(payload) == 6 and payload.isdigit():
                return self.link_with(payload, channel_user_id, display_name)
            return HELP_TEXT

        if verb == "/link":
            code = parts[1] if len(parts) > 1 else ""
            return self.link_with(code, channel_user_id, display_name)

        if verb == "/whoami":
            user_id = self.identities.resolve(CHANNEL, channel_user_id)
            return f"Linked to {user_id}." if user_id else "Not linked."

        if verb in ("/pause", "/resume"):
            user_id = self.identities.resolve(CHANNEL, channel_user_id)
            if user_id is None:
                return NOT_LINKED_REPLY
            if self.controls is None:
                return "Pausing from chat is not set up. Use the app for now."
            if verb == "/pause":
                self.controls.pause(user_id)
                return ("Paused. I will not pay anything until you send /resume. "
                        "You can still ask me questions.")
            self.controls.resume(user_id)
            return "Resumed. I can pay your bills again, inside your limits."

        if verb == "/unlink":
            if self.identities.unlink(CHANNEL, channel_user_id):
                return "Unlinked. This chat can no longer see or move money."
            return "This chat was not linked."

        return HELP_TEXT
