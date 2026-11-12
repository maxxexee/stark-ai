//! Stark vault — one per user. It holds the user's USDC and enforces their
//! spending rules onchain, so an AI agent holding a function-call key cannot
//! drain it.
//!
//! Each user gets their own vault account (`u-<id>.<parent>`), created by the
//! backend in one transaction: create the account, deploy this code, add the
//! agent's function-call key (scoped to `pay` on this account), call `new`.
//!
//! Three roles, and nobody else can change anything:
//!
//! * **owner** — policy, allowlist, pause, withdraw, hand-over. Starts as Stark's
//!   funder account (users sign in with email and hold no NEAR key) and can be
//!   handed to the user's own account in two steps: the owner `propose_owner`s it,
//!   and the new account takes it with `accept_owner`. A mistyped account id can
//!   never accept, so the vault cannot be handed to nobody.
//! * **funder** — Stark's backend. Sets the naira rate, sends a bank withdrawal's
//!   USDC back to the treasury (`debit`), and deposits USDC with
//!   `ft_transfer_call`, each deposit carrying a reference that is applied once.
//!   Only USDC sent by the funder or the treasury is taken; anyone else's is sent
//!   back without touching state, so strangers cannot fill the vault's storage or
//!   write events into its log.
//! * **agent** — the function-call key on this very account. Its calls arrive with
//!   `predecessor == current_account_id`, and it may only `pay`.
//!
//! Money is USDC (the `usdc` NEP-141 token). Caps are in naira, the unit people
//! budget in, and `pay` converts at `usdc_per_kngn`, which only the funder sets.
//! A paid bill's USDC goes to `treasury`, which pays the biller in naira; if that
//! transfer fails, the payment is reversed before `pay` returns.

mod policy;

pub use policy::{period_key, remaining_cap, Rejection};

use near_sdk::json_types::U128;
use near_sdk::serde_json::{json, Value};
use near_sdk::store::{LookupMap, LookupSet};
use near_sdk::{
    env, near, require, AccountId, BorshStorageKey, Gas, NearToken, PanicOnDefault, Promise,
    PromiseOrValue,
};

/// NEP-297 event standard identifier.
const EVENT_STANDARD: &str = "stark-vault";
const EVENT_VERSION: &str = "3.0";

const FT_TRANSFER_GAS: Gas = Gas::from_tgas(10);
const CALLBACK_GAS: Gas = Gas::from_tgas(10);
const ONE_YOCTO: NearToken = NearToken::from_yoctonear(1);
/// A `ft_transfer_call` whose `msg` starts with this returns a payment's USDC.
const REFUND_PREFIX: &str = "refund:";
/// The longest deposit `msg` taken, in bytes. Every reference is kept forever, so
/// an unbounded one is a storage leak. Stark's longest is `opening:<vault id>`,
/// and an account id is at most 64 bytes.
const MAX_MSG_LEN: usize = 128;
/// Raw storage key for an ownership hand-over in progress. Kept outside the
/// `Vault` struct so vaults already holding state still deserialise once they run
/// this code.
const PENDING_OWNER_KEY: &[u8] = b"pending_owner";

const ERR_OWNER_ONLY: &str = "Only the owner can do that";
const ERR_FUNDER_ONLY: &str = "Only Stark can do that";
const ERR_PAYER_ONLY: &str = "Only Stark's agent or the owner can pay";
const ERR_TOKEN_ONLY: &str = "This vault only holds USDC";
const ERR_NO_BALANCE_MSG: &str = "That's more than the balance";
const ERR_ZERO: &str = "That amount needs to be above zero.";
const ERR_NO_RATE: &str = "The naira rate needs to be above zero";
const ERR_NOT_PROPOSED: &str = "This account has not been offered the vault";

#[near]
#[derive(BorshStorageKey)]
enum StorageKey {
    References,
    Payments,
}

