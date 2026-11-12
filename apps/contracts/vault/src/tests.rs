use super::*;
use near_sdk::test_utils::{accounts, VMContextBuilder};
use near_sdk::{test_vm_config, testing_env, PromiseResult, RuntimeFeesConfig};

const METER: &str = "0101170026583";
const METER2: &str = "08031234567";

/// 2026-10-20 00:00 UTC, in nanoseconds.
const OCT_2026: u64 = 1_792_454_400_000_000_000;
/// 2026-11-01 00:00 UTC, in nanoseconds.
const NOV_2026: u64 = 1_793_491_200_000_000_000;

// Roles. The vault is accounts(0), so a call *from* accounts(0) is the agent key.
fn agent() -> AccountId {
    accounts(0)
}
fn owner() -> AccountId {
    accounts(1)
}
fn funder() -> AccountId {
    accounts(2)
}
fn treasury() -> AccountId {
    accounts(3)
}
fn stranger() -> AccountId {
    accounts(4)
}
fn usdc() -> AccountId {
    accounts(5)
}

fn act_as(predecessor: AccountId, timestamp: u64) {
    let mut builder = VMContextBuilder::new();
    builder
        .current_account_id(accounts(0))
        .predecessor_account_id(predecessor)
        .block_timestamp(timestamp);
    testing_env!(builder.build());
}

/// USDC sent in through the token, as `ft_transfer_call` delivers it. Leaves the
/// caller as it found it and returns the amount sent back.
fn deposit(vault: &mut Vault, amount_usdc: u128, reference: &str) -> U128 {
    let caller = env::predecessor_account_id();
    let now = env::block_timestamp();
    act_as(usdc(), now);
    let PromiseOrValue::Value(unused) =
        vault.ft_on_transfer(funder(), U128(amount_usdc), reference.to_string())
    else {
        panic!("a deposit answers at once");
    };
    act_as(caller, now);
    unused
}

/// A payment's USDC sent back by `sender`, as the treasury does for a failed bill.
fn refund(vault: &mut Vault, sender: AccountId, payment_id: u64, amount_usdc: u128) -> U128 {
    let now = env::block_timestamp();
    act_as(usdc(), now);
    let PromiseOrValue::Value(unused) =
        vault.ft_on_transfer(sender, U128(amount_usdc), format!("refund:{payment_id}"))
    else {
        panic!("a refund answers at once");
    };
    unused
}

/// Run the next call as this vault's own callback, with `result` as the transfer's.
fn callback(result: PromiseResult) {
    let mut builder = VMContextBuilder::new();
    builder
        .current_account_id(accounts(0))
        .predecessor_account_id(accounts(0))
        .block_timestamp(env::block_timestamp());
    testing_env!(
        builder.build(),
        test_vm_config(),
        RuntimeFeesConfig::test(),
        Default::default(),
        vec![result],
    );
}

/// Rate 1000: one naira is one USDC base unit, so the naira figures below read directly.
fn empty_vault() -> Vault {
    act_as(funder(), OCT_2026);
    Vault::new(
        owner(),
        funder(),
        treasury(),
        usdc(),
        U128(1_000),
        U128(30_000),
        U128(10_000),
        vec![METER.to_string()],
    )
}

/// Funded with ₦64,200, left acting as the agent.
fn funded_vault() -> Vault {
    let mut vault = empty_vault();
    deposit(&mut vault, 64_200, "dep_seed");
    act_as(agent(), OCT_2026);
    vault
}

// --- caps: the never-cut guarantee --------------------------------------

#[test]
fn a_payment_within_the_limits_succeeds() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(5_000));
    assert_eq!(out.payment_id, 1);
    assert_eq!(out.amount_ngn, U128(5_000));
    assert_eq!(out.remaining_cap_ngn, U128(25_000));
    assert_eq!(v.get_state().spent_period_ngn, U128(5_000));
    assert_eq!(v.get_state().balance_ngn, U128(59_200));
}

#[test]
#[should_panic(expected = "over your monthly limit")]
fn refuses_a_payment_over_the_monthly_cap() {
    let mut v = funded_vault();
    for _ in 0..3 {
        v.authorise(METER.to_string(), U128(10_000));
    }
    v.authorise(METER.to_string(), U128(1));
}

