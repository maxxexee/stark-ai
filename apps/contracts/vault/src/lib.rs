//! Stark vault — one per user, spending caps enforced onchain.
//!
//! This is the "never cut" piece of the product: the guarantee that an AI agent
//! holding a function-call key cannot drain a user's balance.
//!
//! Each user gets their own vault account (`u-<id>.<parent>`), created by the
//! backend in one transaction: create the account, deploy this code, add the
//! agent's function-call key (scoped to `pay` on this account), call `new`.
//!
//! Three roles, and nobody else can change anything:
//!
//! * **owner** — policy, allowlist, pause, withdraw, hand-over. Starts as Stark's
//!   funder account (users sign in with email and hold no NEAR key) and can be
//!   handed to the user's own account with `set_owner`.
//! * **funder** — Stark's backend. Credits a confirmed deposit (`fund`), debits a
//!   bank withdrawal (`debit`), and reverses a payment the vendor did not deliver
//!   (`refund`). Each credit and debit carries a reference, and a reference is
//!   applied once: a retried broadcast cannot credit twice.
//! * **agent** — the function-call key on this very account. Its calls arrive with
//!   `predecessor == current_account_id`, and it may only `pay`.
//!
//! What this does **not** do: hold tokens. `balance_ngn` is a naira ledger that
//! mirrors money Stark holds (the Flutterwave NGN balance, treasury USDC).
//! Deposits are credited here by the funder after they are confirmed off-chain.
//!
//! `policy.rs` holds the cap rules with no `near-sdk` import, so the logic that
//! matters is tested directly rather than through a chain mock.

mod policy;

pub use policy::{period_key, remaining_cap, Rejection};

use near_sdk::json_types::U128;
use near_sdk::store::{LookupMap, LookupSet};
use near_sdk::{env, near, require, AccountId, BorshStorageKey, PanicOnDefault};

/// NEP-297 event standard identifier.
const EVENT_STANDARD: &str = "stark-vault";
const EVENT_VERSION: &str = "2.0";

const ERR_OWNER_ONLY: &str = "Only the owner can do that";
const ERR_FUNDER_ONLY: &str = "Only Stark can do that";
const ERR_PAYER_ONLY: &str = "Only Stark's agent or the owner can pay";
const ERR_NO_BALANCE_MSG: &str = "That's more than the balance";
const ERR_ZERO: &str = "That amount needs to be above zero.";

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
    /// Where settled funds belong. Informational until tokens move onchain.
    treasury: AccountId,
    paused: bool,
    monthly_cap_ngn: u128,
    per_payment_cap_ngn: u128,
    allowed_meters: Vec<String>,
    /// Spend already booked in `period_key`.
    spent_period_ngn: u128,
    /// `"YYYY-MM"` the spend above belongs to.
    period_key: String,
    /// Naira ledger. Mirrors money Stark holds — see the module docs.
    balance_ngn: u128,
    total_paid_ngn: u128,
    payment_count: u64,
    /// `fund`/`debit` references already applied.
    references: LookupSet<String>,
    payments: LookupMap<u64, PaymentRecord>,
}

/// Returned by `pay`. Plain data, so serde is derived explicitly — the wasm
/// build serialises these on the way out, and a bare `#[near]` only derives borsh.
#[near(serializers = [json])]
pub struct PaymentOutcome {
    pub payment_id: u64,
    pub meter: String,
    pub amount_ngn: U128,
    pub remaining_cap_ngn: U128,
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
    pub paused: bool,
    /// `"YYYY-MM"` the spend counter belongs to.
    pub period_key: String,
    pub spent_period_ngn: U128,
    pub remaining_cap_ngn: U128,
    pub balance_ngn: U128,
    pub total_paid_ngn: U128,
    pub payment_count: u64,
}

#[near]
impl Vault {
    #[init]
    pub fn new(
        owner: AccountId,
        funder: AccountId,
        treasury: AccountId,
        monthly_cap_ngn: U128,
        per_payment_cap_ngn: U128,
        allowed_meters: Vec<String>,
    ) -> Self {
        require!(
            per_payment_cap_ngn.0 <= monthly_cap_ngn.0,
            "The per-payment limit cannot be above the monthly limit"
        );
        Self {
            owner,
            funder,
            treasury,
            paused: false,
            monthly_cap_ngn: monthly_cap_ngn.0,
            per_payment_cap_ngn: per_payment_cap_ngn.0,
            allowed_meters,
            spent_period_ngn: 0,
            period_key: period_key(env::block_timestamp() as u128),
            balance_ngn: 0,
            total_paid_ngn: 0,
            payment_count: 0,
            references: LookupSet::new(StorageKey::References),
            payments: LookupMap::new(StorageKey::Payments),
        }
    }

    // --- spending ------------------------------------------------------------