/// What a `pay` booked, kept so a vendor failure can be reversed exactly.
#[near(serializers = [borsh, json])]
#[derive(Clone)]
pub struct PaymentRecord {
    pub meter: String,
    pub amount_ngn: U128,
    pub amount_usdc: U128,
    /// `"YYYY-MM"` the spend was counted in. A refund only gives allowance back
    /// to the month it was taken from.
    pub period_key: String,
    pub refunded: bool,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Vault {
    owner: AccountId,
    funder: AccountId,
    /// Receives each paid bill's USDC, and is the only sender of refunds.
    treasury: AccountId,
    usdc: AccountId,
    /// USDC base units (6 decimals) per ₦1,000.
    usdc_per_kngn: u128,
    paused: bool,
    monthly_cap_ngn: u128,
    per_payment_cap_ngn: u128,
    allowed_meters: Vec<String>,
    /// Spend already booked in `period_key`.
    spent_period_ngn: u128,
    /// `"YYYY-MM"` the spend above belongs to.
    period_key: String,
    /// USDC held, in base units.
    balance_usdc: u128,
    total_paid_ngn: u128,
    payment_count: u64,
    /// Deposit and withdrawal references already applied.
    references: LookupSet<String>,
    payments: LookupMap<u64, PaymentRecord>,
}

#[near(serializers = [json])]
pub struct PaymentOutcome {
    pub payment_id: u64,
    pub meter: String,
    pub amount_ngn: U128,
    pub amount_usdc: U128,
    pub remaining_cap_ngn: U128,
    /// False when the USDC could not reach the treasury; the payment was reversed.
    pub settled: bool,
}

#[near(serializers = [json])]
pub struct PolicyView {
    pub monthly_cap_ngn: U128,
    pub per_payment_cap_ngn: U128,
    pub allowed_meters: Vec<String>,
    pub period_key: String,
}

#[near(serializers = [json])]
pub struct StateView {
    pub owner: AccountId,
    pub funder: AccountId,
    pub treasury: AccountId,
    pub usdc: AccountId,
    pub usdc_per_kngn: U128,
    pub paused: bool,
    /// `"YYYY-MM"` the spend counter belongs to.
    pub period_key: String,
    pub spent_period_ngn: U128,
    pub remaining_cap_ngn: U128,
    pub balance_usdc: U128,
    /// `balance_usdc` at the current rate, rounded down.
    pub balance_ngn: U128,
    pub total_paid_ngn: U128,
    pub payment_count: u64,
}

#[near]
impl Vault {
    #[init]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        owner: AccountId,
        funder: AccountId,
        treasury: AccountId,
        usdc: AccountId,
        usdc_per_kngn: U128,
        monthly_cap_ngn: U128,
        per_payment_cap_ngn: U128,
        allowed_meters: Vec<String>,
    ) -> Self {
        require!(
            per_payment_cap_ngn.0 <= monthly_cap_ngn.0,
            "The per-payment limit cannot be above the monthly limit"
        );
        require!(usdc_per_kngn.0 > 0, ERR_NO_RATE);
        Self {
            owner,
            funder,
            treasury,
            usdc,
            usdc_per_kngn: usdc_per_kngn.0,
            paused: false,
            monthly_cap_ngn: monthly_cap_ngn.0,
            per_payment_cap_ngn: per_payment_cap_ngn.0,
            allowed_meters,
            spent_period_ngn: 0,
            period_key: period_key(env::block_timestamp() as u128),
            balance_usdc: 0,
            total_paid_ngn: 0,
            payment_count: 0,
            references: LookupSet::new(StorageKey::References),
            payments: LookupMap::new(StorageKey::Payments),
        }
    }

    // --- spending ------------------------------------------------------------

    /// Pay a bill: check the rules, book it, and send its USDC to the treasury.
    /// Panics with a plain-English reason if it breaks a rule. The meter token
    /// itself comes from the bill API, not from this contract.
    pub fn pay(&mut self, meter: String, amount_ngn: U128) -> Promise {
        let outcome = self.authorise(meter, amount_ngn);
        self.settle(outcome.payment_id)
    }

    /// A payment the owner approved over the caps. Owner-only: the agent key can
    /// never reach this. Pause, the allowlist and the balance still bind, and the
    /// spend still counts toward the month.
    pub fn pay_approved(&mut self, meter: String, amount_ngn: U128) -> Promise {
        let outcome = self.authorise_approved(meter, amount_ngn);
        self.settle(outcome.payment_id)
    }