#[test]
#[should_panic(expected = "most you allow in one go")]
fn refuses_a_payment_over_the_per_payment_cap() {
    let mut v = funded_vault();
    v.authorise(METER.to_string(), U128(10_001));
}

#[test]
#[should_panic(expected = "isn't on your list")]
fn refuses_a_meter_that_is_not_on_the_allowlist() {
    let mut v = funded_vault();
    v.authorise(METER2.to_string(), U128(1_000));
}

#[test]
#[should_panic(expected = "paused")]
fn refuses_payments_while_paused() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.pause();
    act_as(agent(), OCT_2026);
    v.authorise(METER.to_string(), U128(1_000));
}

#[test]
fn the_cap_resets_when_the_month_rolls_over() {
    let mut v = funded_vault();
    for _ in 0..3 {
        v.authorise(METER.to_string(), U128(10_000));
    }
    assert_eq!(v.get_state().remaining_cap_ngn, U128(0));

    act_as(agent(), NOV_2026);
    assert_eq!(v.get_state().period_key, "2026-11");
    assert_eq!(v.get_state().remaining_cap_ngn, U128(30_000));

    let out = v.authorise(METER.to_string(), U128(10_000));
    assert_eq!(out.payment_id, 4, "counter is cumulative across months");
}

#[test]
fn the_monthly_counter_is_shared_across_meters() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.add_meter(METER2.to_string());
    act_as(agent(), OCT_2026);
    v.authorise(METER.to_string(), U128(10_000));
    v.authorise(METER2.to_string(), U128(10_000));
    v.authorise(METER2.to_string(), U128(10_000));
    assert_eq!(v.get_state().remaining_cap_ngn, U128(0));
}

// --- roles: the reason an agent can't drain the wallet ---------------------

#[test]
#[should_panic(expected = "Only Stark's agent or the owner can pay")]
fn a_stranger_cannot_pay() {
    let mut v = funded_vault();
    act_as(stranger(), OCT_2026);
    v.authorise(METER.to_string(), U128(1_000));
}

#[test]
#[should_panic(expected = "Only Stark's agent or the owner can pay")]
fn the_funder_cannot_pay() {
    // Crediting money and spending it are different keys on purpose.
    let mut v = funded_vault();
    act_as(funder(), OCT_2026);
    v.authorise(METER.to_string(), U128(1_000));
}

#[test]
fn the_owner_can_pay() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    assert_eq!(v.authorise(METER.to_string(), U128(1_000)).payment_id, 1);
}

#[test]
#[should_panic(expected = "only holds USDC")]
fn a_deposit_of_another_token_is_refused() {
    // Regression for the old ledger: balance used to be credited by a funder call.
    let mut v = empty_vault();
    act_as(stranger(), OCT_2026);
    let _ = v.ft_on_transfer(stranger(), U128(1_000_000), "free".to_string());
}

/// `ft_on_transfer` as the USDC token calls it, from `sender`. Returns the amount sent back.
fn transfer_in(vault: &mut Vault, sender: AccountId, amount_usdc: u128, msg: &str) -> U128 {
    act_as(usdc(), OCT_2026);
    let PromiseOrValue::Value(unused) =
        vault.ft_on_transfer(sender, U128(amount_usdc), msg.to_string())
    else {
        panic!("a deposit answers at once");
    };
    unused
}

#[test]
fn the_funder_and_the_treasury_can_send_usdc_in_without_a_reference() {
    let mut v = empty_vault();
    assert_eq!(transfer_in(&mut v, funder(), 2_500, ""), U128(0));
    assert_eq!(transfer_in(&mut v, treasury(), 500, ""), U128(0));
    assert_eq!(v.get_state().balance_usdc, U128(3_000));
}

#[test]
fn usdc_from_a_stranger_is_sent_back_and_stores_nothing() {
    let mut v = empty_vault();
    assert_eq!(transfer_in(&mut v, stranger(), 1, "spam_1"), U128(1));
    assert_eq!(transfer_in(&mut v, stranger(), 2_500, ""), U128(2_500));
    assert_eq!(v.get_state().balance_usdc, U128(0));
    assert!(!v.is_applied("spam_1".to_string()), "a stranger's msg must not take storage");
    assert!(near_sdk::test_utils::get_logs().is_empty(), "nor write an event");
}

