"""The composition root: every repository and service, built once and wired together.

Controllers reach these through `request.app.state.module` (see
`decorators/inject_module.py`), so a test can build an `AppModule` on whatever
database it likes and hand it to `create_app`.
"""

from __future__ import annotations

from app.database import neon
from app.modules.admin.admin_service import AdminService
from app.modules.account.account_repository import AccountRepository
from app.modules.account.account_service import AccountService
from app.modules.agent import agent as agent_layer
from app.modules.agent.account_toolbox import AccountToolbox
from app.modules.approval.approval_repository import ApprovalRepository
from app.modules.approval.approval_service import ApprovalService
from app.modules.auth.auth_service import AuthService
from app.modules.flutterwave import flutterwave
from app.modules.flutterwave.flutterwave_webhook_service import FlutterwaveWebhookService
from app.modules.bill.bill_service import BillService
from app.modules.chain import near_tx, treasury_chain, vault_chain
from app.modules.control.control_service import ControlService
from app.modules.demo.demo_service import DemoService
from app.modules.intents import one_click
from app.modules.limit.limit_service import LimitService
from app.modules.liquidity.float_service import FloatService
from app.modules.payment.bill_payment_service import BillPaymentService
from app.modules.payment.payment_service import PaymentService
from app.modules.plan.plan_service import PlanService
from app.modules.receipt.receipt_repository import ReceiptRepository
from app.modules.reminder.reminder_service import ReminderService
from app.modules.settings.settings_service import SettingsService
from app.modules.state.state_service import StateService
from app.modules.stub.stub_service import StubService
from app.modules.suggestion.suggestion_service import SuggestionService
from app.modules.telegram.identity_repository import IdentityRepository
from app.modules.telegram.telegram_service import TelegramService
from app.modules.telemetry.telemetry_repository import TelemetryRepository
from app.modules.telemetry.telemetry_service import TelemetryService
from app.modules.treasury.treasury_service import TreasuryService
from app.modules.treasury.treasury_watch import TreasuryWatch
from app.modules.vault.vault_service import VaultService
from app.modules.vending.catalog import CATALOG
from app.modules.vending.vending import VendingGateway
from app.modules.voice.voice_service import VoiceService
from app.modules.wallet.deposit_service import DepositService
from app.modules.wallet.wallet_service import WalletService
from app.modules.wallet.crypto_withdrawal_service import CryptoWithdrawalService
from app.modules.wallet.withdrawal_service import WithdrawalService
from app.shared.services.api_config_service import ApiConfigService


class AppModule:
    def __init__(self, config: ApiConfigService, db: neon.Database) -> None:
        self.config = config
        self.db = db

        self.receipts = ReceiptRepository(db)
        self.account_repository = AccountRepository(db)
        self.readings = TelemetryRepository(db)
        self.identities = IdentityRepository(db)

        self.auth = AuthService(db)
        self.accounts = AccountService(
            self.auth, self.account_repository, self.receipts, self._build_agent
        )
        self.demo = DemoService()

        # Money: each user's vault, the rails that fill and empty it, the float.
        money = config.money
        self.usdc_rate = money.funding.usdc_rate
        self.flutterwave = flutterwave.client_from_env()
        if self.flutterwave is not None:
            CATALOG.use(self.flutterwave.bill_categories)
        self.vaults = VaultService(db, vault_chain.chain_from_env(), self.accounts,
                                    self.usdc_rate.market)
        gateway = VendingGateway(self.flutterwave)
        self.floats = FloatService(db, self.flutterwave, money.float_settings)
        one_click_client = one_click.client_from_env()
        self.deposits = DepositService(
            db,
            self.receipts,
            self.vaults,
            self.flutterwave,
            one_click_client,
            money.funding,
        )
        self.withdrawals = WithdrawalService(db, self.receipts, self.vaults, self.flutterwave,
                                             self.account_repository, money.withdrawals)
        treasury = treasury_chain.treasury_from_env()
        # Real USDC leaves only against real naira. A Flutterwave test key credits
        # checkouts nobody paid for, so it switches crypto payouts off.
        self.crypto_withdrawals = CryptoWithdrawalService(
            db,
            self.withdrawals,
            self.vaults,
            self.deposits,
            one_click_client,
            treasury,
            money.crypto_payouts,
            sandbox_naira=self.flutterwave is not None and self.flutterwave.test_mode,
        )
        self.flutterwave_webhooks = FlutterwaveWebhookService(
            db, money.flutterwave_secret_hash, self.deposits, self.withdrawals
        )
        self.controls = ControlService(
            self.accounts, self.account_repository, self.vaults
        )
        self.settings_service = SettingsService(db)
        self.bills = BillService(self.accounts, self.account_repository, self.receipts,
                                 self.settings_service)
        self.plans = PlanService()
        # Free test money only on a box with no rail at all: with a treasury key it
        # could be withdrawn as real USDC.
        self.wallet = WalletService(
            self.accounts, self.receipts, self.vaults,
            test_money=self.flutterwave is None and treasury is None,
        )
        self.telemetry = TelemetryService(self.readings, self.receipts)
        self.bill_payments = BillPaymentService(
            self.accounts,
            self.bills,
            self.wallet,
            PaymentService(
                self.receipts, gateway, vaults=self.vaults, floats=self.floats
            ),
            self.settings_service,
        )
        self.telegram = TelegramService(
            config, db, self.identities, self.accounts, self.controls
        )
        self.treasury = TreasuryService(
            db,
            self.vaults,
            self.deposits,
            self.bill_payments,
            self.withdrawals,
            self.crypto_withdrawals,
            self.floats,
            money.funding.treasury_account,
            self.usdc_rate,
            near_tx.NearRpc(near_tx.MAINNET_RPC),
            TreasuryWatch(money.watch, self.telegram.tell_owner),
        )
        self.admin = AdminService(db, self.treasury, self.vaults, self.settings_service)
        self.approvals = ApprovalService(ApprovalRepository(db), self.bill_payments)
        self.limits = LimitService(self.accounts, self.wallet, self.approvals)
        self.state = StateService(self.accounts, self.wallet, self.telemetry, self.bills)
        self.suggestions = SuggestionService(
            self.accounts, self.wallet, self.telemetry, self.bill_payments
        )
        self.voice = VoiceService(self.accounts)
        self.reminders = ReminderService(self.accounts, self.telegram)
        self.stub = StubService(
            config,
            self.accounts,
            self.account_repository,
            self.receipts,
            self.readings,
            self.identities,
            self.reminders,
        )

    @classmethod
    def from_env(cls) -> "AppModule":
        """`DATABASE_URL` is required: accounts, wallets and receipts live there."""
        return cls(ApiConfigService.from_env(), neon.open_database())

    def _build_agent(
        self, account_id: str, limits: agent_layer.Limits
    ) -> agent_layer.Agent:
        """An agent bound to one account's toolbox and caps."""
        return agent_layer.build_agent(AccountToolbox(account_id, self), limits)
