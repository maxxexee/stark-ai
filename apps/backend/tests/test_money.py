"""The money flow end to end: deposit → vault → float → purchase → withdrawal.

Rails are faked at their HTTP clients (chain, Flutterwave, 1Click), so every
state transition runs against the real Postgres schema without a network. What
these do NOT prove: that the live services answer in the modeled shapes. That is
recorded in docs/HANDOFF.md.
"""

from __future__ import annotations

import base64
import json
import time
import unittest
from typing import Optional
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.modules.flutterwave import flutterwave
from app.modules.flutterwave.flutterwave import FlutterwaveError
from app.modules.flutterwave.flutterwave_webhook_service import FlutterwaveWebhookService
from app.modules.chain import near_tx, vault_chain
from app.modules.chain.treasury_chain import SignedTransfer
from app.modules.chain.vault_chain import ChainResult, VaultChain
from app.modules.intents.one_click import OneClickError
from app.modules.liquidity.float_service import FloatService, FloatSettings
from app.modules.liquidity.usdc_rate import STALE_SECONDS, RateUnavailable, UsdcRate
from app.modules.payment import payment_service
from app.modules.vault.vault_service import AuthorisationFailed, VaultService
from app.modules.vending import vending
from app.modules.wallet.crypto_withdrawal_service import (
    CryptoPayoutSettings,
    CryptoWithdrawalService,
)
from app.modules.wallet.deposit_service import (
    MAX_CHECK_SECONDS,
    MIN_CHECK_SECONDS,
    SOON_SECONDS,
    DepositService,
    FundingSettings,
    _check_delay,
    _payable,
)
from app.modules.account.account_repository import AccountRepository
from app.modules.wallet.withdrawal_service import WithdrawalService, WithdrawalSettings
from tests import support

OPEN_WITHDRAWALS = WithdrawalSettings(daily_ngn=10**12, lookups_per_day=10**6)
CARD_HOLD_HOURS = 72

KEY = near_tx.KeyPair.from_secret(bytes(range(32)))
RATE_1500 = UsdcRate(spread_ngn=Decimal(0), fixed=Decimal("1500"))
SPREAD_RATE = UsdcRate(spread_ngn=Decimal(10), fixed=Decimal("1500"))


class DownRate(UsdcRate):
    def __init__(self):
        super().__init__(spread_ngn=Decimal(10))

    def _fetch(self):
        raise RateUnavailable("Paycrest down")
AGENT = near_tx.KeyPair.from_secret(bytes(range(1, 33)))
METER = "0101170026583"
ELECTRICITY = {"id": "bill_home", "label": "Home meter", "kind": "electricity",
               "reference": METER, "provider": "ikeja-electric", "meter_type": "prepaid"}


# --- fakes ---------------------------------------------------------------------


class FakeChain:
    """Records every chain write; can be told to fail the next call."""

    broadcast = True
    funder_id = "stark-vault.testnet"

    def __init__(self):
        self.calls: list[tuple] = []
        self.fail_with: Exception | None = None
        self.policy = {"monthly_cap_ngn": "30000", "per_payment_cap_ngn": "10000",
                       "allowed_meters": [METER]}
        self.rate = "666667"
        self.settled = True
        self.rpc = self
        self.payment_id = 0

    def vault_id(self, account_id):
        return f"u-{account_id[-8:]}.{self.funder_id}"

    def _maybe_fail(self):
        if self.fail_with is not None:
            err, self.fail_with = self.fail_with, None
            raise err

    def create(self, vault_id, **policy):
        self._maybe_fail()
        self.calls.append(("create", vault_id, policy))
        return ChainResult("ab" * 32, None, True)

    def pay(self, vault_id, meter, amount):
        self._maybe_fail()
        self.payment_id += 1
        self.calls.append(("pay", meter, amount))
        return ChainResult("cd" * 32, {"payment_id": self.payment_id,
                                       "settled": self.settled}, True)

    def pay_approved(self, vault_id, meter, amount):
        self._maybe_fail()
        self.payment_id += 1
        self.calls.append(("pay_approved", meter, amount))
        return ChainResult("ef" * 32, {"payment_id": self.payment_id,
                                       "settled": self.settled}, True)

    def deposit(self, vault_id, amount_usdc, msg):
        self._maybe_fail()
        if msg.startswith("refund:"):
            self.calls.append(("refund", {"payment_id": int(msg[len("refund:"):]),
                                          "amount_usdc": amount_usdc}))
        else:
            self.calls.append(("fund", {"amount_usdc": amount_usdc, "reference": msg}))
        return ChainResult("23" * 32, "0", True)

    def payment(self, vault_id, payment_id):
        return {"amount_usdc": "666667"}

    def state(self, vault_id):
        return {"usdc_per_kngn": self.rate, "balance_usdc": "0", "balance_ngn": "0"}

    def call(self, vault_id, method, args):
        self._maybe_fail()
        self.calls.append((method, args))
        if method == "set_policy":
            self.policy = args
        if method == "set_rate":
            self.rate = args["usdc_per_kngn"]
        return ChainResult("01" * 32, None, True)

    def view(self, vault_id, method, args):
        assert method == "get_policy"
        return self.policy

    def methods(self):
        return [c[0] for c in self.calls]

    def deposits(self):
        """Deposits other than the balance a new vault opens with."""
        return [c for c in self.calls
                if c[0] == "fund" and not c[1]["reference"].startswith("opening:")]


class FakeFlutterwave:
    """Flutterwave's checkout, verify, banks, resolve, transfers and balance."""

    test_mode = True

    def __init__(self, balance=500_000):
        self.value = balance
        self.reads = 0
        self.checkouts: dict[str, dict] = {}
        self.charges: dict[str, dict] = {}
        self.transfers: list[dict] = []
        self.transfer_status: dict[str, str] = {}
        self.resolved = True
        self.resolves = 0
        self.lookups: list[str] = []
        self.transfer_error: FlutterwaveError | None = None

    def ngn_balance(self):
        self.reads += 1
        return self.value

    def create_checkout(self, *, tx_ref, amount_ngn, email, name, redirect_url, meta):
        self.checkouts[tx_ref] = {"amount": amount_ngn, "email": email,
                                  "redirect_url": redirect_url, "meta": meta}
        return f"https://checkout.flutterwave.com/v3/hosted/pay/{tx_ref[-6:]}"

    def pay(self, tx_ref, amount, *, status="successful", currency="NGN",
            payment_type="bank_transfer"):
        """The customer finishes the checkout."""
        self.charges[tx_ref] = {"id": 4_000_000 + len(self.charges), "tx_ref": tx_ref,
                                "amount": amount, "currency": currency, "status": status,
                                "payment_type": payment_type}

    def verify_by_reference(self, tx_ref):
        if tx_ref not in self.charges:
            raise FlutterwaveError(400, "No transaction was found for this id")
        return self.charges[tx_ref]

    def banks(self):
        return [{"id": 1, "name": "Guaranty Trust Bank", "code": "058"}]

    def resolve_account(self, bank_code, account_number):
        self.resolves += 1
        if not self.resolved:
            raise FlutterwaveError(400, "Sorry, that account number is invalid")
        return {"account_name": "ADA OKAFOR", "account_number": account_number}

    def create_transfer(self, *, bank_code, account_number, amount_ngn, reference,
                        narration):
        if self.transfer_error is not None:
            raise self.transfer_error
        transfer = {"id": 26_000 + len(self.transfers), "status": "NEW",
                    "reference": reference, "amount": amount_ngn, "bank_code": bank_code}
        self.transfers.append(transfer)
        return transfer

    def find_transfer(self, reference):
        self.lookups.append(reference)
        transfer = next((t for t in self.transfers if t["reference"] == reference), None)
        if transfer is None:
            return None
        return {**transfer,
                "status": self.transfer_status.get(reference, transfer["status"]),
                "complete_message": "Account is invalid"}

    def get_transfer(self, transfer_id):
        transfer = next(t for t in self.transfers if str(t["id"]) == transfer_id)
        return {**transfer, "status": self.transfer_status.get(transfer["reference"], "PENDING"),
                "complete_message": "Account is invalid"}


class FakeOneClick:
    def __init__(self):
        self.status_reply = {"status": "PENDING_DEPOSIT", "swapDetails": {}}
        self.quotes: list[dict] = []
        self.refuse: Optional[Exception] = None
        self.status_reads = 0

    def tokens(self):
        return [{"assetId": "nep141:tron-usdt", "symbol": "USDT", "blockchain": "tron",
                 "decimals": 6}]

    def quote(self, *, origin_asset, swap_type, amount, recipient, deadline, dry=False):
        if self.refuse is not None:
            raise self.refuse
        self.quotes.append({"origin": origin_asset, "swap_type": swap_type, "amount": amount,
                            "recipient": recipient, "dry": dry})
        return {"quote": {"depositAddress": None if dry else "TXdeposit1",
                          "depositMemo": None, "amountIn": "13460000",
                          "amountInFormatted": "13.46", "amountOut": "14700000",
                          "minAmountOut": "14553000",
                          "deadline": deadline}}

    def status(self, address, memo):
        self.status_reads += 1
        return self.status_reply

    def submit_deposit(self, address, tx_hash, memo):
        return self.status_reply