#[test]
fn a_stranger_cannot_burn_a_reference_the_funder_will_use() {
    let mut v = empty_vault();
    transfer_in(&mut v, stranger(), 1, "dep_1");
    assert_eq!(deposit(&mut v, 5_000, "dep_1"), U128(0));
    assert_eq!(v.get_state().balance_usdc, U128(5_000));
}

#[test]
fn an_overlong_msg_is_sent_back_even_from_the_funder() {
    let mut v = empty_vault();
    let long = "x".repeat(MAX_MSG_LEN + 1);
    assert_eq!(transfer_in(&mut v, funder(), 5_000, &long), U128(5_000));
    assert!(!v.is_applied(long));
    let longest = "x".repeat(MAX_MSG_LEN);
    assert_eq!(transfer_in(&mut v, funder(), 5_000, &longest), U128(0));
    assert_eq!(v.get_state().balance_usdc, U128(5_000));
}

#[test]
fn an_overlong_refund_msg_is_sent_back() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(5_000));
    let msg = format!("refund:{}{}", out.payment_id, " ".repeat(MAX_MSG_LEN));
    assert_eq!(transfer_in(&mut v, treasury(), 5_000, &msg), U128(5_000));
    assert!(!v.get_payment(out.payment_id).unwrap().refunded);
}

#[test]
fn a_reference_with_quotes_cannot_forge_event_fields() {
    let mut v = empty_vault();
    let forged = r#"x","amount_usdc":"999999999"}]}"#;
    transfer_in(&mut v, funder(), 5, forged);
    let logs = near_sdk::test_utils::get_logs();
    assert_eq!(logs.len(), 1);
    let event: Value = near_sdk::serde_json::from_str(&logs[0]).expect("the event is valid JSON");
    assert_eq!(event["event"], "funded");
    assert_eq!(event["data"][0]["reference"], forged);
    assert_eq!(event["data"][0]["amount_usdc"], "5");
}

#[test]
#[should_panic(expected = "Only Stark's agent or the owner can pay")]
fn the_token_contract_cannot_pay() {
    let mut v = funded_vault();
    act_as(usdc(), OCT_2026);
    v.authorise(METER.to_string(), U128(1_000));
}

#[test]
#[should_panic(expected = "Only the owner")]
fn a_non_owner_cannot_withdraw() {
    let mut v = funded_vault();
    act_as(stranger(), OCT_2026);
    let _ = v.withdraw(U128(1_000));
}

#[test]
#[should_panic(expected = "Only the owner")]
fn the_agent_cannot_withdraw() {
    let mut v = funded_vault();
    let _ = v.withdraw(U128(1_000));
}

#[test]
#[should_panic(expected = "Only Stark can do that")]
fn the_agent_cannot_move_the_rate() {
    let mut v = funded_vault();
    v.set_rate(U128(1));
}

#[test]
#[should_panic(expected = "Only Stark can do that")]
fn the_agent_cannot_debit() {
    let mut v = funded_vault();
    let _ = v.debit(U128(1_000), "wd_1".to_string());
}

#[test]
#[should_panic(expected = "Only the owner")]
fn a_non_owner_cannot_change_the_policy() {
    let mut v = funded_vault();
    v.set_policy(U128(10_000_000), U128(9_000_000), vec![]);
}

#[test]
#[should_panic(expected = "Only the owner")]
fn a_non_owner_cannot_pause() {
    let mut v = funded_vault();
    act_as(stranger(), OCT_2026);
    v.pause();
}

#[test]
#[should_panic(expected = "Only the owner")]
fn a_non_owner_cannot_widen_the_allowlist() {
    let mut v = funded_vault();
    v.add_meter(METER2.to_string());
}

#[test]
fn the_owner_can_always_withdraw_even_while_paused() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.pause();
    let _ = v.withdraw(U128(20_000));
    assert_eq!(v.get_state().balance_ngn, U128(44_200));
}

#[test]
fn a_withdrawal_that_does_not_arrive_is_put_back() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    let _ = v.withdraw(U128(20_000));
    callback(PromiseResult::Failed);
    assert!(!v.on_withdrawn(U128(20_000)));
    assert_eq!(v.get_state().balance_ngn, U128(64_200));
}

// --- ownership hand-over: propose, then accept ------------------------------

const NEW_OWNER: &str = "user.testnet";

fn new_owner() -> AccountId {
    NEW_OWNER.parse().unwrap()
}

