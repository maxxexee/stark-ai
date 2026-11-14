"""What a Telegram message looks like beyond its words: buttons, a menu, and an
address that copies in one tap.

Every value the model never wrote (an address, a link, an amount) comes from the
deposit itself and is escaped here, because these messages are sent as HTML.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

from app.modules.wallet.chains import ChainNames

# A tapped choice comes back as callback data with this prefix and is read as if
# the user had typed the rest. Telegram caps callback data at 64 bytes.
CHOICE_PREFIX = "say:"
CALLBACK_DATA_LIMIT = 64
CHOICES_PER_ROW = 2


@dataclass(frozen=True)
class Outgoing:
    """One message: its text and the `sendMessage` fields beyond chat and text."""

    text: str
    extra: dict[str, Any] = field(default_factory=dict)


class Replies:
    # Always under the message box once a chat is linked: the things people come
    # for, a tap away. Each button sends its label as an ordinary message.
    MENU_BUTTONS = (("Balance", "Add money"), ("Pay a bill", "Recent payments"))

    @classmethod
    def menu(cls) -> dict[str, Any]:
        return {"reply_markup": {
            "keyboard": [[{"text": label} for label in row] for row in cls.MENU_BUTTONS],
            "resize_keyboard": True,
            "is_persistent": True,
        }}

    @staticmethod
    def choices(options: list[str]) -> dict[str, Any]:
        """Tap-to-answer buttons. An option too long for callback data is left
        out rather than cut, since a cut answer would say something else."""
        buttons = [{"text": option, "callback_data": CHOICE_PREFIX + option}
                   for option in options
                   if len((CHOICE_PREFIX + option).encode()) <= CALLBACK_DATA_LIMIT]
        if not buttons:
            return {}
        rows = [buttons[i:i + CHOICES_PER_ROW]
                for i in range(0, len(buttons), CHOICES_PER_ROW)]
        return {"reply_markup": {"inline_keyboard": rows}}

    @staticmethod
    def choice_from(data: Any) -> str | None:
        """The answer a tapped choice stands for, or None if it is not one of ours."""
        if not isinstance(data, str) or not data.startswith(CHOICE_PREFIX):
            return None
        return data[len(CHOICE_PREFIX):].strip() or None

    @classmethod
    def deposit(cls, deposit: dict[str, Any]) -> Outgoing:
        """What to do with a deposit `add_money` started."""
        pay = deposit["pay"]
        if deposit["method"] == "bank":
            amount = f"₦{deposit['amount_ngn']:,}"
            return Outgoing(
                f"Add {amount} by bank transfer, card or USSD. The link works for an hour.",
                {"reply_markup": {"inline_keyboard": [[
                    {"text": f"Pay {amount}", "url": pay["checkout_url"]}]]}})
        chain = ChainNames.display(pay["chain"])
        amount, asset, address = str(pay["amount"]), str(pay["asset"]), str(pay["address"])
        lines = [f"Send exactly <code>{html.escape(amount)}</code> {html.escape(asset)} "
                 f"on {html.escape(chain)} to:",
                 f"<code>{html.escape(address)}</code>"]
        buttons = [[{"text": "Copy address", "copy_text": {"text": address}}],
                   [{"text": "Copy amount", "copy_text": {"text": amount}}]]
        if pay.get("memo"):
            memo = str(pay["memo"])
            lines.append(f"Memo: <code>{html.escape(memo)}</code>")
            buttons.append([{"text": "Copy memo", "copy_text": {"text": memo}}])
        lines.append(f"\nThe address works for an hour. Send only on {html.escape(chain)}: "
                     "coins sent on another network are lost. Your balance updates "
                     "once it lands.")
        return Outgoing("\n".join(lines), {"parse_mode": "HTML",
                                           "reply_markup": {"inline_keyboard": buttons}})