class FakeAccounts:
    def __init__(self, limits):
        self.limits = limits

    def state(self, account_id):
        class State:
            pass
        state = State()
        state.limits = self.limits
        return state


def limits():
    from app.modules.agent import agent as agent_layer
    return agent_layer.Limits(30_000, 10_000, frozenset({METER}))


class MoneyCase(unittest.TestCase):
    balance = 0

    def setUp(self):
        self.account = support.TempAccount()
        self.db = self.account.db
        self.receipts = self.account.store.raw
        # An opened account always has a wallet row, even at ₦0.
        self.receipts.set_wallet(self.account.id, self.balance, 0)
        self.chain = FakeChain()
        self.vaults = VaultService(self.db, self.chain, FakeAccounts(limits()), RATE_1500.market)

    def tearDown(self):
        self.account.close()

    def wallet(self):
        return self.receipts.wallet(self.account.id)

    def ledger(self, flutterwave, settings=OPEN_WITHDRAWALS):
        return WithdrawalService(self.db, self.receipts, self.vaults, flutterwave,
                                 AccountRepository(self.db), settings)

    def pause(self):
        self.db.query("UPDATE accounts SET paused_at = $2 WHERE id = $1",
                      [self.account.id, Clock.now_iso()])

    def ops(self):
        return self.db.query(
            "SELECT method, status FROM chain_ops WHERE user_id = $1 ORDER BY seq",
            [self.account.id],
        )


# --- the transaction encoders --------------------------------------------------


class ActionEncodingTests(unittest.TestCase):
    def test_function_call_key_is_scoped_to_pay_on_the_vault(self):
        raw = near_tx.add_function_call_key_action(
            AGENT.public, receiver_id="u-1.stark.testnet", method_names=["pay"],
            allowance=5,
        )
        self.assertEqual(raw[0], 5, "Action::AddKey")
        self.assertEqual(raw[1:34], b"\x00" + AGENT.public)
        self.assertEqual(raw[34:42], bytes(8), "access key nonce 0")
        self.assertEqual(raw[42], 0, "AccessKeyPermission::FunctionCall")
        self.assertEqual(raw[43], 1, "Some(allowance)")
        self.assertEqual(int.from_bytes(raw[44:60], "little"), 5)
        self.assertIn(b"u-1.stark.testnet", raw)
        self.assertTrue(raw.endswith(b"\x01\x00\x00\x00\x03\x00\x00\x00pay"))

    def test_full_access_is_never_granted(self):
        raw = near_tx.add_function_call_key_action(
            AGENT.public, receiver_id="v", method_names=["pay"])
        self.assertEqual(raw[42], 0, "never AccessKeyPermission::FullAccess (1)")
        self.assertEqual(raw[43], 0, "None allowance")

    def test_global_contract_actions(self):
        self.assertEqual(near_tx.use_global_contract_action("stark.testnet"),
                         b"\x0a\x01" + b"\x0d\x00\x00\x00stark.testnet")
        self.assertEqual(near_tx.deploy_global_contract_action(b"wasm"),
                         b"\x09\x04\x00\x00\x00wasm\x01")

    def test_pay_encoding_is_unchanged_by_the_generic_encoder(self):
        args = dict(signer_id="a.testnet", public_key=KEY.public, nonce=1,
                    receiver_id="v.testnet", block_hash=bytes(32))
        self.assertEqual(
            near_tx.encode_pay_transaction(meter=METER, amount_ngn=5000, **args),
            near_tx.encode_transaction(actions=[near_tx.function_call_action(
                "pay", near_tx.pay_args(METER, 5000))], **args),
        )

    def test_success_value_decodes_and_panics_become_refusals(self):
        ok = {"status": {"SuccessValue": base64.b64encode(b'{"payment_id":3}').decode()}}
        self.assertEqual(near_tx.success_value(ok), {"payment_id": 3})
        self.assertIsNone(near_tx.success_value({"status": {"SuccessValue": ""}}))
        refused = {"status": {"Failure": {"ActionError": {"kind": {"FunctionCallError": {
            "ExecutionError": "Smart contract panicked: That would go over your monthly limit."
        }}}}}}
        with self.assertRaises(near_tx.ContractRefused) as caught:
            near_tx.success_value(refused)
        self.assertEqual(caught.exception.message, "That would go over your monthly limit.")


