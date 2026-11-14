<div align="center">

# Stark

**An AI agent that pays your bills when you ask, and cannot spend past the limits you set.**

Nigerian prepaid electricity, airtime, data and TV, by text or voice, in naira.
Your money is USDC in a NEAR smart contract that holds the rules.

[**Open the app**](https://dash.hellostark.xyz) · [**Read-only demo**](https://dash.hellostark.xyz/demo) · [**Telegram bot**](https://t.me/hellostarkai_bot) · [**Website**](https://hellostark.xyz)

![license](https://img.shields.io/badge/license-MIT-1f1f1f?style=flat-square)
![track](https://img.shields.io/badge/NEAR%20HACKATHON-real--world%20money%20%C2%B7%20AI%20security%20%C2%B7%20private%20AI%20%C2%B7%20agent%20economy-00a67e?style=flat-square)
![contract](https://img.shields.io/badge/contract-Rust%20%C2%B7%20near--sdk-b7410e?style=flat-square)
![api](https://img.shields.io/badge/api-Python%20%C2%B7%20FastAPI-3776ab?style=flat-square)
![web](https://img.shields.io/badge/web-TypeScript%20%C2%B7%20TanStack-3178c6?style=flat-square)

</div>

---

## For judges

**Tracks entered**

| Track | What in Stark answers it | Where to check |
|---|---|---|
| **Real-World Money** (lead) | USDC on NEAR pays real Nigerian bills (electricity, airtime, data, TV) in naira, by text or voice, on mainnet | The [mainnet vaults](#the-vault) and their `payment_count`; `apps/backend/app/modules/vending/` |
| **AI Security & Defense** | Spending limits live in a per-user contract, not in the prompt. The agent holds a function-call key that can only call `pay` on one vault. Payment guards run in code after the model answers, and the model runs in a NEAR AI Private TEE | [`policy.rs`](apps/contracts/vault/src/policy.rs), `payment_gate.py`, [Security model](#security-model) |
| **Privacy & Private AI** | The agent's model, the payment judge and voice transcription (Whisper) run on NEAR AI Cloud in a Private TEE, so the user's messages, balances and bills are read inside an enclave. A non-TEE model of the same speed was measured and rejected | [The agent](#the-agent), [Design decisions](#design-decisions) |
| **Agent Economy** | An agent that spends for its user on real services, within limits it cannot change, and moves money across chains with NEAR Intents (1Click) | [The agent](#the-agent), [Money in and out](#money-in-and-out) |

**Verify it in five minutes, with no account and no keys**

1. Open the read-only sample at [dash.hellostark.xyz/demo](https://dash.hellostark.xyz/demo),
   or `curl https://geddon.hellostark.xyz/v1/demo`.
2. Read a live mainnet vault. It shows real caps, a real balance and real payments:

   ```sh
   curl -s https://rpc.mainnet.near.org -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"query","params":{"request_type":"call_function","finality":"final","account_id":"u-fbda9ededd79777a.funder.moonboys-stark.near","method_name":"get_state","args_base64":"e30="}}' \
     | python3 -c 'import json,sys; print(bytes(json.load(sys.stdin)["result"]["result"]).decode())'
   ```

3. Confirm the agent's key can only call `pay`. Send the same request with
   `"request_type":"view_access_key_list"` and without `method_name` and `args_base64`.
   It returns one `FunctionCall` key with `method_names: ["pay"]`.
4. Sign up at [dash.hellostark.xyz](https://dash.hellostark.xyz), link a Telegram chat
   in the app, and message [@hellostarkai_bot](https://t.me/hellostarkai_bot).

## Contents

**The product**
[Screenshots](#screenshots) ·
[Why this exists](#why-this-exists) ·
[What you can say](#what-you-can-say) ·
[Features](#features) ·
[What works today](#what-works-today)

**How it works**
[Architecture](#architecture) ·
[One payment, step by step](#one-payment-step-by-step) ·
[The vault](#the-vault) ·
[The agent](#the-agent) ·
[Telegram](#telegram) ·
[Money in and out](#money-in-and-out) ·
[Security model](#security-model) ·
[Design decisions](#design-decisions)

**For developers**
[Repository](#repository) ·
[Run it locally](#run-it-locally) ·
[Configuration](#configuration) ·
[API and data](#api-and-data) ·
[Operations](#operations) ·
[Troubleshooting](#troubleshooting) ·
[Contributing](#contributing)

[Built at NEAR HACKATHON](#built-at-near-hackathon) · [License](#license)

---

# The product

## Screenshots

<img src="docs/screenshots/landing.png" width="900" alt="The Stark landing page">

*The landing page at [hellostark.xyz](https://hellostark.xyz).*

| The read-only sample account | Sign in |
|---|---|
| <img src="docs/screenshots/demo.png" width="430" alt="The demo dashboard"> | <img src="docs/screenshots/login.jpg" width="430" alt="The sign-in page"> |
| [dash.hellostark.xyz/demo](https://dash.hellostark.xyz/demo): fake data, no login, a ₦15,000 approval waiting | No passwords: Google or an email code |

## Why this exists

Paying for prepaid electricity in Nigeria means opening an app, remembering a 13-digit
meter number and topping up by hand, often at night when the lights are already out.
Paying is easy. Remembering and retyping the number is the hard part.

Stark replaces the form with one sentence: **"top up my meter with 5,000."** It answers
questions from your real balance and bills, and it pays only when you ask. Its limits are
in a contract, so the contract refuses an out-of-limit payment whether it came from a bad
prompt, a model bug or a leaked server key.

Two rules shape the design:

1. **A question never spends money.** Asking "how much is left?" and paying are
   different actions, and code keeps them apart, not the prompt.
2. **Users never see the chain.** Balances, caps and receipts are in whole naira. Adding
   money is the only place a coin appears. The user sends an amount in the coin they
   choose, and the exchange rate sets the naira they get. The interface never shows
   USDC, the vault or the chain.

## What you can say

| You say | Stark does | What is enforced |
|---|---|---|
| "How much can I spend this month?" | Reads the cap, this month's spend and the balance | Nothing can be paid on a question |
| "What bills are due?" | Lists saved bills with their dates | Read-only |
| "Top up my meter with 5,000" | Prices it, checks the rules, signs `pay()` | Cap, allowlist, balance, rate |
| "Pay 15,000 for electricity" | Puts it in Approvals instead of paying | Over a cap, so the owner approves |
| "If I pay DStv and top up 5,000, how much is left?" | Does the arithmetic, pays nothing | Read as a question, so `pay_bill` refuses |
| "Add my MTN line, 0803…" | Saves the bill for next time | Never pays while saving |
| "Recharge my airtime" | Asks how much | No amount said, so it refuses with `amount_required` |
| "Pause everything" | Turns on the kill switch | Contract `pause()` and the app switch |

## Features

**For the person paying**

- Talk or type. Whisper transcribes voice notes, and replies can be spoken.
- Electricity, airtime, data and TV in one place, with plan prices from the biller.
- Saved bills with short names ("Home meter"), so you type a meter number once.
- Approvals: a payment over a limit becomes a request you accept or deny.
- Receipts that name the bill and link the on-chain transaction.
- Telegram, so there is no second app to install.
- One switch that stops every payment, in the app and in the contract.

**For whoever trusts it with money**

- The caps are in the contract: monthly, per payment, and a list of allowed meters.
- The server's key can only call `pay()` on one vault.
- Nobody, Stark included, can change a vault's code after it is deployed.
- A retried deposit cannot credit twice, and a failed transfer reverses its payment.

**For developers**

- One typed client shared by the dashboard and the website (`packages/api`).
- The API contract is written down in [`docs/API.md`](docs/API.md) and only grows.
- With no keys set, the server uses a deterministic model and dry-run payments.

## What works today

Last checked **2026-11-14**, against `main` and the live deployments.

| Part | State |
|---|---|
| Vault contract | **Live.** The testnet reference vault holds USDC with monthly and per-payment caps and an allowlist. It has one settled payment and has refused over-cap and unlisted-meter payments. |
| Mainnet | **Live.** `funder.moonboys-stark.near` is the funder and treasury and holds USDC. Three user vaults have real contract code, one `pay`-only key each, a USDC balance and live policies. |
| Agent | **Live.** NEAR AI in a Private TEE, with Whisper for voice. 2–3s for a question, 5–15s for a payment. |
| Web app | **Live** at [dash.hellostark.xyz](https://dash.hellostark.xyz), with a read-only sample at [/demo](https://dash.hellostark.xyz/demo). |
| API | **Live** at `geddon.hellostark.xyz` (`/health`). Swagger is local only. |
| Sign-in and storage | **Live.** Neon Auth, and one wallet and one receipt trail per account in Neon Postgres. |
| Telegram | **Live** as [@hellostarkai_bot](https://t.me/hellostarkai_bot), with text and voice notes. |
| Bill payment in naira | **Live.** Real bills have been paid end to end in production: USDC out of the vault on chain, naira to the biller through Flutterwave, and the token or confirmation back in the receipt. |
| Crypto deposits | **Live.** Real deposits have completed through NEAR Intents (1Click) on mainnet and been credited to the user's vault. |

---

# How it works

## Architecture

```text
                       ┌──────────────────────────┐
   browser ──────────▶ │ dashboard  (TanStack)    │
                       ├──────────────────────────┤
   Telegram ─────────▶ │ bot webhook  /v1/tg/…    │
                       └────────────┬─────────────┘
                                    │  Bearer token (Neon Auth JWKS)
                       ┌────────────▼─────────────┐
                       │  FastAPI  ·  /v1         │
                       │  auth · bills · wallet   │
                       │  approvals · control     │
                       └───┬──────────┬───────────┘
                           │          │
              ┌────────────▼──┐   ┌───▼──────────────────────┐
              │  Agent        │   │  Money loop (every 30s)  │
              │  NEAR AI TEE  │   │  deposits · float ·      │
              │  tools, not   │   │  settlements · alerts    │
              │  free text    │   └───┬──────────────┬───────┘
              └───────┬───────┘       │              │
                      │               │              │
        ┌─────────────▼───────┐  ┌────▼─────────┐  ┌─▼────────────┐
        │ Vault contract      │  │ Neon Postgres│  │ Flutterwave  │
        │ USDC · caps · keys  │  │ 19 tables    │  │ naira rails  │
        └─────────┬───────────┘  └──────────────┘  └──────┬───────┘
                  │ USDC on NEAR                         │ naira
                  ▼                                      ▼
            Stark treasury ───────────────────────▶ the biller
```

There are three parts:

- **The agent** is a tool-calling loop on NEAR AI. The model chooses which tool to call.
  It never chooses the amount, the meter or the recipient on its own.
- **The money loop** runs in the background. It confirms open deposits, watches the
  Flutterwave float and the treasury's USDC, settles bills and raises operator alerts.
- **The vault** is one contract per user. It is the only thing that can move that
  user's USDC, and it only sends it to the treasury.

## One payment, step by step

```text
"top up my meter with 5,000"
  │
  ├─ 1. Snapshot: balance, cap, spend, bills and recent activity go into the prompt
  ├─ 2. A short, separate model call labels the message: PAY, AGAIN, or not a payment
  ├─ 3. The model proposes pay_bill(bill_id, 5000)
  ├─ 4. Guards in code (PaymentGate):
  │       labelled as a payment?       if not: not_a_payment_request
  │       plan price matches?          if not: plan_price_mismatch
  │       an amount was said?          if not: amount_required
  │       is it the amount said?       if not: amount_mismatch
  │       paid minutes ago?            if so: duplicate_payment, unless AGAIN
  ├─ 5. Backend policy: caps, float, pause, bill ownership
  ├─ 6. The backend signs pay("0101…", 5000) with the vault's agent key
  ├─ 7. The contract checks pause, caps, allowlist and balance, then books it
  ├─ 8. The contract sends USDC to the treasury, and reverses if that fails
  ├─ 9. The receipt is written; Flutterwave buys the token and delivers it
  └─ 10. The reply names the bill and the amount, and links the transaction
```

Step 4 exists because of a real failure. On 2026-10-24, "recharge my airtime number"
bought ₦1,000 twice, 29 seconds apart, because the model chose the amount. The guard
now requires the amount to be one the user said, so "pay 500" cannot become ₦5,000.

## The vault

Each user gets one contract under the funder account, named `u-<hex>.<funder>`.

| Network | Account | What it is |
|---|---|---|
| testnet | [`u-e2e541dbcb1.stark-usdc-fcb734.testnet`](https://testnet.nearblocks.io/address/u-e2e541dbcb1.stark-usdc-fcb734.testnet) | Reference vault: USDC, caps, one settled payment |
| mainnet | [`funder.moonboys-stark.near`](https://nearblocks.io/address/funder.moonboys-stark.near) | Funder and treasury. Holds USDC and creates vaults |
| mainnet | [`u-312d6989246f5965`](https://nearblocks.io/address/u-312d6989246f5965.funder.moonboys-stark.near), [`u-fbda9ededd79777a`](https://nearblocks.io/address/u-fbda9ededd79777a.funder.moonboys-stark.near), [`u-278a146620c99d70`](https://nearblocks.io/address/u-278a146620c99d70.funder.moonboys-stark.near) `.funder.moonboys-stark.near` | User vaults, live since 2026-11-13, with 6, 8 and 0 payments on 2026-11-14 |

### How the limits are enforced

| Rule | How it is enforced | How to check it |
|---|---|---|
| The money is USDC in the user's own vault | Deposits arrive as NEP-141 transfers. `pay()` sends the bill's USDC to Stark's treasury, or reverses the payment if the transfer fails | `get_state`, and [one settled payment](https://testnet.nearblocks.io/txns/Ho5iZ7HaB7S235FDuqw7Ar5XfCERBKq7XEdxBXeHhcR8) |
| A monthly cap and a per-payment cap, in naira | `pay()` checks both before booking | `get_policy` |
| Only listed meters can be paid | `pay()` checks the allowlist | `allowed_meters` in `get_policy` |
| The server's key can only call `pay` | Each vault has exactly one access key, a function-call key limited to `pay` on that vault | `view_access_key_list` |
| That key cannot change the rate or the policy | Only the funder or the owner can | `tests.rs` |
| The funder cannot inflate the rate | `set_rate` refuses a rate above the owner's ceiling or more than 5% above the day's opening rate. Only vaults deployed from the current code have this; the backend bounds the rate for all of them | `tests.rs` |
| Nobody can change a vault's code | The code is deployed into the vault, there is no full-access key, and there is no upgrade method | `view_access_key_list` |
| An over-cap payment waits for the owner | The backend queues it, and the owner calls `pay_approved()` | Approvals |
| A question is never paid | A model call labels every message, and anything not labelled a payment, or a failed call, is refused in code | `tests/test_agent.py` |
| One switch stops everything | `pause()` in the contract and in the app | Settings |

A leaked server key cannot withdraw, change the policy, pay a different contract or even
pause. NEAR rejects any other call as `INVALID_TRANSACTION` before the contract runs.

### Who may call what

| Method | Who may call | Does |
|---|---|---|
| `pay(meter, amount_ngn)` | Agent key or owner | Checks every rule, books the payment, sends USDC to the treasury |
| `pay_approved(...)` | Owner only | The same without the caps. Pause, allowlist and balance still apply |
| `ft_on_transfer(...)` | Funder or treasury | Accepts a deposit. A reused reference is sent back untouched |
| `debit`, `withdraw` | Owner | Takes USDC out for a withdrawal |
| `set_rate` | Funder | Sets the naira rate, within the limits above |
| `set_rate_ceiling` | Owner | Caps the rate the funder may set |
| `set_policy`, `add_meter`, `remove_meter`, `pause`, `unpause` | Owner | Administration |
| `propose_owner`, `accept_owner` | Owner, then the nominee | Hands a vault to the user's own account |
| `get_state`, `get_policy`, `get_payment`, `is_applied`, `can_pay` | Anyone | Read-only |

`get_state` returns the owner, the balance in USDC and naira, the rate, this month's spend
and remaining cap, lifetime totals and the pause flag. `get_policy` returns the caps and
the meter allowlist. A refused payment comes back as a code: `paused`, `over_cap`,
`over_per_payment_cap`, `meter_not_allowed` or insufficient balance. The app turns each
one into a plain-English message.

The contract is three files: [`policy.rs`](apps/contracts/vault/src/policy.rs) (the
rules), [`lib.rs`](apps/contracts/vault/src/lib.rs) (money and state) and
[`tests.rs`](apps/contracts/vault/src/tests.rs).

## The agent

The agent is a tool loop. The model sees a snapshot of the account and picks from seven
tools, and the backend decides whether the resulting action is allowed.

| Tool | Spends money? | Purpose |
|---|---|---|
| `get_state` | No | Balance, cap, spend, pause |
| `list_bills` | No | Saved bills and what is due |
| `recent_activity` | No | Latest receipts |
| `find_plans` | No | Data and TV plans with prices |
| `pay_bill` | **Yes** | Pays one bill an exact naira amount |
| `add_bill` | No | Saves a bill for later |
| `add_money` | No | Starts a deposit, crypto or bank |

**Models.** The agent runs on NEAR AI Cloud in a Private TEE. The default model is
`Qwen/Qwen3.6-35B-A3B-FP8`. On 2026-11-13 it took 1.4s a turn and made the same tool
calls as slower models across a six-turn test. Same day, same prompt:

| Model | Time per turn | Note |
|---|---|---|
| `Qwen/Qwen3.6-35B-A3B-FP8` | 1.4s | Default |
| `google/gemini-2.5-flash-lite` | 1.4s | Not a TEE model. Said a deposit had arrived when it had only started |
| `deepseek/deepseek-v4.1-flash` | 2.9s | |
| `Qwen/Qwen3.8-27B` | 17.9s | Single turns reached 81s |

Voice in is `openai/whisper-large-v3`. Voice out is ElevenLabs Flash when a key is set,
and text otherwise. A question takes 2–3 seconds. A payment takes 5–15, because it makes
several tool calls.

**A snapshot instead of read tools.** Putting the ~2KB account snapshot in the prompt is
faster than a tool call, so the read tools are left out when the snapshot already has
the answer. That kept a 1.2s answer from becoming 2.5s. If the snapshot fails, every
tool comes back, because a wrong number is worse than a slow one.

**The prompt is not a security boundary.** Every rule that matters is checked again
after the model answers. The amount must be one the user said, plan prices must match,
a question is refused, and the contract checks caps and the allowlist on chain anyway.

## Telegram

People already send voice notes in chat apps, so Stark answers in Telegram as well as in
the web app.

- **Same agent as the web app.** `@hellostarkai_bot` uses the same agent, tools and
  vault. There is no second implementation and no second balance.
- **Linking is explicit.** The app issues a short code, and sending it to the bot links
  that one chat to that account. Codes expire and allow a limited number of tries.
  Unlinked chats get nothing, not even a balance. You can see and remove linked chats
  in the app.
- **Voice notes work.** The bot fetches Telegram's audio, transcribes it and answers on
  the same path as browser voice.
- **Reminders go to the right chats.** Each account gets renewal reminders about its own
  bills, in its own linked chats.
- **No double payments from retries.** The bot records each Telegram update ID, so a
  retried webhook cannot pay twice. The webhook refuses everything until both the bot
  token and the secret are set.
- **Buttons.** A linked chat gets a menu: Balance, Add money, Pay a bill, Recent
  payments. A crypto deposit shows the address and amount with Copy buttons. A bank
  deposit is a Pay button. A question with fixed answers, like which network, shows
  them as buttons, and a tap goes through the same checks as typed text.

`app/modules/telegram` and the web app's Talk screen share one turn pipeline.

## Money in and out

Billers in Nigeria take naira, not USDC, so the last step happens off chain:

```text
user's vault ──USDC──▶ Stark treasury ──Flutterwave──▶ biller ──token/SMS──▶ user
```

- **Flutterwave** handles all naira: bill payments, deposits by bank transfer, card or
  USSD, withdrawals and the bill catalogue.
- **The float** is Stark's naira balance at Flutterwave. A deposit can be spent at once,
  but it reaches the float only when Flutterwave settles it. If the float cannot cover a
  payment, Stark refuses it with `float_low` before signing anything.
- **Crypto deposits** use NEAR Intents (1Click) on mainnet. Stark creates a quote, the
  user sends to the address it returns, and the money loop credits the account.
- **The rate** is Paycrest's live naira/USDC rate plus Stark's spread. The backend refuses
  a rate outside the operator's range or one that moved too far from the last accepted
  rate. The last accepted rate stays valid for 15 minutes.
- **Withdrawals** go to a Nigerian bank account through Flutterwave, with the account
  name checked and a daily limit, or out as USDC through a 1Click swap.
- **Card money is held** for 72 hours by default, because a card charge can be disputed
  after the cash is gone. Bank transfer and USSD are not held.
- **Operator alerts** appear on the admin page when the float or the treasury's USDC
  runs low, or when coverage goes negative.

## Security model

| Threat | What stops it |
|---|---|
| Prompt injection asks for a bigger payment | The amount must be one the user said, plan prices must match, and the contract checks caps and the allowlist again |
| The model invents a payee | The contract only pays from the vault to the treasury, and the backend picks the biller, not the model |
| A leaked agent key | It can only call `pay` on one vault, with a NEAR allowance. It cannot withdraw or change the policy or rate |
| A leaked backend session | Every `/v1` route checks a Neon Auth token against the provider's keys |
| Malicious vault code | No upgrade method and no full-access key, so the deployed code cannot change |
| A replayed deposit | Each deposit reference is applied once, and a repeat is sent back untouched |
| Spam deposits to fill a vault's storage | Only the funder and the treasury may deposit, with a size-limited message |
| A replayed Telegram update | Each update ID is processed once |
| A card charge reversed after spending | Card money is held 72 hours before it can be withdrawn |
| An operator mistypes a rate | The backend bounds the rate and how far it can move, and stale rates expire after 15 minutes. New vaults also enforce the owner's ceiling and a 5% daily limit on chain |

**Known limits**

- On mainnet, each vault's `owner` is the funder account, not the user's own account.
  `propose_owner` and `accept_owner` exist but have not been run, so owner powers
  (policy, withdrawal) sit with the team. The spending rules that protect the user are
  not owner powers, and they bind the owner too through `pay_approved`.
- The treasury holds a full-access key for crypto withdrawals and refunds, because
  `ft_transfer` needs a 1-yocto deposit that a function-call key cannot attach. It holds
  a small, capped balance, but it is a hot key.
- The float is a custodial naira balance at Flutterwave, because billers only take naira.

## Design decisions

- **Why a contract per user?** "The agent cannot overspend" is only true if the limit
  lives somewhere the agent cannot write. A shared ledger would put the rules back in
  the backend.
- **Why naira in the contract?** Users think in naira. The contract keeps the caps and
  the rate in naira and converts once, at payment time, so rounding happens in one place.
- **Why USDC, not a naira stablecoin?** USDC on NEAR is liquid and has a real treasury
  flow. Billers still need naira, so the swap happens once, off chain.
- **Why Telegram?** People already use chat apps for voice notes. The bot costs one
  webhook and reuses the whole turn pipeline.
- **Why a TEE model?** The prompt carries the user's balance, bills and messages, so the
  default model runs in a Private TEE. A non-TEE model of the same speed was measured and
  rejected (see [The agent](#the-agent)).
- **Cost.** A vault costs about 2 NEAR of storage on testnet. On mainnet the code is
  published once as a global contract, so each vault pays only for its own state.
- **What we did not build.** Card issuance, credit, shared household accounts and an
  on-chain biller registry.

---

# For developers

## Repository

| Path | Contents | Stack |
|---|---|---|
| [`apps/contracts`](apps/contracts) | The vault: USDC, caps, allowlist, pause, payment records | Rust, near-sdk |
| [`apps/backend`](apps/backend) | API, agent, bill payment, Telegram, voice, money loop, 30 modules | Python, FastAPI |
| [`apps/dashboard`](apps/dashboard) | The app people use | TanStack Start and Query |
| [`apps/website`](apps/website) | Marketing site, pre-rendered | React Router |
| [`packages/ui`](packages/ui) | Design system | shadcn/ui on Base UI, Tailwind v4 |
| [`packages/api`](packages/api) | Typed client for `/v1` | TanStack Query |
| [`docs`](docs) | [`API.md`](docs/API.md) contract, [`FRONTEND.md`](docs/FRONTEND.md), [`HANDOFF.md`](docs/HANDOFF.md) engineering log | |

**Where to start reading**

- The rules: `apps/contracts/vault/src/policy.rs`, then `pay()` in `lib.rs`.
- The agent: `Agent.respond` and `_tools_for` in `apps/backend/app/modules/agent/agent.py`.
- The guards: `PaymentGate` in `payment_gate.py`, and the payment judge in
  `payment_intent.py`.
- Signing: `apps/backend/app/modules/chain/near_tx.py` and `vault_chain.py`.
- The money loop: `apps/backend/app/modules/payment/`, `treasury/` and `liquidity/`.

## Run it locally

**Prerequisites:** Node 22+, Bun 1.3+ and Python 3.9+. Rust only if you change the
contract.

```sh
bun install
cd apps/backend && bun run setup && cd ../..   # Python venv for the API
bun dev                                       # website :5173, dashboard :5174, API :8000
```

The API needs `DATABASE_URL` (a Neon pooler URL; the schema creates itself) and
`NEON_AUTH_BASE_URL` (the same branch's Auth URL). The team keeps both in Infisical. Run
`infisical login` once, and the `dev` scripts load them.

With nothing else set, the server runs offline. Payments are dry runs, nothing reaches a
chain, and a deterministic model stands in for the LLM.

**Contract**

```sh
cd apps/contracts/vault
cargo test                                   # every refusal the contract can produce
cargo near build non-reproducible-wasm
```

On testnet, point `STARK_VAULT_CODE` at the wasm to deploy vaults (about 2 NEAR of
storage per user). On mainnet, publish the code once as a global contract, and vaults
reference `global:<funder>`:

```sh
python -m app.modules.chain.vault_chain publish ../contracts/vault/target/near/stark_vault.wasm
```

**Checks**

```sh
bun check    # typecheck, lint, backend unit tests
bun smoke    # end-to-end checks against a running API
```

## Configuration

Everything is optional except the two Neon values. Each variable is documented in
[`apps/backend/.env.example`](apps/backend/.env.example).

| Variable | Effect when unset |
|---|---|
| `DATABASE_URL`, `NEON_AUTH_BASE_URL` | **Required.** The server refuses to start |
| `NEAR_AI_API_KEY`, `NEAR_AI_MODEL`, `NEAR_AI_STT_MODEL` | Deterministic model, no voice |
| `ELEVENLABS_API_KEY` (plus voice and model IDs) | Replies are text |
| `FLW_SECRET_KEY`, `FLW_SECRET_HASH`, `STARK_APP_URL` | Nothing can be sold or withdrawn (501); test top-ups only |
| `STARK_FUNDER_ACCOUNT`, `STARK_FUNDER_KEY`, `STARK_AGENT_KEY`, `STARK_VAULT_CODE` | Payments are booked off chain only |
| `STARK_NETWORK`, `STARK_USDC_TOKEN`, `STARK_BROADCAST` | Testnet, `usdc.fakes.testnet`, broadcast off |
| `STARK_TREASURY_NEAR_ACCOUNT`, `STARK_TREASURY_KEY`, `ONECLICK_API_KEY` | Crypto deposits and withdrawals off |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | The webhook refuses every request |
| `STARK_ADMIN_KEY` | Every admin request is refused. Under 32 characters, the server will not start |
| `STARK_DOCS=1` | No Swagger, no ReDoc, no spec |
| `STARK_STUB_RESET=1` | `POST /v1/_stub/reset` is 404 |

Operator limits (caps, holds, thresholds, rate bounds, rate limits) are set on
`/admin → Limits` and take effect within 15 seconds, with no deploy. The environment
variable only sets the default.

## API and data

The API is at `https://geddon.hellostark.xyz`. Every `/v1` route except `/v1/demo` and
the Telegram webhook needs `Authorization: Bearer <Neon Auth token>`. The full contract
is in [`docs/API.md`](docs/API.md).

The routes cover account state, bills, payees and plans, the wallet (deposits,
withdrawals, rates), payments and activity, limits, approvals, the pause switch, voice,
Telegram linking, operator admin and health. `GET /v1/state` returns everything the
dashboard needs in one call. Errors are `{code, message, detail}` with stable codes such
as `unauthorized`, `float_low`, `over_cap` and `rate_limited`. Swagger is local only
(`STARK_DOCS=1`, then `/docs`).

Data lives in 19 Neon Postgres tables, created on first boot. Schema changes only add.
Money is stored as integer naira, never as floats. Chain writes go through `chain_ops`,
so retrying one is safe.

## Operations

- **`/admin`** shows the float, treasury, coverage, alerts, limits, fees and pots. It
  needs `X-Stark-Admin-Key`.
- **Operator limits** cover caps, holds, thresholds, rate bounds and per-minute rate
  limits. Changes take effect within 15 seconds, with no deploy.
- **Turn log.** `STARK_TURN_LOG=1` writes one JSON line per turn (transcript, reply,
  actions, timing per stage) plus the uploaded clip. Read it at `GET /v1/turnlog`.
- **Alerts** for a low float, a low treasury and negative coverage appear on the admin
  page and clear when they recover.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Address already in use` | An old process holds the port: `lsof -nP -iTCP:8000 -sTCP:LISTEN` |
| Every request is 401 | Not signed in, or `NEON_AUTH_BASE_URL` belongs to a different Neon branch than `DATABASE_URL` |
| Dashboard shows no data | The API is not on `127.0.0.1:8000` |
| `Please enable IP Whitelisting` from Flutterwave | This machine's IP is not on the Flutterwave dashboard's list, test mode included |
| Payments succeed but no token | The biller call failed or is still pending. Check the receipt's status and the Flutterwave logs. Locally, with no Flutterwave keys, payments are dry runs |
| `float_low` | The Flutterwave float has not settled. See `/admin` |
| `/docs` is 404 | Expected in production. Run locally with `STARK_DOCS=1` |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). The ground rules:

- Money in the app is whole naira, stored as integers. No floats.
- What users see has no crypto terms. Chain detail belongs in docs like this one.
- [`docs/API.md`](docs/API.md) is frozen. Changes may only add to it.
- Never commit secrets.

---

## Built at NEAR HACKATHON

Everything here was written during the hackathon. The first commit is from
**2026-10-20**, the day after the announcement, and no code comes from an earlier
project. Tracks: **Real-World Money** (lead), **AI Security & Defense**, **Privacy &
Private AI** and **Agent Economy** (see [For judges](#for-judges)).

**Libraries and services**

| Part | Used for |
|---|---|
| near-sdk (Rust) | The vault contract |
| FastAPI and pydantic | The API |
| React, TanStack Start, Router and Query | The web app |
| Tailwind v4 and shadcn/ui on Base UI | The design system |
| NEAR AI Cloud | The agent's model and Whisper transcription, in a Private TEE |
| NEAR Intents (1Click) | Crypto deposits and withdrawals |
| Neon | Postgres and sign-in |
| Flutterwave | Naira: bill payments, bank deposits and withdrawals |
| ElevenLabs | Spoken replies |
| Telegram Bot API | The Telegram bot |

AI coding assistants were used.

## License

MIT. See [`LICENSE`](LICENSE).