    #[private]
    pub fn on_paid(&mut self, payment_id: u64) -> PaymentOutcome {
        let settled = env::promise_result_checked(0, 0).is_ok();
        if !settled {
            self.reverse(payment_id);
        }
        let record = self.record(payment_id);
        PaymentOutcome {
            payment_id,
            meter: record.meter,
            amount_ngn: record.amount_ngn,
            amount_usdc: record.amount_usdc,
            remaining_cap_ngn: U128(remaining_cap(self.monthly_cap_ngn, self.spent_period_ngn)),
            settled,
        }
    }

    // --- deposits and refunds: USDC arriving -----------------------------------

    /// NEP-141 receiver. A deposit's `msg` is its reference: a reference already
    /// applied is sent back untouched, so a retried deposit cannot credit twice.
    /// From the treasury, `msg = "refund:<payment_id>"` returns a failed bill's USDC.
    ///
    /// Only the funder and the treasury may deposit, with a `msg` of at most
    /// `MAX_MSG_LEN` bytes. Anything else is sent back in full before any state is
    /// written: each reference costs storage the vault pays for, so dust from a
    /// stranger with long unique `msg`s would otherwise use it up and stop every
    /// later call.
    pub fn ft_on_transfer(
        &mut self,
        sender_id: AccountId,
        amount: U128,
        msg: String,
    ) -> PromiseOrValue<U128> {
        require!(env::predecessor_account_id() == self.usdc, ERR_TOKEN_ONLY);
        if msg.len() > MAX_MSG_LEN {
            return PromiseOrValue::Value(amount);
        }
        if let Some(id) = msg.strip_prefix(REFUND_PREFIX) {
            return PromiseOrValue::Value(self.refund(&sender_id, id, amount.0));
        }
        if sender_id != self.funder && sender_id != self.treasury {
            return PromiseOrValue::Value(amount);
        }
        if !msg.is_empty() && !self.references.insert(msg.clone()) {
            return PromiseOrValue::Value(amount);
        }
        self.balance_usdc += amount.0;
        emit(
            "funded",
            json!({
                "amount_usdc": amount,
                "reference": msg,
                "sender": sender_id,
                "balance_usdc": U128(self.balance_usdc),
            }),
        );
        PromiseOrValue::Value(U128(0))
    }

    // --- funder ----------------------------------------------------------------

    /// Send a bank withdrawal's USDC back to the treasury, which pays out the naira.
    /// A reference already applied changes nothing.
    pub fn debit(&mut self, amount_usdc: U128, reference: String) -> PromiseOrValue<U128> {
        self.assert_funder();
        require!(amount_usdc.0 > 0, ERR_ZERO);
        if self.references.contains(&reference) {
            return PromiseOrValue::Value(U128(self.balance_usdc));
        }
        require!(amount_usdc.0 <= self.balance_usdc, ERR_NO_BALANCE_MSG);
        self.references.insert(reference.clone());
        self.balance_usdc -= amount_usdc.0;
        PromiseOrValue::Promise(
            self.transfer(&self.treasury.clone(), amount_usdc.0, &reference).then(
                Self::ext(env::current_account_id())
                    .with_static_gas(CALLBACK_GAS)
                    .on_debited(amount_usdc, reference),
            ),
        )
    }

    #[private]
    pub fn on_debited(&mut self, amount_usdc: U128, reference: String) -> U128 {
        if env::promise_result_checked(0, 0).is_ok() {
            emit(
                "debited",
                json!({
                    "amount_usdc": amount_usdc,
                    "reference": reference,
                    "balance_usdc": U128(self.balance_usdc),
                }),
            );
        } else {
            self.balance_usdc += amount_usdc.0;
            self.references.remove(&reference);
        }
        U128(self.balance_usdc)
    }

    /// The naira rate `pay` converts at. Funder-only, so the agent key can never move it.
    pub fn set_rate(&mut self, usdc_per_kngn: U128) {
        self.assert_funder();
        require!(usdc_per_kngn.0 > 0, ERR_NO_RATE);
        self.usdc_per_kngn = usdc_per_kngn.0;
    }

    // --- owner -------------------------------------------------------------------