class VaultChainTests(unittest.TestCase):
    def chain(self, **overrides):
        settings = dict(rpc=near_tx.NearRpc("http://127.0.0.1:9"), funder_id="stark.testnet",
                        funder_key=KEY, agent_key=AGENT, treasury_id="stark.testnet",
                        usdc_id="usdc.testnet", code="global:stark.testnet", storage_yocto=10,
                        broadcast=False)
        settings.update(overrides)
        return VaultChain(**settings)

    def test_vault_ids_are_short_lowercase_sub_accounts(self):
        chain = self.chain()
        self.assertEqual(chain.vault_id("acct_0123456789abcdef"),
                         "u-0123456789abcdef.stark.testnet")
        odd = chain.vault_id("test_Has Spaces!")
        self.assertTrue(odd.startswith("u-") and odd.endswith(".stark.testnet"))
        self.assertEqual(odd, odd.lower())

    def test_dry_chain_signs_offline(self):
        result = self.chain().create("u-1.stark.testnet", usdc_per_kngn=666_667,
                                     monthly_cap_ngn=30_000, per_payment_cap_ngn=10_000,
                                     meters=[METER])
        self.assertFalse(result.broadcast)
        self.assertIn(len(result.tx_hash), (43, 44), "base58, as explorers spell it")

    def test_create_is_one_transaction_of_five_actions_then_a_token_registration(self):
        signed: list[dict] = []
        original = near_tx.sign_transaction

        def spy(**kwargs):
            signed.append(kwargs)
            return original(**kwargs)

        near_tx.sign_transaction = spy
        try:
            self.chain().create("u-1.stark.testnet", usdc_per_kngn=666_667,
                                monthly_cap_ngn=30_000, per_payment_cap_ngn=10_000,
                                meters=[METER])
        finally:
            near_tx.sign_transaction = original
        captured, register = signed
        self.assertEqual(register["receiver_id"], "usdc.testnet")
        self.assertIn(b"storage_deposit", register["actions"][0])
        tags = [action[0] for action in captured["actions"]]
        self.assertEqual(tags, [0, 3, 10, 5, 2],
                         "create, fund storage, use code, add the pay key, init")
        self.assertEqual(captured["signer_id"], "stark.testnet")
        self.assertEqual(captured["receiver_id"], "u-1.stark.testnet")
        init = json.loads(captured["actions"][4][1 + 4 + 3 + 4:].split(b"\x00\xe8")[0]
                          .rsplit(b"}", 1)[0] + b"}")
        self.assertEqual(init["funder"], "stark.testnet")
        self.assertEqual(init["usdc"], "usdc.testnet")
        self.assertEqual(init["usdc_per_kngn"], "666667")
        self.assertEqual(init["allowed_meters"], [METER])

    def test_a_short_treasury_leaves_the_deposit_queued_not_failed(self):
        class Rpc:
            def view(self, account_id, method, args):
                return "999"

        chain = self.chain(rpc=Rpc(), broadcast=True)
        with self.assertRaises(near_tx.NearRpcError):
            chain.deposit("u-1.stark.testnet", 1_000, "dep_1")

    def test_pay_is_signed_as_the_vault_with_the_agent_key(self):
        captured = {}
        original = near_tx.sign_transaction

        def spy(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        near_tx.sign_transaction = spy
        try:
            self.chain().pay("u-1.stark.testnet", METER, 5000)
        finally:
            near_tx.sign_transaction = original
        self.assertEqual(captured["signer_id"], "u-1.stark.testnet")
        self.assertIs(captured["key"], AGENT)

    def test_config_is_all_or_nothing(self):
        self.assertIsNone(vault_chain.chain_from_env({}))
        with self.assertRaises(ValueError):
            vault_chain.chain_from_env({"STARK_FUNDER_ACCOUNT": "stark.testnet"})
        chain = vault_chain.chain_from_env({
            "STARK_FUNDER_ACCOUNT": "stark.testnet",
            "STARK_FUNDER_KEY": "ed25519:" + near_tx.b58encode(bytes(range(32))),
            "STARK_AGENT_KEY": "ed25519:" + near_tx.b58encode(bytes(range(1, 33))),
        })
        self.assertFalse(chain.broadcast)
        self.assertEqual(chain.code, "global:stark.testnet")
        self.assertEqual(chain.storage_yocto, 2 * 10 ** 23)


# --- the vault and Postgres stay in step ------------------------------------------


class VaultServiceTests(MoneyCase):
    def test_a_credit_creates_the_vault_and_lands(self):
        self.vaults.ensure(self.account.id)
        self.vaults.credit(self.account.id, 5000, "dep_1")
        self.assertEqual(self.chain.methods(), ["create", "fund"])
        self.assertEqual(self.ops(), [{"method": "fund", "status": "done"}])

    def test_the_same_reference_is_queued_once(self):
        self.vaults.ensure(self.account.id)
        self.vaults.credit(self.account.id, 5000, "dep_1")
        self.vaults.credit(self.account.id, 5000, "dep_1")
        self.assertEqual(self.chain.methods().count("fund"), 1)

    def test_a_network_failure_stays_pending_and_blocks_payment(self):
        self.vaults.ensure(self.account.id)
        self.chain.fail_with = near_tx.NearRpcError("timeout")
        self.vaults.credit(self.account.id, 5000, "dep_1")
        self.assertEqual(self.ops(), [{"method": "fund", "status": "pending"}])
        self.chain.fail_with = near_tx.NearRpcError("still down")
        with self.assertRaises(AuthorisationFailed):
            self.vaults.authorise_payment(self.account.id, METER, 1000)
        self.assertNotIn("pay", self.chain.methods(),
                         "never sign against a vault that is behind")
        # The network comes back: the deposit lands first, then the payment.
        auth = self.vaults.authorise_payment(self.account.id, METER, 1000)
        self.assertEqual(self.chain.methods()[-2:], ["fund", "pay"])
        self.assertEqual(auth.payment_id, 1)

    def test_a_contract_refusal_is_failed_not_retried(self):
        self.vaults.ensure(self.account.id)
        self.chain.fail_with = near_tx.ContractRefused("That's more than the balance")
        self.vaults.debit(self.account.id, 5000, "wd_1")
        self.assertEqual(self.ops(), [{"method": "debit", "status": "failed"}])
        self.assertEqual(self.vaults.flush(self.account.id), 0)

    def test_a_contract_refusal_on_pay_is_spoken_plainly(self):
        self.chain.fail_with = None
        self.vaults.ensure(self.account.id)
        self.chain.fail_with = near_tx.ContractRefused("That would go over your monthly limit.")
        with self.assertRaises(AuthorisationFailed) as caught:
            self.vaults.authorise_payment(self.account.id, METER, 1000)
        self.assertEqual(caught.exception.message,
                         "That would go over your monthly limit. Nothing was charged.")

    def test_policy_is_synced_before_paying(self):
        self.vaults.ensure(self.account.id)
        self.chain.policy = {"monthly_cap_ngn": "1", "per_payment_cap_ngn": "1",
                             "allowed_meters": []}
        self.vaults.authorise_payment(self.account.id, METER, 1000)
        self.assertEqual(self.chain.methods()[-2:], ["set_policy", "pay"])
        self.vaults.authorise_payment(self.account.id, METER, 1000)
        self.assertEqual(self.chain.methods()[-2:], ["pay", "pay"], "no resync when equal")

    def test_an_approved_payment_uses_the_owner_path(self):
        self.vaults.authorise_payment(self.account.id, METER, 40_000, approved=True)
        self.assertEqual(self.chain.methods()[-1], "pay_approved")

    def test_a_refund_sends_the_payments_usdc_back(self):
        auth = self.vaults.authorise_payment(self.account.id, METER, 1000)
        self.vaults.record_payment(self.account.id, "rcpt_x", auth.payment_id)
        self.vaults.refund_receipt(self.account.id, "rcpt_x")
        self.vaults.refund_receipt(self.account.id, "rcpt_x")
        self.assertEqual(self.chain.calls[-1], ("refund", {"payment_id": auth.payment_id,
                                                           "amount_usdc": 666_667}))
        self.assertEqual(self.chain.methods().count("refund"), 1)

    def test_a_deposit_sends_its_worth_in_usdc_priced_when_queued(self):
        self.vaults.ensure(self.account.id)
        self.vaults.credit(self.account.id, 1500, "dep_1")
        self.assertEqual(self.chain.calls[-1],
                         ("fund", {"amount_usdc": 1_000_001, "reference": "dep_1"}))

    def test_a_payment_whose_usdc_did_not_settle_is_refused(self):
        self.chain.settled = False
        with self.assertRaises(AuthorisationFailed) as caught:
            self.vaults.authorise_payment(self.account.id, METER, 1000)
        self.assertIn("Nothing was charged", caught.exception.message)

    def test_the_rate_is_synced_before_paying(self):
        self.vaults.ensure(self.account.id)
        self.chain.rate = "1"
        self.vaults.authorise_payment(self.account.id, METER, 1000)
        self.assertEqual(self.chain.calls[-2], ("set_rate", {"usdc_per_kngn": "666667"}))

    def test_a_new_vault_opens_with_the_wallet_balance(self):
        self.receipts.set_wallet(self.account.id, 7_500, 0)
        self.vaults.ensure(self.account.id)
        self.vaults.flush(self.account.id)
        self.assertEqual(self.chain.calls[-1], ("fund", {
            "amount_usdc": 5_000_003, "reference": f"opening:{self.vaults.vault_account(self.account.id)}"}))

    def test_the_opening_deposit_leaves_out_what_is_already_queued(self):
        self.receipts.set_wallet(self.account.id, 7_500, 0)
        self.chain.fail_with = near_tx.NearRpcError("vault not made yet")
        self.vaults.credit(self.account.id, 1_500, "dep_1")
        self.vaults.flush(self.account.id)
        funds = [c[1] for c in self.chain.calls if c[0] == "fund"]
        self.assertEqual(sorted(f["amount_usdc"] for f in funds), [1_000_001, 4_000_002])

    def test_a_vault_made_under_another_funder_is_not_reused(self):
        old = self.vaults.ensure(self.account.id)
        self.chain.funder_id = "stark.near"
        self.assertIsNone(self.vaults.vault_account(self.account.id))
        self.assertNotEqual(self.vaults.ensure(self.account.id), old)

    def test_no_chain_means_no_writes_and_no_authorisation(self):
        offline = VaultService(self.db, None, FakeAccounts(limits()), RATE_1500.market)
        offline.credit(self.account.id, 5000, "dep_1")
        self.assertIsNone(offline.authorise_payment(self.account.id, METER, 1000))
        self.assertEqual(self.ops(), [])


# --- the float ---------------------------------------------------------------------


class FloatServiceTests(MoneyCase):
    def floats(self, balance=500_000, test_mode=False):
        self.flutterwave = FakeFlutterwave(balance)
        self.flutterwave.test_mode = test_mode
        return FloatService(self.db, self.flutterwave, FloatSettings(low_water_ngn=100_000))

    def test_test_mode_has_nothing_to_cover(self):
        self.floats(balance=0, test_mode=True).ensure_can_cover(5000)

    def test_covers_a_purchase_that_fits(self):
        self.floats().ensure_can_cover(5000)

    def test_refuses_when_it_cannot_cover(self):
        floats = self.floats(balance=1000)
        with self.assertRaises(ApiError) as caught:
            floats.ensure_can_cover(5000)
        self.assertEqual(caught.exception.code, "float_low")
        self.assertIn("nothing was charged", caught.exception.message)

    def test_an_unreadable_balance_refuses_too(self):
        with self.assertRaises(ApiError) as caught:
            FloatService(self.db, None, FloatSettings(1)).ensure_can_cover(5000)
        self.assertEqual(caught.exception.code, "float_low")

    def test_pending_purchases_count_as_spent(self):
        floats = self.floats(balance=10_000)
        self.receipts.create(self.account.id, {
            "id": "rcpt_p", "request_id": "req_p", "bill_id": "b", "bill_label": "b",
            "amount_ngn": 8000, "status": "pending", "created_at": "2026-11-03T00:00:00Z",
        })
        self.assertLessEqual(floats.available(), 2000)
        with self.assertRaises(ApiError):
            floats.ensure_can_cover(5000)

    def test_balance_reads_are_cached(self):
        floats = self.floats()
        floats.balance()
        floats.balance()
        self.assertEqual(self.flutterwave.reads, 1)
        floats.balance(fresh=True)
        self.assertEqual(self.flutterwave.reads, 2)


# --- a purchase: float, vault, vendor, refund ------------------------------------------


class ScriptedGateway:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.bought = 0

    def buy(self, bill, amount, request_id):
        self.bought += 1
        return self.outcomes.pop(0)

    def requery(self, request_id, amount, *, token_required):
        return self.outcomes.pop(0)


class PaymentPathTests(MoneyCase):
    balance = 64_200

    def service(self, gateway, *, float_balance=500_000):
        live = FakeFlutterwave(float_balance)
        live.test_mode = False
        floats = FloatService(self.db, live, FloatSettings(100_000))
        return payment_service.PaymentService(self.receipts, gateway, vaults=self.vaults,
                                              floats=floats)

    def test_a_delivery_carries_the_vault_tx_and_charges_once(self):
        gateway = ScriptedGateway(vending.VendingOutcome(status=vending.DELIVERED, token="1234"))
        receipt = self.service(gateway).pay(self.account.id, ELECTRICITY, 5000)
        self.assertEqual(receipt["tx_hash"], "cd" * 32)
        self.assertEqual(self.wallet()["balance_ngn"], 59_200)
        self.assertEqual(self.chain.methods()[-1], "pay")

    def test_a_vendor_failure_refunds_the_vault(self):
        gateway = ScriptedGateway(vending.VendingOutcome(status=vending.FAILED, code="016",
                                                         message="bad meter"))
        with self.assertRaises(payment_service.SpendError):
            self.service(gateway).pay(self.account.id, ELECTRICITY, 5000)
        self.assertEqual(self.chain.calls[-1][0], "refund")
        self.assertEqual(self.wallet()["balance_ngn"], 64_200)

    def test_a_low_float_refuses_before_signing_or_recording(self):
        gateway = ScriptedGateway()
        with self.assertRaises(ApiError) as caught:
            self.service(gateway, float_balance=1000).pay(self.account.id, ELECTRICITY, 5000)
        self.assertEqual(caught.exception.code, "float_low")
        self.assertNotIn("pay", self.chain.methods())
        self.assertEqual(gateway.bought, 0)
        self.assertEqual(self.receipts.count(self.account.id), 0)

    def test_a_vault_refusal_stops_the_purchase(self):
        self.vaults.ensure(self.account.id)
        self.vaults.flush(self.account.id)
        self.chain.fail_with = near_tx.ContractRefused("That meter isn't on your list.")
        gateway = ScriptedGateway()
        with self.assertRaises(payment_service.SpendError) as caught:
            self.service(gateway).pay(self.account.id, ELECTRICITY, 5000)
        self.assertEqual(caught.exception.code, payment_service.AUTHORISATION_FAILED)
        self.assertEqual(gateway.bought, 0)
        self.assertEqual(self.receipts.count(self.account.id), 0)
        self.assertEqual(self.wallet()["balance_ngn"], 64_200)

    def test_a_retry_of_a_pending_purchase_does_not_sign_again(self):
        gateway = ScriptedGateway(
            vending.VendingOutcome(status=vending.PENDING, vendor_ref="CF-1"),
            vending.VendingOutcome(status=vending.DELIVERED, token="1234"),
        )
        service = self.service(gateway)
        service.pay(self.account.id, ELECTRICITY, 5000)
        service.pay(self.account.id, ELECTRICITY, 5000)
        self.assertEqual(self.chain.methods().count("pay"), 1)
        self.assertEqual(self.wallet()["balance_ngn"], 59_200)


# --- deposits ---------------------------------------------------------------------------


class DepositTests(MoneyCase):
    def deposits(self, *, crypto=True, rate=RATE_1500):
        self.flutterwave = FakeFlutterwave()
        self.one_click = FakeOneClick()
        settings = FundingSettings(app_url="https://app.test",
                                   treasury_account="stark-treasury.near" if crypto else None,
                                   usdc_rate=rate, card_hold_hours=CARD_HOLD_HOURS)
        return DepositService(self.db, self.receipts, self.vaults, self.flutterwave,
                              self.one_click, settings)

    def test_a_bank_deposit_is_a_checkout_with_our_reference(self):
        deposit = self.deposits().start(self.account.id, 20_000, "bank", None)
        self.assertEqual(deposit["status"], "open")
        self.assertTrue(deposit["pay"]["checkout_url"].startswith("https://checkout"))
        checkout = self.flutterwave.checkouts[deposit["id"]]
        self.assertEqual(checkout["meta"]["deposit_id"], deposit["id"])
        self.assertEqual(checkout["redirect_url"],
                         f"https://app.test/wallet/add?deposit={deposit['id']}")
        self.assertEqual(checkout["email"], f"{self.account.id}@test.invalid")

    def test_the_webhook_credits_once_after_verifying(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "bank", None)
        service.on_charge(deposit["id"])  # not paid yet: verify finds nothing
        self.assertEqual(self.wallet()["balance_ngn"], 0)
        self.flutterwave.pay(deposit["id"], 20_000)
        service.on_charge(deposit["id"])
        service.on_charge(deposit["id"])
        self.assertEqual(self.wallet()["balance_ngn"], 20_000)
        self.assertEqual(service.get(self.account.id, deposit["id"])["status"], "credited")
        self.assertEqual(len(self.chain.deposits()), 1)

    def make_due(self, *deposits):
        for deposit in deposits:
            self.db.query("UPDATE deposits SET next_check_at = '2000-01-01T00:00:00Z'"
                          " WHERE id = $1", [deposit["id"]])

    def test_a_missed_webhook_is_caught_when_the_check_comes_due(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "bank", None)
        self.flutterwave.pay(deposit["id"], 20_000)
        service.check_due()
        self.assertEqual(self.wallet()["balance_ngn"], 0, "not due yet")
        self.make_due(deposit)
        service.check_due()
        service.on_charge(deposit["id"])
        self.assertEqual(self.wallet()["balance_ngn"], 20_000)

    def test_an_unpaid_deposit_is_checked_less_often_as_it_ages(self):
        self.assertEqual(_check_delay(Clock.now_iso()), MIN_CHECK_SECONDS)
        hour_old = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(_check_delay(hour_old), MAX_CHECK_SECONDS)

    def test_a_settled_deposit_leaves_nothing_due(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "bank", None)
        self.assertLessEqual(service.check_due(), MIN_CHECK_SECONDS)
        self.flutterwave.pay(deposit["id"], 20_000)
        service.on_charge(deposit["id"])
        self.make_due(deposit)
        due = self.db.one("SELECT 1 AS due FROM deposits WHERE id = $1"
                          " AND status IN ('open', 'confirming')", [deposit["id"]])
        self.assertIsNone(due)

    def test_sending_the_tx_brings_the_check_forward(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "crypto", "nep141:tron-usdt")
        self.make_due(deposit)
        service.check_due()
        service.submit_tx(self.account.id, deposit["id"], "0xabc")
        self.assertLessEqual(service.check_due(), SOON_SECONDS)

    def test_a_short_or_foreign_charge_is_not_credited(self):
        service = self.deposits()
        short = service.start(self.account.id, 20_000, "bank", None)
        self.flutterwave.pay(short["id"], 19_999)
        foreign = service.start(self.account.id, 20_000, "bank", None)
        self.flutterwave.pay(foreign["id"], 20_000, currency="USD")
        self.make_due(short, foreign)
        service.check_due()
        self.assertEqual(self.wallet()["balance_ngn"], 0)

    def test_a_failed_charge_marks_the_deposit_failed(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "bank", None)
        self.flutterwave.pay(deposit["id"], 20_000, status="failed")
        self.assertEqual(service.get(self.account.id, deposit["id"])["status"], "failed")
        self.assertEqual(self.wallet()["balance_ngn"], 0)

    def test_a_crypto_quote_covers_the_naira_at_the_locked_rate(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "crypto", "nep141:tron-usdt")
        self.assertEqual(self.one_click.quotes[0]["amount"], 13_333_334, "rounded up")
        self.assertEqual(self.one_click.quotes[0]["recipient"], "stark-treasury.near")
        self.assertEqual(deposit["pay"]["address"], "TXdeposit1")
        self.assertEqual(deposit["pay"]["amount"], "13.46")

    def test_a_crypto_deposit_locks_starks_buying_rate(self):
        deposit = self.deposits(rate=SPREAD_RATE).start(self.account.id, 20_000, "crypto",
                                                        "nep141:tron-usdt")
        # ₦20,000 at ₦1,490 (market ₦1,500 less ₦10) is 13.422819 USDC, rounded up.
        self.assertEqual(self.one_click.quotes[0]["amount"], 13_422_819)
        self.assertEqual(self.db.value("SELECT rate_ngn_per_usdc FROM deposits WHERE id = $1",
                                       [deposit["id"]]), "1490")

    def test_a_preview_from_the_naira_side_reserves_nothing(self):
        preview = self.deposits().preview("nep141:tron-usdt", 20_000, None)
        self.assertEqual(preview["amount_in"], "13.46")
        self.assertEqual(preview["amount_ngn"], 20_000)
        quote = self.one_click.quotes[0]
        self.assertEqual((quote["swap_type"], quote["amount"], quote["dry"]),
                         ("EXACT_OUTPUT", 13_333_334, True))
        self.assertIsNone(self.db.value("SELECT id FROM deposits WHERE user_id = $1",
                                        [self.account.id]))

    def test_a_preview_from_the_crypto_side_credits_what_the_swap_yields(self):
        preview = self.deposits().preview("nep141:tron-usdt", None, Decimal("13.46"))
        quote = self.one_click.quotes[0]
        self.assertEqual((quote["swap_type"], quote["amount"]), ("EXACT_INPUT", 13_460_000))
        # At most 1% slippage: 14.553 USDC is the least that arrives, at ₦1,500.
        self.assertEqual(preview["amount_ngn"], 21_829)

    def test_the_amount_to_send_rounds_up_to_a_cent(self):
        sol = {"decimals": 9, "price": 82.93}
        self.assertEqual(_payable("13285316", sol), "0.0133")
        self.assertEqual(_payable("13300000", sol), "0.0133", "already on the step")
        self.assertEqual(_payable("109351234", {"decimals": 8, "price": 100_000}), "1.0935124")
        self.assertEqual(_payable("13460001", {"decimals": 6, "price": 1}), "13.47")
        self.assertEqual(_payable("13460001", {"decimals": 6}), "13.460001", "no price")

    def test_one_clicks_minimum_is_named_in_naira(self):
        service = self.deposits()
        self.one_click.refuse = OneClickError(
            400, '{"message":"Temporary swap limits: minimum swap amount is $100"}')
        with self.assertRaises(ApiError) as caught:
            service.preview("nep141:tron-usdt", 20_000, None)
        self.assertEqual(caught.exception.code, "below_minimum")
        self.assertIn("₦150,000", str(caught.exception.message))

    def test_no_rate_means_no_crypto_quote(self):
        with self.assertRaises(ApiError) as caught:
            self.deposits(rate=DownRate()).start(self.account.id, 20_000, "crypto",
                                                 "nep141:tron-usdt")
        self.assertEqual(caught.exception.code, "provider_failed")
        self.assertEqual(self.one_click.quotes, [])

    def test_a_settled_swap_credits_no_more_than_was_asked(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "crypto", "nep141:tron-usdt")
        self.one_click.status_reply = {"status": "SUCCESS",
                                       "swapDetails": {"amountOut": "13333334"}}
        self.assertEqual(service.get(self.account.id, deposit["id"])["credited_ngn"], 20_000)
        self.assertEqual(self.wallet()["balance_ngn"], 20_000)

    def test_a_short_swap_credits_what_arrived(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "crypto", "nep141:tron-usdt")
        self.one_click.status_reply = {"status": "SUCCESS",
                                       "swapDetails": {"amountOut": "10000000"}}
        self.assertEqual(service.get(self.account.id, deposit["id"])["credited_ngn"], 15_000)

    def test_a_swap_in_progress_reads_confirming(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "crypto", "nep141:tron-usdt")
        self.one_click.status_reply = {"status": "PROCESSING", "swapDetails": {}}
        self.assertEqual(service.get(self.account.id, deposit["id"])["status"], "confirming")
        self.assertEqual(self.wallet()["balance_ngn"], 0)

    def test_reading_a_deposit_asks_the_rail_at_most_every_few_seconds(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "crypto", "nep141:tron-usdt")
        for _ in range(3):
            self.assertEqual(service.get(self.account.id, deposit["id"])["status"], "open")
        self.assertEqual(self.one_click.status_reads, 1)
        self.db.query("UPDATE deposits SET checked_at = $2 WHERE id = $1",
                      [deposit["id"], Clock.ago(minutes=1)])
        service.get(self.account.id, deposit["id"])
        self.assertEqual(self.one_click.status_reads, 2)

    def test_a_refunded_swap_credits_nothing(self):
        service = self.deposits()
        deposit = service.start(self.account.id, 20_000, "crypto", "nep141:tron-usdt")
        self.one_click.status_reply = {"status": "REFUNDED",
                                       "swapDetails": {"refundReason": "PARTIAL_DEPOSIT"}}
        result = service.get(self.account.id, deposit["id"])
        self.assertEqual(result["status"], "refunded")
        self.assertEqual(result["note"], "PARTIAL_DEPOSIT")
        self.assertEqual(self.wallet()["balance_ngn"], 0)

    def test_refusals(self):
        service = self.deposits(crypto=False)
        for args, code in (
            ((50, "bank", None), "bad_amount"),
            ((20_000, "cash", None), "bad_method"),
            ((20_000, "crypto", "x"), "not_available"),
        ):
            with self.assertRaises(ApiError) as caught:
                service.start(self.account.id, *args)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ApiError) as caught:
            self.deposits().start(self.account.id, 20_000, "crypto", "nep141:unknown")
        self.assertEqual(caught.exception.code, "bad_asset")
        no_flutterwave = DepositService(self.db, self.receipts, self.vaults, None,
                                        FakeOneClick(),
                                        FundingSettings(None, None, RATE_1500, CARD_HOLD_HOURS))
        with self.assertRaises(ApiError) as caught:
            no_flutterwave.start(self.account.id, 20_000, "bank", None)
        self.assertEqual(caught.exception.code, "not_available")