#[test]
#[should_panic(expected = "Only the owner")]
fn handing_over_ownership_moves_the_policy_keys() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.propose_owner(new_owner());
    act_as(new_owner(), OCT_2026);
    v.accept_owner();
    assert_eq!(v.get_state().owner, new_owner());
    assert_eq!(v.get_pending_owner(), None);
    v.pause(); // the new owner can
    act_as(owner(), OCT_2026);
    v.unpause(); // the old owner no longer can
}

#[test]
fn a_proposal_changes_nothing_until_it_is_accepted() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.propose_owner(new_owner());
    assert_eq!(v.get_state().owner, owner());
    assert_eq!(v.get_pending_owner(), Some(new_owner()));
    v.pause(); // still the owner's to run
    assert!(v.get_state().paused);
}

#[test]
#[should_panic(expected = "has not been offered the vault")]
fn only_the_proposed_account_can_accept() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.propose_owner(new_owner());
    act_as(stranger(), OCT_2026);
    v.accept_owner();
}

#[test]
#[should_panic(expected = "has not been offered the vault")]
fn nobody_can_accept_without_a_proposal() {
    let mut v = funded_vault();
    act_as(stranger(), OCT_2026);
    v.accept_owner();
}

#[test]
#[should_panic(expected = "Only the owner")]
fn a_non_owner_cannot_propose_an_owner() {
    let mut v = funded_vault();
    act_as(stranger(), OCT_2026);
    v.propose_owner(stranger());
}

#[test]
#[should_panic(expected = "has not been offered the vault")]
fn a_new_proposal_replaces_the_last() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.propose_owner(stranger());
    v.propose_owner(new_owner());
    act_as(stranger(), OCT_2026);
    v.accept_owner();
}

#[test]
#[should_panic(expected = "has not been offered the vault")]
fn an_accepted_proposal_cannot_be_accepted_again() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.propose_owner(new_owner());
    act_as(new_owner(), OCT_2026);
    v.accept_owner();
    act_as(owner(), OCT_2026);
    v.accept_owner();
}

// --- deposits and debits apply exactly once ---------------------------------

#[test]
fn a_repeated_deposit_reference_credits_once_and_sends_the_repeat_back() {
    let mut v = empty_vault();
    assert_eq!(deposit(&mut v, 5_000, "dep_1"), U128(0));
    assert_eq!(deposit(&mut v, 5_000, "dep_1"), U128(5_000));
    assert_eq!(deposit(&mut v, 2_000, "dep_2"), U128(0));
    assert_eq!(v.get_state().balance_usdc, U128(7_000));
    assert!(v.is_applied("dep_1".to_string()));
    assert!(!v.is_applied("dep_3".to_string()));
}

#[test]
fn a_debit_moves_usdc_once_and_leaves_the_allowance_alone() {
    let mut v = empty_vault();
    deposit(&mut v, 10_000, "dep_1");
    act_as(funder(), OCT_2026);
    let _ = v.debit(U128(4_000), "wd_1".to_string());
    let _ = v.debit(U128(4_000), "wd_1".to_string());
    let state = v.get_state();
    assert_eq!(state.balance_usdc, U128(6_000));
    assert_eq!(state.spent_period_ngn, U128(0));
}

#[test]
fn a_debit_that_does_not_arrive_is_put_back_and_can_be_retried() {
    let mut v = empty_vault();
    deposit(&mut v, 10_000, "dep_1");
    act_as(funder(), OCT_2026);
    let _ = v.debit(U128(4_000), "wd_1".to_string());
    callback(PromiseResult::Failed);
    assert_eq!(v.on_debited(U128(4_000), "wd_1".to_string()), U128(10_000));
    assert!(!v.is_applied("wd_1".to_string()));
}

#[test]
#[should_panic(expected = "more than the balance")]
fn a_debit_over_the_balance_is_refused() {
    let mut v = empty_vault();
    deposit(&mut v, 1_000, "dep_1");
    act_as(funder(), OCT_2026);
    let _ = v.debit(U128(1_001), "wd_1".to_string());
}

#[test]
fn a_refused_debit_does_not_burn_its_reference() {
    // The retry after a top-up must still go through.
    let mut v = empty_vault();
    deposit(&mut v, 1_000, "dep_1");
    assert!(!v.is_applied("wd_1".to_string()));
    deposit(&mut v, 5_000, "dep_2");
    act_as(funder(), OCT_2026);
    let _ = v.debit(U128(2_000), "wd_1".to_string());
    assert_eq!(v.get_state().balance_usdc, U128(4_000));
}

