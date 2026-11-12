# @stark/contracts

NEAR smart contracts, in Rust. Today there is one: [`vault/`](vault), which holds a
user's USDC and spending rules, and is the account the agent's `pay()` calls are signed
against.

## Setup

Only needed to change the contract. The web app, the dashboard and the backend run
without it.

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh   # once
rustup target add wasm32-unknown-unknown
cargo install cargo-near                                          # for the deployable wasm
```

## Commands

From the repo root:

| Command | What it does |
|---|---|
| `bun --filter @stark/contracts run contract:test` | 81 unit tests on the host |
| `bun --filter @stark/contracts run contract:check` | type-check the wasm target |
| `bun --filter @stark/contracts run contract:build` | deployable wasm → `vault/target/near/stark_vault.wasm` (193 KB) |

Or from `vault/`: `cargo test`, `cargo near build non-reproducible-wasm`.

The backend ships a copy of the build at `apps/backend/assets/stark_vault.wasm`, which
new vaults are deployed from (`STARK_VAULT_CODE=assets/stark_vault.wasm`). After changing
the contract, rebuild and copy it there.

These are not turbo tasks, so `bun run test` and `bun run build` work without a Rust
toolchain.

If cargo reports no toolchain although rustup is installed, your shell's `$HOME` is
probably redirected; set `RUSTUP_HOME` to the real `~/.rustup`. See
[`docs/HANDOFF.md`](../../docs/HANDOFF.md) §1.

## The vault

**Holds:** the user's USDC (Circle's NEP-141 token on mainnet, `usdc.fakes.testnet` on
testnet). Deposits arrive by `ft_transfer_call`; the `msg` is a reference applied once,
so a repeated deposit is sent back. Only the funder and the treasury may deposit, and a
`msg` longer than 128 bytes is refused: anyone else's USDC, or an overlong `msg`, is
returned in full without writing state, so a stranger cannot spend the vault's storage
on references or put events in its log. Events and transfer memos are serialised as
JSON, never spliced into a string.

**Enforces:** monthly cap, per-payment cap, meter allowlist, owner-only policy changes,
pause, and an owner withdraw that still works while paused. Caps are in naira; `pay`
converts at `usdc_per_kngn`, which only the funder sets. The spend counter resets on the
first of each calendar month.

**Settles:** `pay` sends the bill's USDC to the treasury, which pays the biller in naira.
If that transfer fails, the payment is reversed before `pay` returns (`settled: false`).
A bank withdrawal's USDC goes back to the treasury (`debit`), and a failed bill's USDC
comes back from the treasury with `msg = "refund:<payment_id>"`, for that exact amount
only.

**Roles:** the agent's function-call key may only call `pay` on its own vault. The
funder sets the rate, deposits and debits. The owner changes policy. So a leaked agent
key cannot move the rate, the caps or where the money goes.

**Hand-over:** ownership moves in two steps. The owner calls `propose_owner(owner)`, and
nothing changes until that account calls `accept_owner()`; a new proposal replaces the
last, and `get_pending_owner` shows the one in flight. A mistyped account id can never
accept, so the vault cannot be handed to an account nobody holds. (`set_owner` is gone.)

**Upgrading existing vaults.** Vaults created from the global contract run whatever code
is published under the funder's id, so a change reaches them only once it is published
again (HANDOFF §13.3):

```sh
cd apps/backend
STARK_FUNDER_ACCOUNT=... STARK_FUNDER_KEY=... STARK_AGENT_KEY=... STARK_BROADCAST=1 \
  python -m app.modules.chain.vault_chain publish assets/stark_vault.wasm
```

Vaults created with `STARK_VAULT_CODE=<path>` carry their own copy and keep the old code
until each is redeployed. The contract state layout is unchanged (the pending owner sits
under its own storage key), so existing state reads as before.

```
vault/src/policy.rs   pure rules, no near-sdk, unit-tested
vault/src/lib.rs      contract, token movements and callbacks
vault/src/tests.rs    unit tests, including callbacks with faked transfer results
```

**`policy.rs` has a Python twin.** [`apps/backend/app/modules/agent/policy.py`](../backend/app/modules/agent/policy.py)
mirrors its error codes and sentences, and a backend test reads this Rust source and
fails if they drift. Change both together.

## Deployed

**Testnet, USDC vaults (2026-11-12).** Parent and treasury `stark-usdc-fcb734.testnet`;
each user's vault is `u-<id>.stark-usdc-fcb734.testnet`, with the code deployed into it.
Checked end to end on chain: a 20 USDC deposit (the same reference again was sent back),
a ₦5,000 `pay` through the agent key that moved 3.205130 USDC to the treasury, and a
`pay` over the per-payment cap and one to an unlisted meter, both refused by the contract.

**`stark-vault.testnet`**, deployed 2026-10-26, is the earlier ledger-only vault. Its caps
were ₦30,000 monthly / ₦10,000 per payment with `04512345678` as the only allowed meter;
`fund`, a `pay` inside the caps and two refused `pay`s ran on it. It holds no tokens.