# --- withdrawals -----------------------------------------------------------------------


class WithdrawalTests(MoneyCase):
    balance = 50_000

    def withdrawals(self, settings=OPEN_WITHDRAWALS):
        self.flutterwave = FakeFlutterwave()
        return self.ledger(self.flutterwave, settings)

    def test_money_is_held_at_once_and_sent_with_our_reference(self):
        service = self.withdrawals()
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        self.assertEqual(result["status"], "processing")
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)
        self.assertIn(("debit", {"amount_usdc": "6666670", "reference": result["id"]}),
                      self.chain.calls)
        self.assertEqual(self.flutterwave.transfers[0]["reference"], result["id"])
        entry = self.receipts.recent(self.account.id, 1)[0]
        self.assertEqual(entry["source"], "Guaranty Trust Bank ····6789")

    def test_a_timeout_is_resent_with_the_same_reference(self):
        service = self.withdrawals()
        self.flutterwave.transfer_error = FlutterwaveError(0, "unreachable")
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        self.assertEqual(result["status"], "sending")
        self.flutterwave.transfer_error = None
        service.advance()
        self.assertEqual(service.recent(self.account.id)[0]["status"], "processing")
        self.assertEqual([t["reference"] for t in self.flutterwave.transfers], [result["id"]])

    def test_a_transfer_that_went_through_is_never_sent_again(self):
        service = self.withdrawals()
        self.flutterwave.transfer_error = FlutterwaveError(0, "timed out")
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        self.flutterwave.transfer_error = None
        self.flutterwave.transfers.append({"id": 77, "status": "NEW",
                                           "reference": result["id"]})
        service.advance()
        self.assertEqual(len(self.flutterwave.transfers), 1)
        self.assertEqual(service.recent(self.account.id)[0]["status"], "processing")
        self.flutterwave.transfer_status[result["id"]] = "SUCCESSFUL"
        service.advance()
        self.assertEqual(service.recent(self.account.id)[0]["status"], "paid")

    def test_a_refusal_for_a_transfer_flutterwave_holds_keeps_the_money_out(self):
        service = self.withdrawals()
        self.flutterwave.transfer_error = FlutterwaveError(400, "Wording we have not seen")
        answers = iter([None, {"id": 77, "status": "NEW"}])
        self.flutterwave.find_transfer = lambda _reference: next(answers)
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        self.assertEqual(result["status"], "processing")
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)

    def test_a_refusal_keeps_the_money_out_when_flutterwave_cannot_say(self):
        service = self.withdrawals()
        self.flutterwave.transfer_error = FlutterwaveError(400, "Refused")
        calls = []

        def find(_reference):
            calls.append(1)
            if len(calls) > 1:
                raise FlutterwaveError(0, "unreachable")

        self.flutterwave.find_transfer = find
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        self.assertEqual(result["status"], "sending")
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)

    def test_a_success_after_the_money_came_back_is_flagged_and_not_marked_paid(self):
        service = self.withdrawals()
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        service.on_transfer(result["id"], "FAILED", "Account is invalid")
        with self.assertLogs("stark.withdrawals", "CRITICAL"):
            service.on_transfer(result["id"], "SUCCESSFUL", None)
        self.assertEqual(service.recent(self.account.id)[0]["status"], "returned")

    def test_a_refused_transfer_returns_the_money(self):
        service = self.withdrawals()
        self.flutterwave.transfer_error = FlutterwaveError(400, "Insufficient funds")
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        self.assertEqual(result["status"], "returned")
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)

    def test_a_failed_transfer_returns_the_money_once(self):
        service = self.withdrawals()
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        service.on_transfer(result["id"], "FAILED", "Account is invalid")
        service.on_transfer(result["id"], "FAILED", "Account is invalid")
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)
        returned = service.recent(self.account.id)[0]
        self.assertEqual((returned["status"], returned["note"]),
                         ("returned", "Account is invalid"))
        self.assertEqual(len(self.chain.deposits()), 1)

    def test_a_missed_webhook_is_caught_by_the_poll(self):
        service = self.withdrawals()
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        service.advance()
        self.assertEqual(service.recent(self.account.id)[0]["status"], "processing")
        self.flutterwave.transfer_status[result["id"]] = "SUCCESSFUL"
        service.advance()
        self.assertEqual(service.recent(self.account.id)[0]["status"], "paid")

    def test_a_paid_transfer_is_final(self):
        service = self.withdrawals()
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        self.assertTrue(service.on_transfer(result["id"], "SUCCESSFUL", None))
        self.assertEqual(service.recent(self.account.id)[0]["status"], "paid")
        self.assertFalse(service.on_transfer("wd_not_ours", "SUCCESSFUL", None))

    def test_refusals_take_nothing(self):
        service = self.withdrawals()
        for args, code in (
            ((10_000, "058", "123"), "bad_account"),
            ((50, "058", "0123456789"), "bad_amount"),
            ((90_000, "058", "0123456789"), "insufficient_balance"),
        ):
            with self.assertRaises(ApiError) as caught:
                service.request(self.account.id, *args)
            self.assertEqual(caught.exception.code, code)
        self.flutterwave.resolved = False
        with self.assertRaises(ApiError) as caught:
            service.request(self.account.id, 10_000, "058", "0123456789")
        self.assertEqual(caught.exception.code, "bad_account")
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)
        self.assertEqual(service.recent(self.account.id), [], "no row is left behind")

    def test_a_failure_after_the_transfer_was_paid_returns_nothing(self):
        service = self.withdrawals()
        result = service.request(self.account.id, 10_000, "058", "0123456789")
        service.on_transfer(result["id"], "SUCCESSFUL", None)
        with self.assertLogs("stark.withdrawals", "CRITICAL"):
            service.on_transfer(result["id"], "FAILED", "Reversed")
        self.assertEqual(service.recent(self.account.id)[0]["status"], "paid")
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)
        self.assertEqual(self.chain.deposits(), [])

    def test_a_paused_account_withdraws_nothing(self):
        service = self.withdrawals()
        self.pause()
        with self.assertRaises(ApiError) as caught:
            service.request(self.account.id, 10_000, "058", "0123456789")
        self.assertEqual((caught.exception.status, caught.exception.code), (423, "paused"))
        self.assertEqual(self.flutterwave.transfers, [])
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)

    def test_the_daily_bank_limit_is_per_account_and_counts_what_was_not_returned(self):
        service = self.withdrawals(WithdrawalSettings(daily_ngn=25_000, lookups_per_day=20))
        first = service.request(self.account.id, 10_000, "058", "0123456789")
        with self.assertRaises(ApiError) as caught:
            service.request(self.account.id, 20_000, "058", "0123456789")
        self.assertEqual(caught.exception.code, "daily_limit")
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)
        service.on_transfer(first["id"], "FAILED", "Account is invalid")
        service.request(self.account.id, 20_000, "058", "0123456789")
        self.assertEqual(self.wallet()["balance_ngn"], 30_000)

    def test_the_hold_and_the_withdrawal_row_are_written_together(self):
        service = self.withdrawals()
        withdrawal = {"id": "wd_together_" + self.account.id[-8:], "user_id": self.account.id,
                      "method": "bank", "amount_ngn": 10_000, "bank_code": "058",
                      "account_number": "0123456789", "account_name": "ADA OKAFOR",
                      "bank_name": "Guaranty Trust Bank", "status": "sending",
                      "created_at": Clock.now_iso(), "updated_at": Clock.now_iso()}
        service.hold(self.account.id, withdrawal, label="To ADA OKAFOR", source="GTB",
                     vendor="flutterwave")
        row = service._row(withdrawal["id"])
        entry = self.receipts.by_request_id(self.account.id, withdrawal["id"])
        self.assertEqual(row["receipt_id"], entry["id"])
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)
        # The crash this guards against: held, then nothing sent. The next send
        # debits the vault before anything else.
        self.assertNotIn(withdrawal["id"], [c[1].get("reference") for c in self.chain.calls
                                            if c[0] == "debit"])
        service._send(row)
        self.assertIn(withdrawal["id"], [c[1]["reference"] for c in self.chain.calls
                                         if c[0] == "debit"])

    def test_name_lookups_are_limited_per_account(self):
        service = self.withdrawals(WithdrawalSettings(daily_ngn=10**12, lookups_per_day=2))
        for _ in range(2):
            service.lookup(self.account.id, "058", "0123456789")
        with self.assertRaises(ApiError) as caught:
            service.lookup(self.account.id, "058", "0123456789")
        self.assertEqual((caught.exception.status, caught.exception.code),
                         (429, "too_many_lookups"))
        self.assertEqual(self.flutterwave.resolves, 2)
        # A typo never reaches Flutterwave, so it does not count.
        with self.assertRaises(ApiError) as caught:
            service.lookup(self.account.id, "058", "123")
        self.assertEqual(caught.exception.code, "bad_account")
        # Sending money still resolves the account it pays.
        service.request(self.account.id, 1_000, "058", "0123456789")
        self.assertEqual(self.flutterwave.resolves, 3)