// --- settlement: a payment's USDC reaches the treasury, or the payment is undone

#[test]
fn a_settled_payment_reports_settled() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(10_000));
    callback(PromiseResult::Successful(vec![]));
    let settled = v.on_paid(out.payment_id);
    assert!(settled.settled);
    assert_eq!(v.get_state().balance_ngn, U128(54_200));
}

#[test]
fn a_payment_whose_usdc_does_not_arrive_is_reversed() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(10_000));
    callback(PromiseResult::Failed);
    assert!(!v.on_paid(out.payment_id).settled);
    let state = v.get_state();
    assert_eq!(state.balance_ngn, U128(64_200));
    assert_eq!(state.spent_period_ngn, U128(0));
}

#[test]
fn usdc_is_rounded_up_so_a_payment_never_under_settles() {
    let mut v = empty_vault();
    act_as(funder(), OCT_2026);
    v.set_rate(U128(641_026));
    deposit(&mut v, 10_000_000, "dep_1");
    act_as(agent(), OCT_2026);
    let out = v.authorise(METER.to_string(), U128(1_001));
    assert_eq!(out.amount_usdc, U128(641_668));
}

// --- refunds: a vendor failure gives everything back ------------------------

#[test]
fn a_refund_returns_the_money_and_the_allowance() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(10_000));
    assert_eq!(refund(&mut v, treasury(), out.payment_id, 10_000), U128(0));
    let state = v.get_state();
    assert_eq!(state.balance_ngn, U128(64_200));
    assert_eq!(state.spent_period_ngn, U128(0));
    assert_eq!(state.remaining_cap_ngn, U128(30_000));
    assert_eq!(state.total_paid_ngn, U128(0));
    assert!(v.get_payment(out.payment_id).unwrap().refunded);
}

#[test]
fn a_refund_applies_once() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(10_000));
    refund(&mut v, treasury(), out.payment_id, 10_000);
    assert_eq!(refund(&mut v, treasury(), out.payment_id, 10_000), U128(10_000));
    assert_eq!(v.get_state().balance_ngn, U128(64_200));
}

#[test]
fn a_refund_from_anyone_but_the_treasury_is_sent_back() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(10_000));
    assert_eq!(refund(&mut v, stranger(), out.payment_id, 10_000), U128(10_000));
    assert!(!v.get_payment(out.payment_id).unwrap().refunded);
}

#[test]
fn a_refund_of_the_wrong_amount_is_sent_back() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(10_000));
    assert_eq!(refund(&mut v, treasury(), out.payment_id, 9_999), U128(9_999));
    assert_eq!(v.get_state().balance_ngn, U128(54_200));
}

#[test]
fn a_refund_after_the_month_turns_does_not_inflate_the_new_allowance() {
    let mut v = funded_vault();
    let out = v.authorise(METER.to_string(), U128(10_000));
    act_as(usdc(), NOV_2026);
    let _ = v.ft_on_transfer(treasury(), U128(10_000), format!("refund:{}", out.payment_id));
    let state = v.get_state();
    assert_eq!(state.balance_ngn, U128(64_200));
    assert_eq!(state.spent_period_ngn, U128(0));
    assert_eq!(state.remaining_cap_ngn, U128(30_000));
}

#[test]
fn refunding_an_unknown_payment_sends_it_back() {
    let mut v = funded_vault();
    assert_eq!(refund(&mut v, treasury(), 99, 1_000), U128(1_000));
}

// --- ledger ---------------------------------------------------------------

#[test]
#[should_panic(expected = "isn't enough in your balance")]
fn refuses_to_pay_more_than_the_ledger_holds() {
    let mut v = empty_vault();
    deposit(&mut v, 4_000, "dep_1");
    act_as(agent(), OCT_2026);
    v.authorise(METER.to_string(), U128(5_000));
}

#[test]
fn total_paid_is_cumulative_across_months() {
    let mut v = funded_vault();
    for _ in 0..3 {
        v.authorise(METER.to_string(), U128(10_000));
    }
    act_as(agent(), NOV_2026);
    for _ in 0..3 {
        v.authorise(METER.to_string(), U128(10_000));
    }
    assert_eq!(v.get_state().total_paid_ngn, U128(60_000));
}

