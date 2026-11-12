"""What reaches the platform's logs: every line redacted, whatever logged it."""

from __future__ import annotations

import io
import logging
import unittest

from app.common.logs import Logs, RedactingFormatter, Redactor


class RedactorTests(unittest.TestCase):
    CASES = [
        ('GET /v1/speak/stream?text=hi&token=abc.def-123 HTTP/1.1', "abc.def-123"),
        ('GET /v1/speak/stream?ticket=Zx9_kQ-4rT HTTP/1.1', "Zx9_kQ-4rT"),
        ("Authorization: Bearer sess_abcdef123456", "sess_abcdef123456"),
        ("key ed25519:3D4YudUahN1nawWogh8pAKSj92sUNMdbZGjn7kERKzYoTy8tnFQuwoGUC51Dow",
         "3D4YudUahN1nawWogh8pAKSj92sUNMdbZGjn7kERKzYoTy8tnFQuwoGUC51Dow"),
        ("FLW_SECRET_KEY=FLWSECK_TEST-abc123-X", "FLWSECK_TEST-abc123-X"),
        ("https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/x",
         "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"),
        ('{"secret": "hunter2", "amount_ngn": 5000}', "hunter2"),
        ("X-Stark-Admin-Key: kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk", "kkkkkkkkkkkkkkkk"),
        ("token 4821 0937 5512 8846 3019 bought", "4821 0937 5512 8846 3019"),
        ("user adedokun.test@gmail.com paid", "adedokun.test"),
        ("airtime to 09127366558", "09127366558"),
        ("meter 0101170026583", "0101170026583"),
    ]

    def test_secrets_and_personal_numbers_never_survive(self):
        for line, secret in self.CASES:
            with self.subTest(line=line):
                self.assertNotIn(secret, Redactor.redact(line))

    def test_what_an_operator_needs_is_kept(self):
        line = ("vault u-312d6989246f5965.funder.moonboys-stark.near amount_usdc=3573545 "
                "ngn=5000 status=pending at 2026-11-12T21:40:11Z")
        self.assertEqual(Redactor.redact(line), line)
        self.assertIn("6558", Redactor.redact("airtime to 09127366558"))
        self.assertIn("@gmail.com", Redactor.redact("a.b@gmail.com"))


class LogsSetupTests(unittest.TestCase):
    def setUp(self):
        root = logging.getLogger()
        saved = (root.handlers[:], root.level)
        self.addCleanup(lambda: (setattr(root, "handlers", saved[0]), root.setLevel(saved[1])))

    def test_arguments_and_tracebacks_are_redacted_too(self):
        Logs.setup()
        stream = io.StringIO()
        logging.getLogger().handlers[0].stream = stream
        log = logging.getLogger("stark.test")
        log.warning("paying %s", "09127366558")
        try:
            raise RuntimeError("Bearer sess_leaky_token_123")
        except RuntimeError:
            log.exception("boom")
        out = stream.getvalue()
        self.assertNotIn("09127366558", out)
        self.assertNotIn("sess_leaky_token_123", out)
        self.assertIn("WARNING stark.test paying *******6558", out)

    def test_uvicorn_writes_through_the_same_handler(self):
        Logs.setup()
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            self.assertEqual(logging.getLogger(name).handlers, [])
            self.assertTrue(logging.getLogger(name).propagate)
        self.assertIsInstance(logging.getLogger().handlers[0].formatter, RedactingFormatter)