    /// Book a bill payment. Panics with a plain-English reason if it breaks a rule.
    ///
    /// Only the agent key (a call from this account to itself) or the owner may
    /// pay. The meter token itself comes from the bill API, not from this contract.
    pub fn pay(&mut self, meter: String, amount_ngn: U128) -> PaymentOutcome {
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
            self.balance_ngn,
            amount_ngn.0,
            allowed,
        ));
        self.book(meter, amount_ngn)
    }

    /// A payment the owner approved over the caps. Owner-only: the agent key can
    /// never reach this. Pause, the allowlist and the balance still bind, and the
    /// spend still counts toward the month.
    pub fn pay_approved(&mut self, meter: String, amount_ngn: U128) -> PaymentOutcome {
        self.assert_owner();
        self.refresh_period();
        let allowed = self.allowed_meters.contains(&meter);
        refuse_if(policy::check_payment(
            self.paused,
            u128::MAX,
            u128::MAX,
            0,
            self.balance_ngn,
            amount_ngn.0,
            allowed,
        ));
        self.book(meter, amount_ngn)
    }

    // --- funder: money Stark confirmed off-chain -------------------------------

    /// Credit a confirmed deposit. A reference already applied changes nothing,
    /// so a retried broadcast is harmless. Returns the balance after.
    pub fn fund(&mut self, amount_ngn: U128, reference: String) -> U128 {
        self.assert_funder();
        require!(amount_ngn.0 > 0, ERR_ZERO);
        if !self.references.insert(reference.clone()) {
            return U128(self.balance_ngn);
        }
        self.balance_ngn += amount_ngn.0;
        emit(
            "funded",
            &format!(
                r#"{{"amount_ngn":"{}","reference":"{}","balance_ngn":"{}"}}"#,
                amount_ngn.0, reference, self.balance_ngn
            ),
        );
        U128(self.balance_ngn)
    }

    /// Debit money leaving to the user's bank. Same reference rule as `fund`.
    pub fn debit(&mut self, amount_ngn: U128, reference: String) -> U128 {
        self.assert_funder();
        require!(amount_ngn.0 > 0, ERR_ZERO);
        if self.references.contains(&reference) {
            return U128(self.balance_ngn);
        }
        require!(amount_ngn.0 <= self.balance_ngn, ERR_NO_BALANCE_MSG);
        self.references.insert(reference.clone());
        self.balance_ngn -= amount_ngn.0;
        emit(
            "debited",
            &format!(
                r#"{{"amount_ngn":"{}","reference":"{}","balance_ngn":"{}"}}"#,
                amount_ngn.0, reference, self.balance_ngn
            ),
        );
        U128(self.balance_ngn)
    }

    /// Reverse a payment the vendor did not deliver: the money comes back, and so
    /// does the allowance if it is still the month it was spent in. Applied once.
    pub fn refund(&mut self, payment_id: u64) -> U128 {
        self.assert_funder();
        self.refresh_period();
        let mut record = self
            .payments
            .get(&payment_id)
            .cloned()
            .unwrap_or_else(|| env::panic_str("No such payment"));
        if record.refunded {
            return U128(self.balance_ngn);
        }
        let amount = record.amount_ngn.0;
        self.balance_ngn += amount;
        self.total_paid_ngn -= amount;
        if record.period_key == self.period_key {
            self.spent_period_ngn -= amount;
        }
        record.refunded = true;
        self.payments.insert(payment_id, record);
        emit(
            "refunded",
            &format!(
                r#"{{"payment_id":"{}","amount_ngn":"{}","balance_ngn":"{}"}}"#,
                payment_id, amount, self.balance_ngn
            ),
        );
        U128(self.balance_ngn)
    }

    // --- owner -------------------------------------------------------------------

    /// Owner-only. Blocked while paused.
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

    /// Owner withdraw. Works even while paused — the owner can always get out.
    pub fn withdraw(&mut self, amount_ngn: U128) {
        self.assert_owner();
        require!(amount_ngn.0 <= self.balance_ngn, ERR_NO_BALANCE_MSG);
        self.balance_ngn -= amount_ngn.0;
        emit("withdrawn", &format!(r#"{{"amount_ngn":"{}"}}"#, amount_ngn.0));
    }

    /// Hand the vault to another account — the user's own, once they have one.
    pub fn set_owner(&mut self, owner: AccountId) {
        self.assert_owner();
        self.owner = owner;
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
            paused: self.paused,
            period_key: key,
            spent_period_ngn: U128(spent),
            remaining_cap_ngn: U128(remaining_cap(self.monthly_cap_ngn, spent)),
            balance_ngn: U128(self.balance_ngn),
            total_paid_ngn: U128(self.total_paid_ngn),
            payment_count: self.payment_count,
        }
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
            self.balance_ngn,
            amount_ngn.0,
            allowed,
        )
        .is_ok()
    }
}

impl Vault {
    /// Record a payment that passed its rules: move the money, count the spend,
    /// keep the record a refund needs, and emit the event.
    fn book(&mut self, meter: String, amount_ngn: U128) -> PaymentOutcome {
        let amount = amount_ngn.0;
        self.spent_period_ngn += amount;
        self.total_paid_ngn += amount;
        self.balance_ngn -= amount;
        self.payment_count += 1;
        self.payments.insert(
            self.payment_count,
            PaymentRecord {
                meter: meter.clone(),
                amount_ngn,
                period_key: self.period_key.clone(),
                refunded: false,
            },
        );

        let remaining = remaining_cap(self.monthly_cap_ngn, self.spent_period_ngn);
        emit(
            "payment",
            &format!(
                r#"{{"payment_id":"{}","meter":"{}","amount_ngn":"{}","period":"{}","remaining_cap_ngn":"{}"}}"#,
                self.payment_count, meter, amount, self.period_key, remaining
            ),
        );

        PaymentOutcome {
            payment_id: self.payment_count,
            meter,
            amount_ngn,
            remaining_cap_ngn: U128(remaining),
        }
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
        env::log_str(&format!(
            r#"{{"code":"{}","message":"{}"}}"#,
            rejected.code(),
            rejected.as_str()
        ));
        env::panic_str(rejected.as_str());
    }
}

/// NEP-297 shaped event, hand-built so we don't depend on macro internals.
fn emit(event: &str, data: &str) {
    env::log_str(&format!(
        r#"{{"standard":"{}","version":"{}","event":"{}","data":[{}]}}"#,
        EVENT_STANDARD, EVENT_VERSION, event, data
    ));
}

#[cfg(test)]
mod tests;
