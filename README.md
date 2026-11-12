# Stark

Stark is an AI agent that pays everyday bills when you ask by voice or chat. It pays
Nigerian prepaid electricity, airtime, data and TV. Your money is USDC in your own NEAR
smart contract, and that contract enforces your spending limits.

Built for NEAR HACKATHON, 2026-11-01 to 2026-11-14. Tracks: `realworld` (lead),
`security` and `agents`.

## How the limits are enforced

Each user has a vault contract that holds their USDC. Every payment goes through it, and
the contract refuses any payment that breaks a rule, whatever the agent was told.

| Rule | How it is enforced | How to check it |
|---|---|---|
| The money is USDC in the user's own vault | Deposits arrive as NEP-141 transfers. `pay()` sends the bill's USDC to Stark's treasury, or reverses the payment if the transfer fails. | `get_state` on [`u-e2e541dbcb1.stark-usdc-fcb734.testnet`](https://testnet.nearblocks.io/address/u-e2e541dbcb1.stark-usdc-fcb734.testnet), and [one settled payment](https://testnet.nearblocks.io/txns/Ho5iZ7HaB7S235FDuqw7Ar5XfCERBKq7XEdxBXeHhcR8) |
| A monthly cap and a per-payment cap, in naira | `pay()` checks both. | `get_policy` on the same vault |
| Only meters on the list can be paid | `pay()` checks the list. | `allowed_meters` in `get_policy` |
| The server's key can only call `pay` | Each vault has one access key, a function-call key limited to `pay`. | `view_access_key_list` on the vault |
| That key can't change the naira rate | Only the funder can call `set_rate()`. | `apps/contracts/vault/src/tests.rs` |
| Nobody can change a vault's code, Stark included | The code is deployed into each vault, the vault has no full-access key, and the contract has no upgrade method. | `view_access_key_list` shows a single `FunctionCall` key |
| A payment over a limit waits for the owner | The backend queues it, and the owner approves it with `pay_approved()`. | Approvals, in the app |
| A question is never paid | The agent gets no tools on a question, and `pay_bill` refuses a question again in code. | `apps/backend/tests/test_agent.py` |
| One switch stops all payments | `pause()` in the contract and in the app | Settings, in the app |

A leaked server key cannot withdraw, change the policy or pay another contract. NEAR
rejects a `pause` signed with it as `INVALID_TRANSACTION` before the contract runs.

To read a vault's live state without an account:

```sh
curl -s https://rpc.testnet.near.org -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"query","params":{"request_type":"call_function","finality":"final","account_id":"u-e2e541dbcb1.stark-usdc-fcb734.testnet","method_name":"get_state","args_base64":"e30="}}' \
  | python3 -c 'import json,sys; print(bytes(json.load(sys.stdin)["result"]["result"]).decode())'
```

## Try it in two minutes

