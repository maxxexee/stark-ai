"""`POST /v1/_stub/reset`: put the caller's account back to the artboard seed.

Off unless `STARK_STUB_RESET=1`, and off whenever a real rail is configured
(Flutterwave, the treasury key or the vault chain), whatever the flag says: the
reset writes a ₦64,200 balance that no deposit and no vault entry stands behind, and
with a rail that balance could buy real goods or leave as real money. Off, it
answers exactly like a route that does not exist, so no signed-in user can swap
their real data for the artboard's.

It only touches the caller's account: their bills, history, wallet, caps and
readings, and the Telegram chats linked to them. Other accounts' links stay.
"""

from __future__ import annotations

from app.common.api_error import ApiError
from app.modules.account.account_repository import AccountRepository
from app.modules.account.account_service import AccountService
from app.modules.receipt.receipt_repository import ReceiptRepository
from app.modules.reminder.reminder_service import ReminderService
from app.modules.stub.stub_seed import StubSeed
from app.modules.telegram.identity_repository import IdentityRepository
from app.modules.telemetry.telemetry_repository import TelemetryRepository
from app.shared.services.api_config_service import ApiConfigService


class StubService:
    def __init__(self, config: ApiConfigService, accounts: AccountService,
                 repository: AccountRepository, receipts: ReceiptRepository,
                 readings: TelemetryRepository, identities: IdentityRepository,
                 reminders: ReminderService, *, live_rails: bool) -> None:
        self.config = config
        self.accounts = accounts
        self.repository = repository
        self.receipts = receipts
        self.readings = readings
        self.identities = identities
        self.reminders = reminders
        self.live_rails = live_rails

    def reset(self, account_id: str) -> dict[str, bool]:
        if not self.config.stub_reset_enabled or self.live_rails:
            raise ApiError(404, "no_route", "No route POST /v1/_stub/reset")
        bills = self.accounts.state(account_id).bills
        bills.clear()
        bills.update(StubSeed.bills())
        history = StubSeed.receipts(bills)
        self.receipts.replace_all(account_id, history, balance_ngn=StubSeed.BALANCE_NGN,
                                  spent_ngn=StubSeed.SPENT_NGN)
        StubSeed.sync_history(bills, history)
        self.repository.replace_bills(account_id, list(bills.values()))
        self.accounts.rebuild_limits(account_id,
                                     monthly_cap_ngn=AccountService.MONTHLY_CAP_NGN,
                                     per_payment_cap_ngn=AccountService.PER_PAYMENT_CAP_NGN)
        self.readings.clear(account_id)
        # In memory and keyed by bill, so the seeded bills' reminders can fire again.
        self.reminders.log.clear()
        for identity in self.identities.identities_for(account_id):
            self.identities.unlink(identity["channel"], identity["channel_user_id"])
        return {"reset": True}
