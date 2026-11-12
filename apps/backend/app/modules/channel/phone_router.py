"""The gates every phone door shares: dedupe, commands, identity, wake, agent.

WhatsApp and SMS differ only in transport — how a webhook is signed, how media
is fetched, how a reply goes out. What happens to a verified message is the same
for both, and it is the Telegram door's order (`telegram/telegram.py`):

1. **Dedupe.** The message id is claimed in `processed_messages` before any work,
   so a provider's retry cannot double-pay.
2. **Commands.** `link 482913`, `unlink`, `whoami`, `pause`, `resume`, `help` — a
   leading `/` is optional, because a phone keyboard has no command menu. Only a
   message that *is* a command counts: "pause my airtime top-up" is a request.
3. **Identity.** An unknown number gets link instructions and nothing else —
   never state, never the agent, never a payment.
4. **Wake gate, for voice only**, by the same `wake.py` rule `/v1/voice` uses.
5. **The agent**, scoped to the linked account. One brain: nothing here branches
   on channel except the words of a reply.

Logs carry the outcome, the account id and the last four digits of the number —
never a message body, a transcript or a full number.
"""

from __future__ import annotations

from typing import Any, Callable

from app.modules.channel.channel_turn import ChannelTurn
from app.modules.channel.inbound_message import InboundMessage
from app.modules.channel.phone_number import PhoneNumber
from app.modules.control.control_service import ControlService
from app.modules.telegram.identity_repository import IdentityRepository
from app.modules.voice import wake

VOICE_NO_STT = (
    "I cannot hear voice notes right now. "
    "Type what you need instead."
)
VOICE_ASLEEP = "I'm here. Say 'stark' first, then your question."
UNREADABLE = "I can only read text and voice notes for now."
FAILED = "Something went wrong handling that. Nothing was charged."
HELP_TEXT = (
    "Stark pays your household bills inside your limits.\n"
    "Try: 'how much is left' or 'pay 5000 for electricity'.\n"
    "Commands: pause, resume, whoami, unlink, help"
)

_SINGLE_WORD_COMMANDS = {"unlink", "whoami", "pause", "resume", "help", "start"}


class PhoneRouter:
    def __init__(
        self,
        channel: str,
        label: str,
        *,
        identities: IdentityRepository,
        respond: Callable[[str, str, str], Any],
        controls: ControlService | None = None,
        hear: Callable[[str], str | None] | None = None,
        log: Callable[[str], None] = lambda line: None,
    ) -> None:
        """`respond(user_id, said, thread)` runs that account's agent; `hear(media_id)`
        turns a voice note into a transcript, or None when it cannot be heard."""
        self.channel = channel
        self.label = label
        self.identities = identities
        self.respond = respond
        self.controls = controls
        self.hear = hear
        self.log = log

    @property
    def link_help(self) -> str:
        return (
            "I do not know this number yet. Open the Stark app, tap "
            f"Connect {self.label}, and send me the 6-digit code it shows: link 482913"
        )

    def route(self, message: InboundMessage) -> ChannelTurn:
        if not self.identities.claim_message(self.channel, message.message_id):
            return ChannelTurn("duplicate", None)
        try:
            turn = self._route(message)
        except Exception as err:  # a bad message must not 500 the webhook
            self.log(f"{self.channel} message failed: {type(err).__name__}: {err}")
            turn = ChannelTurn("error", FAILED)
        self.log(
            f"{self.channel} from={PhoneNumber.redact(message.channel_user_id)}"
            f" user={turn.user_id} outcome={turn.outcome}"
        )
        return turn

    def _route(self, message: InboundMessage) -> ChannelTurn:
        text = (message.text or "").strip()
        sender = message.channel_user_id

        command = self._command(text, sender, message.display_name)
        if command is not None:
            return ChannelTurn("command", command, heard=text)

        user_id = self.identities.resolve(self.channel, sender)
        if user_id is None:
            return ChannelTurn("unlinked", self.link_help, heard=text or None)

        if message.media_id:
            transcript = self.hear(message.media_id) if self.hear is not None else None
            if transcript is None:
                return ChannelTurn("voice_unheard", VOICE_NO_STT, user_id=user_id)
            said = wake.wake_attempt(transcript)
            if said is None:
                return ChannelTurn(
                    "asleep", VOICE_ASLEEP, user_id=user_id, heard=transcript
                )
            spoken = True
        elif text:
            transcript = said = text
            spoken = False
        else:
            return ChannelTurn("ignored", UNREADABLE, user_id=user_id)

        # The number is the thread: memory is per conversation, so two people
        # messaging Stark cannot answer each other's questions.
        result = self.respond(user_id, said, f"{self.channel}:{sender}")
        return ChannelTurn(
            "agent",
            result.reply,
            spoken=spoken,
            user_id=user_id,
            heard=transcript,
            said=said,
            result=result,
        )

    def link_with(self, code: str, sender: str, display_name: str | None) -> str:
        if self.identities.resolve(self.channel, sender):
            return (
                "This number is already linked. Send whoami to check, unlink to remove."
            )
        if not code:
            return "Send the code from the app like this: link 482913"
        user_id = self.identities.consume_code(code, self.channel, sender, display_name)
        if user_id is None:
            return (
                "That code did not work. Codes expire after 10 minutes and "
                "work once. Get a fresh one in the app."
            )
        return "Linked. Ask me for your balance, or say 'pay 5000 for electricity'."

    def _command(self, text: str, sender: str, display_name: str | None) -> str | None:
        """The reply to a command, or None when the message is not one."""
        parts = text.split()
        if not parts:
            return None
        verb = parts[0].lstrip("/").lower()

        if verb == "link" and len(parts) <= 2:
            return self.link_with(
                parts[1] if len(parts) == 2 else "", sender, display_name
            )
        if len(parts) != 1 or verb not in _SINGLE_WORD_COMMANDS:
            return None

        if verb in ("help", "start"):
            return HELP_TEXT

        if verb == "whoami":
            user_id = self.identities.resolve(self.channel, sender)
            return f"Linked to {user_id}." if user_id else "Not linked."

        if verb == "unlink":
            if self.identities.unlink(self.channel, sender):
                return "Unlinked. This number can no longer see or move money."
            return "This number was not linked."

        user_id = self.identities.resolve(self.channel, sender)
        if user_id is None:
            return self.link_help
        if self.controls is None:
            return "Pausing from chat is not set up. Use the app for now."
        if verb == "pause":
            self.controls.pause(user_id)
            return (
                "Paused. I will not pay anything until you send resume. "
                "You can still ask me questions."
            )
        self.controls.resume(user_id)
        return "Resumed. I can pay your bills again, inside your limits."
