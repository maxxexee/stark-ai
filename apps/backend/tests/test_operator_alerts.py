"""Operator alerts live in the database for the admin page, and reminders reach
every linked account rather than one bot owner."""

from __future__ import annotations

import unittest
import uuid

from app.database import neon
from app.modules.reminder.reminder_service import ReminderService
from app.modules.telegram import telegram
from app.modules.treasury.operator_alerts import OperatorAlerts


class OperatorAlertsTest(unittest.TestCase):
    def setUp(self):
        self.db = neon.open_database()
        self.alerts = OperatorAlerts(self.db)
        # A kind of its own, so a run never touches the real alarms' rows.
        self.kind = f"test_{uuid.uuid4().hex[:8]}"
        self.addCleanup(self.db.query, "DELETE FROM operator_alerts WHERE kind = $1",
                        [self.kind])

    def mine(self):
        return [a for a in self.alerts.recent() if a["kind"] == self.kind]

    def test_raised_once_kept_current_then_cleared(self):
        self.assertTrue(self.alerts.raise_alarm(self.kind, "Treasury holds 0.00 USDC"))
        self.assertFalse(self.alerts.raise_alarm(self.kind, "Treasury holds 0.50 USDC"))
        [alert] = self.mine()
        self.assertEqual(alert["message"], "Treasury holds 0.50 USDC")
        self.assertIsNone(alert["cleared_at"])

        self.assertTrue(self.alerts.clear(self.kind, "Treasury is back to 120.00 USDC."))
        self.assertFalse(self.alerts.clear(self.kind, "again"))
        [alert] = self.mine()
        self.assertEqual(alert["cleared_message"], "Treasury is back to 120.00 USDC.")

    def test_a_cleared_alarm_raised_again_is_new(self):
        self.alerts.raise_alarm(self.kind, "low")
        self.alerts.clear(self.kind, "ok")
        self.assertTrue(self.alerts.raise_alarm(self.kind, "low again"))
        self.assertIsNone(self.mine()[0]["cleared_at"])


class RemindersForEveryoneTest(unittest.TestCase):
    """Hermetic: the loop asks for every linked account and nudges each one."""

    def test_every_linked_account_is_pushed_and_one_failure_does_not_stop_the_rest(self):
        class Identities:
            def linked_accounts(self, channel):
                assert channel == telegram.CHANNEL
                return ["acct_a", "acct_broken", "acct_b"]

        class Telegram:
            identities = Identities()

        service = ReminderService.__new__(ReminderService)
        service.telegram = Telegram()
        pushed: list[str] = []

        def push_due(account_id):
            if account_id == "acct_broken":
                raise RuntimeError("bad bill")
            pushed.append(account_id)
            return [f"nudge for {account_id}"]

        service.push_due = push_due
        self.assertEqual(service.push_all(), 2)
        self.assertEqual(pushed, ["acct_a", "acct_b"])