    pub fn set_policy(
        &mut self,
        monthly_cap_ngn: U128,
        per_payment_cap_ngn: U128,
        allowed_meters: Vec<String>,
    ) {
        self.assert_owner();
        require!(
            per_payment_cap_ngn.0 <= monthly_cap_ngn.0,
            "The per-payment limit cannot be above the monthly limit"
        );
        self.monthly_cap_ngn = monthly_cap_ngn.0;
        self.per_payment_cap_ngn = per_payment_cap_ngn.0;
        self.allowed_meters = allowed_meters;
    }

    pub fn add_meter(&mut self, meter: String) {
        self.assert_owner();
        if !self.allowed_meters.contains(&meter) {
            self.allowed_meters.push(meter);
        }
    }

    pub fn remove_meter(&mut self, meter: String) {
        self.assert_owner();
        self.allowed_meters.retain(|m| m != &meter);
    }

    pub fn pause(&mut self) {
        self.assert_owner();
        self.paused = true;
    }

    pub fn unpause(&mut self) {
        self.assert_owner();
        self.paused = false;
    }

    /// Send USDC to the owner. Works even while paused — the owner can always get out.
    pub fn withdraw(&mut self, amount_usdc: U128) -> Promise {
        self.assert_owner();
        require!(amount_usdc.0 > 0, ERR_ZERO);
        require!(amount_usdc.0 <= self.balance_usdc, ERR_NO_BALANCE_MSG);
        self.balance_usdc -= amount_usdc.0;
        let owner = self.owner.clone();
        self.transfer(&owner, amount_usdc.0, "withdraw").then(
            Self::ext(env::current_account_id())
                .with_static_gas(CALLBACK_GAS)
                .on_withdrawn(amount_usdc),
        )
    }

    #[private]
    pub fn on_withdrawn(&mut self, amount_usdc: U128) -> bool {
        let sent = env::promise_result_checked(0, 0).is_ok();
        if sent {
            emit("withdrawn", json!({ "amount_usdc": amount_usdc }));
        } else {
            self.balance_usdc += amount_usdc.0;
        }
        sent
    }

    /// Offer the vault to another account — the user's own, once they have one.
    /// Nothing changes until that account calls `accept_owner`, so a mistyped id
    /// leaves the current owner in charge. A new offer replaces the last one.
    pub fn propose_owner(&mut self, owner: AccountId) {
        self.assert_owner();
        env::storage_write(PENDING_OWNER_KEY, owner.as_bytes());
        emit("owner_proposed", json!({ "owner": self.owner, "proposed": owner }));
    }

    /// Take the vault, as the account `propose_owner` named.
    pub fn accept_owner(&mut self) {
        let caller = env::predecessor_account_id();
        require!(self.pending_owner().as_ref() == Some(&caller), ERR_NOT_PROPOSED);
        env::storage_remove(PENDING_OWNER_KEY);
        let previous = std::mem::replace(&mut self.owner, caller);
        emit("owner_changed", json!({ "previous": previous, "owner": self.owner }));
    }

    // --- views ---------------------------------------------------------------

    pub fn get_policy(&self) -> PolicyView {
        let (key, _) = self.current_period();
        PolicyView {
            monthly_cap_ngn: U128(self.monthly_cap_ngn),
            per_payment_cap_ngn: U128(self.per_payment_cap_ngn),
            allowed_meters: self.allowed_meters.clone(),
            period_key: key,
        }
    }

    pub fn get_state(&self) -> StateView {
        let (key, spent) = self.current_period();
        StateView {
            owner: self.owner.clone(),
            funder: self.funder.clone(),
            treasury: self.treasury.clone(),
            usdc: self.usdc.clone(),
            usdc_per_kngn: U128(self.usdc_per_kngn),
            paused: self.paused,
            period_key: key,
            spent_period_ngn: U128(spent),
            remaining_cap_ngn: U128(remaining_cap(self.monthly_cap_ngn, spent)),
            balance_usdc: U128(self.balance_usdc),
            balance_ngn: U128(self.balance_ngn()),
            total_paid_ngn: U128(self.total_paid_ngn),
            payment_count: self.payment_count,
        }
    }

