"""One logging setup for the whole API, written to stdout for the deployment platform.

Every line goes through `Redactor` on its way out, so a secret, a session token or a
customer's phone number cannot reach the platform's log viewer even when a caller
logs a whole request, an exception or a provider's error body. Redaction runs on the
formatted line (message, arguments and traceback together), so it cannot be skipped
by passing the value as an argument instead of in the message.

    2026-11-12T21:40:11Z WARNING stark.vault authorisation refused user=acct_1 cause=…

Configured once at boot (`Logs.setup`), including uvicorn's own loggers, which then
write through the same handler. `STARK_LOG_LEVEL` sets the level (default INFO).
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time

_KEYS = (r"api[_-]?key|secret(?:[_-]?key|[_-]?hash)?|password|passwd|token|access[_-]?token"
         r"|refresh[_-]?token|authorization|verif-hash|private[_-]?key|bot[_-]?token|signature")


class Redactor:
    """Masks what must never be logged. Each rule keeps enough to tell values apart
    (the last digits of a phone, the domain of an email) and drops the rest."""

    RULES: tuple[tuple[re.Pattern[str], str], ...] = (
        # `Authorization: Bearer <token>` and any bare bearer token.
        (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted]"),
        # JSON Web Tokens.
        (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+"), "[jwt]"),
        # NEAR private keys.
        (re.compile(r"ed25519:[1-9A-HJ-NP-Za-km-z]{40,}"), "ed25519:[redacted]"),
        # Flutterwave keys, test or live.
        (re.compile(r"FLW(?:SECK|PUBK)(?:_TEST)?-[A-Za-z0-9-]+"), "FLW[redacted]"),
        # Telegram bot tokens, alone or inside an API URL.
        (re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}"), "[bot-token]"),
        # `?token=…`, `&key=…` in a URL (uvicorn's access line logs the query string).
        (re.compile(rf"(?i)([?&](?:{_KEYS}|code)=)[^&\s\"']+"), r"\1[redacted]"),
        # `"secret": "…"`, `password=…`, `X-Stark-Admin-Key: …`.
        (re.compile(rf"(?i)(\"?(?:{_KEYS}|x-stark-admin-key)\"?\s*[:=]\s*\"?)[^\"\s,;}}&]+"),
         r"\1[redacted]"),
        # A prepaid meter token: five groups of four digits.
        (re.compile(r"\b\d{4}(?:[ -]\d{4}){4}\b"), "[meter-token]"),
        # Emails: keep the first letter and the domain.
        (re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"),
         r"\1***@\2"),
        # Phone, meter, smartcard and bank account numbers: keep the last four.
        (re.compile(r"(?<![\w.])(\+?\d{6,12})(\d{4})(?![\w.])"),
         lambda m: "*" * len(m.group(1)) + m.group(2)),
    )

    @classmethod
    def redact(cls, text: str) -> str:
        for pattern, replacement in cls.RULES:
            text = pattern.sub(replacement, text)
        return text


class RedactingFormatter(logging.Formatter):
    """UTC timestamps, one level and logger per line, everything redacted."""

    converter = time.gmtime

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s",
                         datefmt="%Y-%m-%dT%H:%M:%SZ")

    def format(self, record: logging.LogRecord) -> str:
        return Redactor.redact(super().format(record))


class Logs:
    @staticmethod
    def setup() -> None:
        """Route every logger, uvicorn's included, through one redacting handler."""
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(RedactingFormatter())
        root = logging.getLogger()
        root.handlers[:] = [handler]
        root.setLevel(os.environ.get("STARK_LOG_LEVEL", "INFO").upper())
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uvicorn_logger = logging.getLogger(name)
            uvicorn_logger.handlers[:] = []
            uvicorn_logger.propagate = True