class CardHoldTests(MoneyCase):
    """A card charge can be disputed after the money has left, so it pays bills at
    once but cannot be withdrawn until its hold passes."""

    def setUp(self):
        super().setUp()
        self.flutterwave = FakeFlutterwave()
        self.deposits = DepositService(
            self.db, self.receipts, self.vaults, self.flutterwave, FakeOneClick(),
            FundingSettings("https://app.test", None, RATE_1500, CARD_HOLD_HOURS))
        self.withdrawals = self.ledger(self.flutterwave)

    def add(self, amount, payment_type):
        deposit = self.deposits.start(self.account.id, amount, "bank", None)
        self.flutterwave.pay(deposit["id"], amount, payment_type=payment_type)
        self.deposits.on_charge(deposit["id"])
        return deposit

    def withdraw(self, amount):
        return self.withdrawals.request(self.account.id, amount, "058", "0123456789")

    def test_card_money_is_spendable_but_not_withdrawable(self):
        deposit = self.add(20_000, "card")
        self.assertEqual(self.wallet()["balance_ngn"], 20_000)
        hold_until = self.db.value("SELECT hold_until FROM deposits WHERE id = $1",
                                   [deposit["id"]])
        self.assertGreater(hold_until, Clock.in_minutes(CARD_HOLD_HOURS * 60 - 1))
        with self.assertRaises(ApiError) as caught:
            self.withdraw(5_000)
        self.assertEqual(caught.exception.code, "funds_on_hold")
        self.assertEqual(self.wallet()["balance_ngn"], 20_000)
        # A bill spends it all the same.
        self.receipts.record_debit(self.account.id, {
            "id": "rcpt_bill01", "request_id": "bill-req-1", "bill_id": "bill_home",
            "bill_label": "Home meter", "meter": METER, "amount_ngn": 5_000, "units": None,
            "token": None, "tx_hash": None, "status": "pending", "entry_type": "bill",
            "source": None, "vendor": None, "vendor_code": None, "vendor_message": None,
            "created_at": Clock.now_iso(),
        }, 5_000)
        self.assertEqual(self.wallet()["balance_ngn"], 15_000)

    def test_only_money_beyond_the_hold_can_leave(self):
        self.add(20_000, "card")
        self.add(10_000, "bank_transfer")
        with self.assertRaises(ApiError) as caught:
            self.withdraw(15_000)
        self.assertEqual(caught.exception.code, "funds_on_hold")
        self.assertIn("₦10,000", caught.exception.message)
        self.withdraw(10_000)
        self.assertEqual(self.wallet()["balance_ngn"], 20_000)

    def test_an_unknown_payment_type_is_held_like_a_card(self):
        self.add(20_000, "applepay")
        with self.assertRaises(ApiError) as caught:
            self.withdraw(5_000)
        self.assertEqual(caught.exception.code, "funds_on_hold")

    def test_card_money_can_leave_once_the_hold_passes(self):
        deposit = self.add(20_000, "card")
        self.db.query("UPDATE deposits SET hold_until = $2 WHERE id = $1",
                      [deposit["id"], Clock.ago(minutes=1)])
        self.withdraw(5_000)
        self.assertEqual(self.wallet()["balance_ngn"], 15_000)

    def test_a_short_balance_is_still_insufficient_not_on_hold(self):
        self.add(20_000, "card")
        with self.assertRaises(ApiError) as caught:
            self.withdraw(30_000)
        self.assertEqual(caught.exception.code, "insufficient_balance")


