"""Refusals a tool raises. Their messages are written for the user."""

from __future__ import annotations


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

    def __init__(self, code: str, message: str, options: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.message = message
        # Answers the user can pick from ("USDC on Solana"). A door that has
        # buttons shows them, so a choice is a tap instead of typing.
        self.options = options