// --- guard rails -----------------------------------------------------------

#[test]
#[should_panic(expected = "per-payment limit cannot be above the monthly")]
fn refuses_a_per_payment_cap_above_the_monthly_cap() {
    act_as(funder(), OCT_2026);
    Vault::new(
        owner(),
        funder(),
        treasury(),
        usdc(),
        U128(1_000),
        U128(30_000),
        U128(90_000),
        vec![METER.to_string()],
    );
}

// --- view helper -------------------------------------------------------------

#[test]
fn can_pay_is_false_where_pay_would_fail() {
    let mut v = funded_vault();
    assert!(v.can_pay(METER.to_string(), U128(5_000)));
    assert!(!v.can_pay(METER.to_string(), U128(10_001)));
    assert!(!v.can_pay(METER2.to_string(), U128(1_000)));
    for _ in 0..3 {
        v.authorise(METER.to_string(), U128(10_000));
    }
    assert!(!v.can_pay(METER.to_string(), U128(1)), "cap exhausted");
    act_as(owner(), OCT_2026);
    v.pause();
    assert!(!v.can_pay(METER.to_string(), U128(1)), "paused");
}

#[test]
fn views_report_the_new_allowance_after_a_rollover_without_a_transaction() {
    let mut v = funded_vault();
    for _ in 0..3 {
        v.authorise(METER.to_string(), U128(10_000));
    }
    assert_eq!(v.get_state().remaining_cap_ngn, U128(0));

    act_as(agent(), NOV_2026);
    assert_eq!(v.get_state().period_key, "2026-11");
    assert_eq!(v.get_state().spent_period_ngn, U128(0));
    assert_eq!(v.get_state().remaining_cap_ngn, U128(30_000));
    assert!(v.can_pay(METER.to_string(), U128(10_000)));
    assert_eq!(v.get_state().total_paid_ngn, U128(30_000));
}

#[test]
fn removing_a_meter_takes_effect_immediately() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.remove_meter(METER.to_string());
    assert!(v.get_policy().allowed_meters.is_empty());
    assert!(!v.can_pay(METER.to_string(), U128(1_000)));
}

#[test]
fn set_policy_replaces_caps_and_allowlist() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.set_policy(U128(50_000), U128(20_000), vec![METER2.to_string()]);
    let policy = v.get_policy();
    assert_eq!(policy.monthly_cap_ngn, U128(50_000));
    assert_eq!(policy.allowed_meters, vec![METER2.to_string()]);
}

// --- approvals: the owner may pay past the caps, the agent may not -----------

#[test]
fn the_owner_can_pay_an_approved_amount_over_the_caps() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    let out = v.authorise_approved(METER.to_string(), U128(40_000));
    assert_eq!(out.payment_id, 1);
    let state = v.get_state();
    assert_eq!(state.balance_ngn, U128(24_200));
    assert_eq!(state.spent_period_ngn, U128(40_000), "approved spend still counts");
    assert_eq!(state.remaining_cap_ngn, U128(0));
}

#[test]
#[should_panic(expected = "Only the owner")]
fn the_agent_cannot_pay_approved() {
    let mut v = funded_vault();
    v.authorise_approved(METER.to_string(), U128(40_000));
}

#[test]
#[should_panic(expected = "isn't enough in your balance")]
fn an_approved_payment_still_needs_the_balance() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.authorise_approved(METER.to_string(), U128(64_201));
}

#[test]
#[should_panic(expected = "paused")]
fn an_approved_payment_still_respects_pause() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.pause();
    v.authorise_approved(METER.to_string(), U128(1_000));
}

#[test]
#[should_panic(expected = "isn't on your list")]
fn an_approved_payment_still_respects_the_allowlist() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    v.authorise_approved(METER2.to_string(), U128(1_000));
}

#[test]
fn an_approved_payment_can_be_refunded() {
    let mut v = funded_vault();
    act_as(owner(), OCT_2026);
    let out = v.authorise_approved(METER.to_string(), U128(40_000));
    refund(&mut v, treasury(), out.payment_id, 40_000);
    assert_eq!(v.get_state().balance_ngn, U128(64_200));
    assert_eq!(v.get_state().spent_period_ngn, U128(0));
}