# --- crypto withdrawals -------------------------------------------------------------------


class FakeTreasury:
    """The treasury's hot key, faked at the chain: signs, sends, reports outcomes."""

    account_id = "stark-treasury.near"

    def __init__(self):
        self.signed: list[tuple[str, int]] = []
        self.sent: list[str] = []
        self.send_error: Exception | None = None
        self.landed: dict | None = None

    def sign_usdc_transfer(self, receiver_id, amount):
        self.signed.append((receiver_id, amount))
        n = len(self.signed)
        return SignedTransfer(f"signed-{n}", f"hash{n}")

    def send(self, transfer):
        self.sent.append(transfer.encoded)
        if self.send_error is not None:
            err, self.send_error = self.send_error, None
            raise err

    def outcome(self, transfer):
        return self.landed


class FakePayoutOneClick(FakeOneClick):
    def __init__(self):
        super().__init__()
        self.payout_quotes: list[dict] = []
        self.quote_error: OneClickError | None = None
        self.submitted: list[str] = []

    def quote_withdrawal(self, *, destination_asset, usdc_in, recipient, treasury, deadline):
        if self.quote_error is not None:
            raise self.quote_error
        self.payout_quotes.append({"asset": destination_asset, "usdc_in": usdc_in,
                                   "recipient": recipient, "treasury": treasury})
        return {"quote": {"depositAddress": "a1b2" * 16, "amountOutFormatted": "13.21",
                          "deadline": deadline}}

    def submit_deposit(self, address, tx_hash, memo):
        self.submitted.append(tx_hash)
        return self.status_reply


LANDED = {"status": {"SuccessValue": ""}}
ADDRESS = "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE"