    /// The account offered the vault and not yet accepted, if any.
    pub fn get_pending_owner(&self) -> Option<AccountId> {
        self.pending_owner()
    }

    pub fn get_payment(&self, payment_id: u64) -> Option<PaymentRecord> {
        self.payments.get(&payment_id).cloned()
    }

    pub fn is_applied(&self, reference: String) -> bool {
        self.references.contains(&reference)
    }

    /// Dry-run a payment without changing anything, so the UI can disable buttons.
    pub fn can_pay(&self, meter: String, amount_ngn: U128) -> bool {
        let (_, spent) = self.current_period();
        let allowed = self.allowed_meters.contains(&meter);
        policy::check_payment(
            self.paused,
            self.monthly_cap_ngn,
            self.per_payment_cap_ngn,
            spent,
            self.balance_ngn(),
            amount_ngn.0,
            allowed,
        )
        .is_ok()
            && self.usdc_for(amount_ngn.0) <= self.balance_usdc
    }
}

impl Vault {
    /// Check a payment against every rule and book it. Only the agent key or the owner.
    pub fn authorise(&mut self, meter: String, amount_ngn: U128) -> PaymentOutcome {
        let caller = env::predecessor_account_id();
        require!(
            caller == env::current_account_id() || caller == self.owner,
            ERR_PAYER_ONLY
        );
        self.refresh_period();
        let allowed = self.allowed_meters.contains(&meter);
        refuse_if(policy::check_payment(
            self.paused,
            self.monthly_cap_ngn,
            self.per_payment_cap_ngn,
            self.spent_period_ngn,
            self.balance_ngn(),
            amount_ngn.0,
            allowed,
        ));
        self.book(meter, amount_ngn)
    }

    /// `authorise` for an owner-approved payment: the caps are lifted, nothing else.
    pub fn authorise_approved(&mut self, meter: String, amount_ngn: U128) -> PaymentOutcome {
        self.assert_owner();
        self.refresh_period();
        let allowed = self.allowed_meters.contains(&meter);
        refuse_if(policy::check_payment(
            self.paused,
            u128::MAX,
            u128::MAX,
            0,
            self.balance_ngn(),
            amount_ngn.0,
            allowed,
        ));
        self.book(meter, amount_ngn)
    }

    /// Record a payment that passed its rules: take the USDC, count the spend, and
    /// keep the record a refund needs.
    fn book(&mut self, meter: String, amount_ngn: U128) -> PaymentOutcome {
        let amount = amount_ngn.0;
        let usdc = self.usdc_for(amount);
        require!(usdc <= self.balance_usdc, Rejection::InsufficientBalance {
            need_ngn: amount,
            have_ngn: self.balance_ngn(),
        }
        .as_str());
        self.spent_period_ngn += amount;
        self.total_paid_ngn += amount;
        self.balance_usdc -= usdc;
        self.payment_count += 1;
        self.payments.insert(
            self.payment_count,
            PaymentRecord {
                meter: meter.clone(),
                amount_ngn,
                amount_usdc: U128(usdc),
                period_key: self.period_key.clone(),
                refunded: false,
            },
        );

        let remaining = remaining_cap(self.monthly_cap_ngn, self.spent_period_ngn);
        emit(
            "payment",
            json!({
                "payment_id": self.payment_count.to_string(),
                "meter": meter,
                "amount_ngn": amount_ngn,
                "amount_usdc": U128(usdc),
                "period": self.period_key,
                "remaining_cap_ngn": U128(remaining),
            }),
        );

        PaymentOutcome {
            payment_id: self.payment_count,
            meter,
            amount_ngn,
            amount_usdc: U128(usdc),
            remaining_cap_ngn: U128(remaining),
            settled: false,
        }
    }

    fn settle(&mut self, payment_id: u64) -> Promise {
        let usdc = self.record(payment_id).amount_usdc.0;
        let treasury = self.treasury.clone();
        self.transfer(&treasury, usdc, &format!("stark payment {payment_id}"))
            .then(
                Self::ext(env::current_account_id())
                    .with_static_gas(CALLBACK_GAS)
                    .on_paid(payment_id),
            )
    }