1. Open the sample account at [dash.hellostark.xyz/demo](https://dash.hellostark.xyz/demo).
   It needs no sign-up and is read-only. It shows the balance, the monthly cap and what
   is left of it.
2. Sign up at [dash.hellostark.xyz](https://dash.hellostark.xyz) with email or Google,
   and open Talk. Ask "how much can you still spend this month?" Stark answers from
   your account and pays nothing.
3. Say "pay 15000 for electricity". The payment goes to Approvals instead of being
   paid, because it is over a limit.
4. Ask "if I pay DStv and top up 5000, how much is left?" Stark does the arithmetic and
   pays nothing.
5. In the app, open Connect to link [@hellostarkai_bot](https://t.me/hellostarkai_bot),
   then send it a text or a voice note. The bot uses the same agent and the same limits.

To see a payment end to end, run Stark locally (below) and say "top up my meter with
5000" on Talk. The agent checks your limits and signs `pay()`, and the receipt links to
the transaction on NEAR.

## What works today

Last checked 2026-11-12.

| Part | State |
|---|---|
| Vault contract | Live on testnet and holding USDC. Each user's vault sits under `stark-usdc-fcb734.testnet`. On chain, a deposit landed, a repeated deposit was sent back, a ₦5,000 `pay` moved 3.205130 USDC to the treasury, and payments over the cap or to an unlisted meter were refused. |
| Mainnet | Production runs on NEAR mainnet from 2026-11-12, with `funder.moonboys-stark.near` as the funder and treasury. No user vault exists on mainnet yet. |
| Agent model | NEAR AI, in a Private TEE throughout. Whisper Large v3 transcribes voice, and `deepseek-ai/DeepSeek-V4.1-Flash-1017` answers. A question takes 2 to 3 seconds. A payment takes 5 to 15 seconds, because it makes several tool calls. |
| Web app, API and website | Deployed at [dash.hellostark.xyz](https://dash.hellostark.xyz), [geddon.hellostark.xyz/docs](https://geddon.hellostark.xyz/docs) and [hellostark.xyz](https://hellostark.xyz). |
| Sign-in and storage | Live. Neon Auth signs people in, and each account has its own wallet and receipts in Neon Postgres. |
| Telegram | Live as `@hellostarkai_bot`, for text and voice notes. |
| Bill payment in naira | Built. Flutterwave pays the biller. It only accepts calls from whitelisted IPs, and the production server's IP is not whitelisted yet, so production has not vended a token. |
| Crypto deposits | Built. NEAR Intents (1Click) quotes are live. No deposit has completed yet. |

When a bill is paid, its USDC moves on chain from the user's vault to Stark's treasury,
and the treasury pays the biller in naira through Flutterwave. Billers in Nigeria only
take naira, so that last step happens off chain.

## Run it locally

You need Node 22 or later, Bun 1.3 or later and Python 3.9 or later. You need Rust only
to change the contract.

```sh
bun install
cd apps/backend && bun run setup && cd ../..   # Python venv for the API
bun dev                                       # website :5173, dashboard :5174, API :8000
```

The API needs `DATABASE_URL`, the pooler URL of a Neon Postgres branch (the schema
creates itself), and `NEON_AUTH_BASE_URL`, the same branch's Auth URL. See
[`apps/backend/.env.example`](apps/backend/.env.example). The team keeps both in
Infisical: run `infisical login` once, and the `dev` scripts load them. With nothing
else set, payments are dry runs, nothing reaches a chain, and a fixed script stands in
for the model.

To check your setup:

```sh
bun check    # typecheck, lint and backend unit tests
bun smoke    # end-to-end checks against a running API
```

The contract tests run with `cargo test` in `apps/contracts/vault`. See
[`apps/contracts`](apps/contracts/README.md).

If something breaks:

- `Address already in use` means an old process holds the port. Find it with
  `lsof -nP -iTCP:8000 -sTCP:LISTEN` and stop it.
- If every request returns 401, you are not signed in, or `NEON_AUTH_BASE_URL` belongs
  to a different Neon branch than `DATABASE_URL`.
- If the dashboard shows no data, the API is not running on `127.0.0.1:8000`.

## Repository

| Path | Contents | Stack |
|---|---|---|
| [`apps/contracts`](apps/contracts) | The vault: USDC, caps, allowlist, pause and payment records | Rust, near-sdk |
| [`apps/backend`](apps/backend) | API, agent, bill payment, Telegram bot and voice | Python, FastAPI (Swagger at `/docs`) |
| [`apps/dashboard`](apps/dashboard) | The app people use to manage their bills | TanStack Start and Query |
| [`apps/website`](apps/website) | Marketing site | React Router, pre-rendered |
| [`packages/ui`](packages/ui) | Design system | shadcn/ui on Base UI, Tailwind v4 |
| [`packages/api`](packages/api) | Typed client for `/v1` | TanStack Query |
| [`docs`](docs) | [`API.md`](docs/API.md) (the API contract), [`FRONTEND.md`](docs/FRONTEND.md) and [`HANDOFF.md`](docs/HANDOFF.md) (engineering log) | |

Good places to start reading the code:

- The rules: `apps/contracts/vault/src/policy.rs`, then `pay()` in `lib.rs`.
- The agent: `Agent.respond` in `apps/backend/app/modules/agent/agent.py`.
- Signing: `apps/backend/app/modules/chain/near_tx.py` and `vault_chain.py`.

## Ground rules

- Money in the app is whole naira, stored as integers. There are no floats.
- What users see has no crypto terms. Chain details belong in docs like this one.
- `docs/API.md` is frozen. Changes may only add to it.
- Never commit secrets.

## Built at NEAR HACKATHON

All of this repository was written during the hackathon. The first commit is on
2026-10-20, the day after the announcement (Q-001), and no code comes from an earlier
project.

Libraries and services (Q-005): near-sdk (Rust) for the contract. FastAPI and pydantic
for the API. React, TanStack Start, Router and Query, Tailwind v4 and shadcn/ui on Base
UI for the web. NEAR AI Cloud for the model and Whisper. NEAR Intents (1Click) for
crypto deposits. Neon for Postgres and sign-in. Flutterwave for naira bill payments.
ElevenLabs for speech. The Telegram Bot API. The repository layout
follows [midday](https://github.com/midday-ai/midday). AI coding assistants were used.

## License

MIT. See [`LICENSE`](LICENSE). To contribute, see [`CONTRIBUTING.md`](CONTRIBUTING.md).