class CryptoWithdrawalTests(MoneyCase):
    balance = 50_000

    def service(self, *, treasury=True, max_ngn=200_000, max_usdc=Decimal(10**6),
                daily_ngn=10**12, user_daily_ngn=10**12, rate=RATE_1500, sandbox_naira=False):
        self.one_click = FakePayoutOneClick()
        self.treasury = FakeTreasury() if treasury else None
        deposits = DepositService(
            self.db, self.receipts, self.vaults, None, self.one_click,
            FundingSettings(None, "stark-treasury.near", RATE_1500, CARD_HOLD_HOURS))
        self.payouts = CryptoWithdrawalService(
            self.db, self.ledger(None), self.vaults, deposits, self.one_click, self.treasury,
            CryptoPayoutSettings(rate, max_ngn, max_usdc, daily_ngn, user_daily_ngn),
            sandbox_naira=sandbox_naira,
        )
        return self.payouts

    def request(self, amount=20_000, asset="nep141:tron-usdt", address=ADDRESS):
        return self.payouts.request(self.account.id, amount, asset, address)

    def test_money_is_held_converted_down_and_sent_once(self):
        self.service()
        result = self.request()
        self.assertEqual(result["method"], "crypto")
        self.assertEqual(result["status"], "processing")
        self.assertEqual(result["crypto"], {"asset": "USDT", "chain": "tron",
                                            "address": ADDRESS, "amount": "13.21",
                                            "tx_hash": "hash1"})
        self.assertEqual(self.wallet()["balance_ngn"], 30_000)
        # ₦20,000 at ₦1,500 is 13.333333 USDC: rounded down, never up.
        self.assertEqual(self.one_click.payout_quotes[0],
                         {"asset": "nep141:tron-usdt", "usdc_in": 13_333_333,
                          "recipient": ADDRESS, "treasury": "stark-treasury.near"})
        self.assertEqual(self.treasury.signed, [("a1b2" * 16, 13_333_333)])
        self.assertEqual(self.one_click.submitted, ["hash1"])
        self.assertIn(("debit", {"amount_usdc": "13333340", "reference": result["id"]}),
                      self.chain.calls)

    def test_a_withdrawal_is_priced_at_starks_selling_rate(self):
        self.service(rate=SPREAD_RATE)
        self.request()
        # ₦20,000 at ₦1,510 (market ₦1,500 plus ₦10) is 13.245033 USDC, rounded down.
        self.assertEqual(self.one_click.payout_quotes[0]["usdc_in"], 13_245_033)

    def test_no_rate_means_nothing_is_held(self):
        self.service(rate=DownRate())
        with self.assertRaises(ApiError) as caught:
            self.request()
        self.assertEqual(caught.exception.code, "provider_failed")
        self.assertEqual(self.wallet()["balance_ngn"], self.balance)
        self.assertEqual(self.one_click.payout_quotes, [])

    def test_a_settled_swap_is_paid_with_what_arrived(self):
        self.service()
        self.request()
        self.one_click.status_reply = {"status": "SUCCESS",
                                       "swapDetails": {"amountOutFormatted": "13.19"}}
        self.payouts.advance()
        latest = self.payouts.ledger.recent(self.account.id)[0]
        self.assertEqual(latest["status"], "paid")
        self.assertEqual(latest["crypto"]["amount"], "13.19")
        self.assertEqual(self.wallet()["balance_ngn"], 30_000)

    def test_a_refunded_swap_returns_the_money_once(self):
        self.service()
        result = self.request()
        self.one_click.status_reply = {"status": "REFUNDED",
                                       "swapDetails": {"refundReason": "no liquidity"}}
        self.payouts.advance()
        self.payouts.advance()
        latest = self.payouts.ledger.recent(self.account.id)[0]
        self.assertEqual(latest["status"], "returned")
        self.assertEqual(latest["note"], "no liquidity")
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)
        self.assertEqual(self.chain.deposits(),
                         [("fund", {"amount_usdc": 13_333_340, "reference": f"{result['id']}-r"})])

    def test_a_timeout_that_landed_is_not_sent_again(self):
        self.service()
        self.treasury.send_error = near_tx.NearRpcError("timeout")
        self.treasury.landed = LANDED
        result = self.request()
        self.assertEqual(result["status"], "processing")
        self.assertEqual(len(self.treasury.signed), 1)
        self.assertEqual(len(self.treasury.sent), 1)

    def test_a_timeout_the_chain_never_saw_resends_the_same_bytes(self):
        self.service()
        self.treasury.send_error = near_tx.NearRpcError("timeout")
        result = self.request()
        self.assertEqual(result["status"], "sending")
        self.payouts.advance()
        self.assertEqual(self.treasury.signed, [("a1b2" * 16, 13_333_333)])
        self.assertEqual(self.treasury.sent, ["signed-1", "signed-1"])
        self.assertEqual(self.payouts.ledger.recent(self.account.id)[0]["status"],
                         "processing")

    def test_an_expired_transaction_is_signed_afresh(self):
        self.service()
        self.treasury.send_error = near_tx.NearRpcError("tx rejected",
                                                        {"data": "Expired"})
        self.request()
        self.payouts.advance()
        self.assertEqual(len(self.treasury.signed), 2)
        self.assertEqual(self.treasury.sent, ["signed-1", "signed-2"])

    def test_a_refused_transfer_returns_the_money(self):
        self.service()
        self.treasury.send_error = near_tx.ContractRefused("The account doesn't have "
                                                           "enough balance")
        result = self.request()
        self.assertEqual(result["status"], "returned")
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)

    def test_refusals_take_nothing(self):
        self.service()
        for args, code in (
            ({"amount": 500}, "bad_amount"),
            ({"amount": 300_000}, "over_limit"),
            ({"asset": "nep141:unknown"}, "bad_asset"),
            ({"address": "not an address"}, "bad_address"),
            ({"amount": 60_000}, "insufficient_balance"),
        ):
            with self.assertRaises(ApiError) as caught:
                self.request(**args)
            self.assertEqual(caught.exception.code, code)
        self.one_click.quote_error = OneClickError(400, "recipient is not a valid address")
        with self.assertRaises(ApiError) as caught:
            self.request()
        self.assertEqual(caught.exception.code, "bad_address")
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)
        self.assertEqual(self.treasury.signed, [])

    def test_without_a_treasury_key_it_is_not_available(self):
        self.service(treasury=False)
        self.assertFalse(self.payouts.available())
        with self.assertRaises(ApiError) as caught:
            self.request()
        self.assertEqual(caught.exception.code, "not_available")
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)

    def test_naira_from_a_test_key_never_becomes_real_usdc(self):
        # A Flutterwave test key credits checkouts nobody paid for.
        self.service(sandbox_naira=True)
        self.assertFalse(self.payouts.available())
        with self.assertRaises(ApiError) as caught:
            self.request()
        self.assertEqual(caught.exception.code, "not_available")
        self.assertEqual(self.treasury.signed, [])
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)

    def test_the_daily_limit_counts_what_was_not_returned(self):
        baseline, _ = self.service()._sent_today(self.account.id)
        self.service(daily_ngn=baseline + 25_000)
        self.request(10_000)
        with self.assertRaises(ApiError) as caught:
            self.request(20_000)
        self.assertEqual(caught.exception.code, "daily_limit")
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)

    def test_one_account_cannot_use_up_the_day_for_everyone(self):
        self.service(user_daily_ngn=25_000)
        self.request(10_000)
        with self.assertRaises(ApiError) as caught:
            self.request(20_000)
        self.assertEqual(caught.exception.code, "daily_limit")
        self.assertIn("₦25,000", caught.exception.message)
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)
        # Someone else still has their whole day.
        other = support.TempAccount(db=self.db)
        try:
            self.receipts.set_wallet(other.id, 30_000, 0)
            self.payouts.request(other.id, 20_000, "nep141:tron-usdt", ADDRESS)
            self.assertEqual(self.receipts.wallet(other.id)["balance_ngn"], 10_000)
        finally:
            other.close()

    def test_a_bad_rate_cannot_multiply_the_usdc_sent(self):
        # ₦20,000 should be ~13 USDC; at a rate of ₦15 it would be 1,333.
        self.service(rate=UsdcRate(spread_ngn=Decimal(0), fixed=Decimal(15)),
                     max_usdc=Decimal(200))
        with self.assertRaises(ApiError) as caught:
            self.request()
        self.assertEqual(caught.exception.code, "over_limit")
        self.assertEqual(self.one_click.payout_quotes, [])
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)

    def test_a_paused_account_sends_nothing(self):
        self.service()
        self.pause()
        with self.assertRaises(ApiError) as caught:
            self.request()
        self.assertEqual((caught.exception.status, caught.exception.code), (423, "paused"))
        self.assertEqual(self.treasury.signed, [])
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)

    def test_a_crash_before_the_vault_debit_is_caught_up_on_the_next_pass(self):
        self.service()
        self.treasury.send_error = near_tx.NearRpcError("timeout")
        result = self.request()
        self.db.query("DELETE FROM chain_ops WHERE id = $1", [f"debit:{result['id']}"])
        self.chain.calls.clear()
        # One row, not `advance()`: the shared database holds other tests' rows too.
        self.payouts._send(self.payouts._row(result["id"]))
        self.assertIn(result["id"], [c[1]["reference"] for c in self.chain.calls
                                     if c[0] == "debit"])


# --- the webhook ---------------------------------------------------------------------------


class ScriptedRate(UsdcRate):
    """Paycrest answering from a list, one rate per fetch."""

    def __init__(self, *answers, spread_ngn=Decimal(10)):
        super().__init__(spread_ngn=spread_ngn)
        self.answers = list(answers)

    def _fetch(self):
        return Decimal(self.answers.pop(0))

    def age(self, seconds):
        """Pretend the accepted rate was fetched `seconds` ago."""
        self._fetched_at = time.monotonic() - seconds