    /// Undo a booked payment: its USDC and, within its month, its allowance.
    fn reverse(&mut self, payment_id: u64) {
        let mut record = self.record(payment_id);
        if record.refunded {
            return;
        }
        self.refresh_period();
        let amount = record.amount_ngn.0;
        self.balance_usdc += record.amount_usdc.0;
        self.total_paid_ngn -= amount;
        if record.period_key == self.period_key {
            self.spent_period_ngn -= amount;
        }
        record.refunded = true;
        self.payments.insert(payment_id, record);
        emit(
            "refunded",
            json!({
                "payment_id": payment_id.to_string(),
                "amount_ngn": U128(amount),
                "balance_usdc": U128(self.balance_usdc),
            }),
        );
    }

    /// A failed bill's USDC coming back from the treasury. Anything that does not
    /// match a payment exactly is sent back.
    fn refund(&mut self, sender: &AccountId, id: &str, amount: u128) -> U128 {
        let Ok(payment_id) = id.parse::<u64>() else {
            return U128(amount);
        };
        let matches = sender == &self.treasury
            && self
                .payments
                .get(&payment_id)
                .is_some_and(|r| !r.refunded && r.amount_usdc.0 == amount);
        if !matches {
            return U128(amount);
        }
        self.reverse(payment_id);
        U128(0)
    }

    fn transfer(&self, receiver: &AccountId, amount_usdc: u128, memo: &str) -> Promise {
        Promise::new(self.usdc.clone()).function_call(
            "ft_transfer".to_string(),
            json!({ "receiver_id": receiver, "amount": U128(amount_usdc), "memo": memo })
                .to_string()
                .into_bytes(),
            ONE_YOCTO,
            FT_TRANSFER_GAS,
        )
    }

    fn pending_owner(&self) -> Option<AccountId> {
        env::storage_read(PENDING_OWNER_KEY).map(|bytes| {
            String::from_utf8(bytes)
                .ok()
                .and_then(|id| id.parse().ok())
                .unwrap_or_else(|| env::panic_str("Corrupt pending owner"))
        })
    }

    fn record(&self, payment_id: u64) -> PaymentRecord {
        self.payments
            .get(&payment_id)
            .cloned()
            .unwrap_or_else(|| env::panic_str("No such payment"))
    }

    /// USDC for a naira amount, rounded up so a payment never under-settles.
    fn usdc_for(&self, amount_ngn: u128) -> u128 {
        (amount_ngn * self.usdc_per_kngn).div_ceil(1000)
    }

    fn balance_ngn(&self) -> u128 {
        self.balance_usdc * 1000 / self.usdc_per_kngn
    }

    fn assert_owner(&self) {
        require!(env::predecessor_account_id() == self.owner, ERR_OWNER_ONLY);
    }

    fn assert_funder(&self) {
        require!(env::predecessor_account_id() == self.funder, ERR_FUNDER_ONLY);
    }

    /// What the period *currently* is, even if no transaction has touched state
    /// since the month rolled over. Views must not report last month's spend.
    fn current_period(&self) -> (String, u128) {
        let key = period_key(env::block_timestamp() as u128);
        if key == self.period_key {
            (key, self.spent_period_ngn)
        } else {
            (key, 0)
        }
    }

    /// Roll the spend counter when a new calendar month starts.
    fn refresh_period(&mut self) {
        let key = period_key(env::block_timestamp() as u128);
        if key != self.period_key {
            self.period_key = key;
            self.spent_period_ngn = 0;
        }
    }
}

/// Log the machine code, then panic with the human sentence.
fn refuse_if(check: Result<(), Rejection>) {
    if let Err(rejected) = check {
        env::log_str(
            &json!({ "code": rejected.code(), "message": rejected.as_str() }).to_string(),
        );
        env::panic_str(rejected.as_str());
    }
}

/// NEP-297 shaped event. Serialised by serde_json rather than `format!`, so a
/// reference or meter holding a quote cannot break out of its string and forge
/// fields or whole events.
fn emit(event: &str, data: Value) {
    let body = json!({
        "standard": EVENT_STANDARD,
        "version": EVENT_VERSION,
        "event": event,
        "data": [data],
    });
    env::log_str(&body.to_string());
}

#[cfg(test)]
mod tests;
