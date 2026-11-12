# @stark/contracts

NEAR smart contracts, in Rust. Today there is one: [`vault/`](vault), which holds a
user's spending policy and is the account the agent's `pay()` calls are signed against.

## Setup

Not needed for the web app, the dashboard or the backend; skip this unless you are
changing the contract.

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh   # once
rustup target add wasm32-unknown-unknown
```

## Commands

From the repo root:

| Command | What it does |
|---|---|
| `bun --filter @stark/contracts run contract:test` | 38 unit tests on the host |
| `bun --filter @stark/contracts run contract:check` | type-check the wasm target |
| `bun --filter @stark/contracts run contract:build` | release wasm → `vault/target/wasm32-unknown-unknown/release/stark_vault.wasm` |

Or with cargo directly from `vault/`: `cargo test`, `cargo build --target wasm32-unknown-unknown --release`.

These are deliberately not turbo tasks, so `bun run test` and `bun run build` work without a
Rust toolchain.

If cargo reports no toolchain although rustup is installed, your shell's `$HOME` is
probably redirected; set `RUSTUP_HOME` to the real `~/.rustup`. See
[`docs/HANDOFF.md`](../../docs/HANDOFF.md) §1.

## The vault

**Enforces:** monthly cap, per-payment cap, meter allowlist, owner-only policy
changes, pause, and an owner-withdraw that still works while paused. The spend
counter resets on the first of each calendar month.

**Does not move tokens yet.** `balance_ngn` is an internal ledger. The real
version credits on an NEP-141 `ft_on_transfer` and settles USDC to the treasury.
If anyone implies money moves onchain today, they are wrong.

```
vault/src/policy.rs   pure rules, no near-sdk, unit-tested
vault/src/lib.rs      contract wrapper, env-based tests
```

**`policy.rs` has a Python twin.** [`apps/backend/policy.py`](../backend/policy.py)
mirrors its error codes and sentences, and a backend test reads this Rust source and
fails if they drift. Change both together; `bun run test` will tell you if you didn't.

The wasm comes from plain `cargo build` (214 KB, 2026-10-26). `cargo-near` is only
needed for the ABI JSON and deploy convenience; neither it nor `near-cli` is required.

## Deployed

**`stark-vault.testnet`**, deployed 2026-10-26 against `near-sdk` 5.29.1. That account's
key is deliberately not in this repo.

`new` was called with `owner` and `treasury` both `stark-vault.testnet`, caps of ₦30,000
monthly / ₦10,000 per payment, and `0101170026583` as the only allowlisted meter. On chain
that has been exercised end to end: `fund`, a `pay` inside the caps (accepted,
`payment_id` incremented), a `pay` above the per-payment cap (rejected) and a `pay` to a
meter not on the allowlist (rejected).

`pay` signed through `apps/backend/near_tx.py` has been broadcast against this account,
which is how the two encoder bugs below were found: `TransactionV0` has no version tag,
and `Signature` carries a leading key-type byte.