class UsdcRateBoundsTests(unittest.TestCase):
    def test_a_rate_outside_the_range_is_never_used(self):
        for wild in ("1.38", "138056"):
            with self.assertLogs("stark.rate", "ERROR"), self.assertRaises(RateUnavailable):
                ScriptedRate(wild).market()

    def test_a_jump_keeps_the_last_good_rate_then_refuses(self):
        rate = ScriptedRate("1500", "3000", "3000")
        self.assertEqual(rate.market(), Decimal(1500))
        rate.age(120)
        with self.assertLogs("stark.rate", "ERROR"):
            self.assertEqual(rate.market(), Decimal(1500), "the last good rate, still fresh")
        rate.age(STALE_SECONDS + 1)
        with self.assertLogs("stark.rate", "ERROR"), self.assertRaises(RateUnavailable):
            rate.market()

    def test_a_move_within_the_limit_is_taken(self):
        rate = ScriptedRate("1500", "1650")
        rate.market()
        rate.age(120)
        self.assertEqual(rate.market(), Decimal(1650))

    def test_a_spread_that_leaves_no_price_is_refused(self):
        rate = UsdcRate(spread_ngn=Decimal(1500), fixed=Decimal(1500))
        with self.assertRaises(RateUnavailable):
            rate.buying()
        self.assertEqual(rate.selling(), Decimal(3000))

    def test_the_bounds_are_read_from_the_environment(self):
        from app.shared.services.money_config import MoneyConfig
        config = MoneyConfig.from_env({"STARK_USDC_RATE_MIN": "1000",
                                       "STARK_USDC_RATE_MAX": "2000",
                                       "STARK_USDC_RATE_MAX_MOVE": "0.05"})
        usdc = config.funding.usdc_rate
        self.assertEqual((usdc.floor, usdc.ceiling, usdc.max_move),
                         (Decimal(1000), Decimal(2000), Decimal("0.05")))
        self.assertIs(config.crypto_payouts.usdc_rate, usdc)
        self.assertEqual(config.withdrawals, WithdrawalSettings(200_000, 20))
        self.assertEqual((config.crypto_payouts.user_daily_ngn, config.crypto_payouts.max_usdc,
                          config.funding.card_hold_hours), (200_000, Decimal(200), 72))


class FlutterwaveClientTests(unittest.TestCase):
    def test_the_verif_hash_must_match(self):
        self.assertTrue(flutterwave.verify_webhook({"verif-hash": "s3cret"}, "s3cret"))
        self.assertFalse(flutterwave.verify_webhook({"verif-hash": "other"}, "s3cret"))
        self.assertFalse(flutterwave.verify_webhook({}, "s3cret"))
        self.assertFalse(flutterwave.verify_webhook({"verif-hash": ""}, ""))

    def test_amounts_become_whole_naira(self):
        self.assertEqual(flutterwave.whole_naira("11.0000"), 11)
        self.assertEqual(flutterwave.whole_naira(249_700.99), 249_700)

    def test_the_key_is_checked_at_boot(self):
        self.assertIsNone(flutterwave.client_from_env({}))
        self.assertTrue(flutterwave.client_from_env(
            {"FLW_SECRET_KEY": "FLWSECK_TEST-abc-X"}).test_mode)
        self.assertFalse(flutterwave.client_from_env({"FLW_SECRET_KEY": "FLWSECK-abc-X"})
                         .test_mode)
        with self.assertRaises(ValueError):
            flutterwave.client_from_env({"FLW_SECRET_KEY": "sk_live_x"})


class WebhookTests(DepositTests):
    def webhooks(self, deposits):
        self.withdrawals = self.ledger(self.flutterwave)
        return FlutterwaveWebhookService(self.db, "whsec", deposits, self.withdrawals)

    def transfer_event(self, hook, reference, status):
        """Post `transfer.completed` claiming `status`, as anyone with the hash could."""
        event_id = f"{reference}-{status}"
        body = json.dumps({"event": "transfer.completed",
                           "data": {"id": event_id, "reference": reference,
                                    "status": status}}).encode()
        try:
            hook.handle(body, {"verif-hash": "whsec"})
        finally:
            self.db.query("DELETE FROM processed_messages WHERE message_id = $1",
                          [f"transfer.completed:{event_id}"])

    def test_a_transfer_webhook_acts_on_flutterwaves_answer_not_the_body(self):
        hook = self.webhooks(self.deposits())
        self.receipts.set_wallet(self.account.id, 50_000, 0)
        result = self.withdrawals.request(self.account.id, 10_000, "058", "0123456789")
        self.flutterwave.transfer_status[result["id"]] = "SUCCESSFUL"
        self.transfer_event(hook, result["id"], "FAILED")
        self.assertEqual(self.withdrawals.recent(self.account.id)[0]["status"], "paid")
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)
        self.assertEqual(self.flutterwave.lookups[-1], result["id"])

    def test_a_forged_failure_for_a_transfer_still_in_flight_returns_nothing(self):
        hook = self.webhooks(self.deposits())
        self.receipts.set_wallet(self.account.id, 50_000, 0)
        result = self.withdrawals.request(self.account.id, 10_000, "058", "0123456789")
        self.transfer_event(hook, result["id"], "FAILED")
        self.assertEqual(self.withdrawals.recent(self.account.id)[0]["status"], "processing")
        self.assertEqual(self.wallet()["balance_ngn"], 40_000)
        self.flutterwave.transfer_status[result["id"]] = "FAILED"
        self.transfer_event(hook, result["id"], "SUCCESSFUL")
        self.assertEqual(self.withdrawals.recent(self.account.id)[0]["status"], "returned")
        self.assertEqual(self.wallet()["balance_ngn"], 50_000)

    def test_a_charge_credits_and_a_redelivery_does_not(self):
        deposits = self.deposits()
        deposit = deposits.start(self.account.id, 20_000, "bank", None)
        self.flutterwave.pay(deposit["id"], 20_000)
        charge_id = self.flutterwave.charges[deposit["id"]]["id"]
        body = json.dumps({"event": "charge.completed",
                           "data": {"id": charge_id, "tx_ref": deposit["id"],
                                    "status": "successful", "amount": 20_000}}).encode()
        hook = self.webhooks(deposits)
        try:
            self.assertFalse(hook.handle(body, {"verif-hash": "whsec"})["duplicate"])
            self.assertTrue(hook.handle(body, {"verif-hash": "whsec"})["duplicate"])
        finally:
            self.db.query("DELETE FROM processed_messages WHERE message_id = $1",
                          [f"charge.completed:{charge_id}"])
        self.assertEqual(self.wallet()["balance_ngn"], 20_000)

    def test_the_body_alone_never_credits(self):
        deposits = self.deposits()
        deposit = deposits.start(self.account.id, 20_000, "bank", None)
        # Says successful, but Flutterwave's verify has no such charge.
        body = json.dumps({"event": "charge.completed",
                           "data": {"id": 1, "tx_ref": deposit["id"],
                                    "status": "successful", "amount": 20_000}}).encode()
        try:
            self.webhooks(deposits).handle(body, {"verif-hash": "whsec"})
        finally:
            self.db.query("DELETE FROM processed_messages WHERE message_id = $1",
                          ["charge.completed:1"])
        self.assertEqual(self.wallet()["balance_ngn"], 0)

    def test_an_unsigned_or_unconfigured_webhook_is_refused(self):
        body = b'{"event":"charge.completed","data":{}}'
        hook = self.webhooks(self.deposits())
        with self.assertRaises(ApiError) as caught:
            hook.handle(body, {})
        self.assertEqual(caught.exception.code, "webhook_unverified")
        hook.secret_hash = None
        with self.assertRaises(ApiError) as caught:
            hook.handle(body, {"verif-hash": "whsec"})
        self.assertEqual(caught.exception.code, "webhook_unconfigured")


# --- the HTTP surface -------------------------------------------------------------------------


class WalletRouteTests(unittest.TestCase):
    def setUp(self):
        self.account = support.TempAccount()
        self.api = support.ApiHarness(self.account)

    def tearDown(self):
        self.account.close()

    def test_methods_report_what_is_switched_on(self):
        body = self.api.client.get("/v1/wallet/methods").json()
        self.assertEqual(set(body), {"bank", "crypto", "test_money", "withdraw"})
        self.assertEqual(set(body["withdraw"]), {"bank", "crypto"})

    def test_test_money_is_refused_once_a_rail_exists(self):
        self.api.module.wallet.test_money = False
        response = self.api.client.post("/v1/wallet/topup", json={"amount_ngn": 5000})
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["code"], "not_available")

    def test_withdraw_without_flutterwave_is_not_available_and_takes_nothing(self):
        self.api.module.withdrawals.flutterwave = None
        response = self.api.client.post("/v1/wallet/withdraw", json={
            "amount_ngn": 5000, "bank_code": "058", "account_number": "0123456789"})
        self.assertEqual(response.status_code, 501)

    def test_too_many_name_lookups_answer_429(self):
        withdrawals = self.api.module.withdrawals
        withdrawals.flutterwave = FakeFlutterwave()
        withdrawals.settings = WithdrawalSettings(daily_ngn=10**12, lookups_per_day=1)
        body = {"bank_code": "058", "account_number": "0123456789"}
        first = self.api.client.post("/v1/wallet/bank-accounts/resolve", json=body)
        self.assertEqual(first.json()["account_name"], "ADA OKAFOR")
        second = self.api.client.post("/v1/wallet/bank-accounts/resolve", json=body)
        self.assertEqual((second.status_code, second.json()["code"]),
                         (429, "too_many_lookups"))

    def test_the_flutterwave_webhook_refuses_unsigned_requests(self):
        self.api.module.flutterwave_webhooks.secret_hash = "whsec"
        response = self.api.client.post("/v1/flutterwave/webhook", content=b"{}")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
