"""The owner can see and remove the chats that speak for their account, and the
bot's owner is never decided by an unverified email.

Drives the real app on the real database (`support.ApiHarness`), so it needs
`DATABASE_URL` like the other store tests.
"""

from __future__ import annotations

import secrets
import unittest

from app.modules.telegram import telegram
from tests import support as test_support


class LinkedChatsTest(unittest.TestCase):
    def setUp(self):
        self.account = test_support.TempAccount()
        self.addCleanup(self.account.close)
        self.api = test_support.ApiHarness(self.account)
        self.addCleanup(self.api.restart)
        self.client = self.api.client
        self.identities = self.api.module.identities

    def link(self, account_id: str, display_name: str | None = "Tunde") -> str:
        chat = str(5_000_000_000 + secrets.randbelow(1_000_000_000))
        code = self.identities.issue_code(account_id)
        self.identities.consume_code(code, telegram.CHANNEL, chat, display_name)
        return chat

    def test_no_chats_is_an_empty_list(self):
        self.assertEqual(self.client.get("/v1/link/identities").json(), [])

    def test_a_linked_chat_is_listed_with_a_masked_hint(self):
        chat = self.link(self.account.id)
        [listed] = self.client.get("/v1/link/identities").json()
        self.assertEqual(listed["channel"], telegram.CHANNEL)
        self.assertEqual(listed["channel_user_id"], chat)
        self.assertEqual(listed["chat_hint"], f"•••• {chat[-4:]}")
        self.assertEqual(listed["display_name"], "Tunde")
        self.assertRegex(listed["linked_at"], r"^\d{4}-\d{2}-\d{2}T")

    def test_removing_a_chat_unlinks_it(self):
        chat = self.link(self.account.id)
        response = self.client.delete(f"/v1/link/identities/{telegram.CHANNEL}/{chat}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"unlinked": True, "channel": telegram.CHANNEL,
                                           "channel_user_id": chat})
        self.assertIsNone(self.identities.resolve(telegram.CHANNEL, chat))
        self.assertEqual(self.client.get("/v1/link/identities").json(), [])

    def test_another_accounts_chat_cannot_be_removed_or_seen(self):
        other = test_support.TempAccount()
        self.addCleanup(other.close)
        chat = self.link(other.id)
        self.assertEqual(self.client.get("/v1/link/identities").json(), [])
        response = self.client.delete(f"/v1/link/identities/{telegram.CHANNEL}/{chat}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "unknown_identity")
        self.assertEqual(self.identities.resolve(telegram.CHANNEL, chat), other.id)

    def test_an_unknown_chat_is_404(self):
        response = self.client.delete(f"/v1/link/identities/{telegram.CHANNEL}/1")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "unknown_identity")


class BotOwnerTest(unittest.TestCase):
    def setUp(self):
        self.account = test_support.TempAccount()
        self.addCleanup(self.account.close)

    def owner(self, **config) -> str:
        api = test_support.ApiHarness(self.account, **config)
        self.addCleanup(api.restart)
        return api.module.telegram.owner_account_id()

    def test_a_configured_account_id_is_the_owner(self):
        self.assertEqual(self.owner(telegram_owner_account_id=self.account.id,
                                    telegram_owner_email=""), self.account.id)

    def test_an_unverified_email_never_makes_an_owner(self):
        # Email sign-up does not verify the address, so anyone could sign up as
        # the owner's email. The temp account has no verified Neon Auth user.
        self.assertEqual(self.owner(telegram_owner_account_id=None,
                                    telegram_owner_email=f"{self.account.id}@test.invalid"),
                         "")


if __name__ == "__main__":
    unittest.main()
