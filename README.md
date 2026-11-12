# Stark

An AI agent that pays your everyday bills, by voice or chat, inside spending limits
that live in a NEAR smart contract. It pays Nigerian prepaid electricity, airtime, data
and TV.

Built for **NEAR HACKATHON** (2026-11-01 → 11-14). Tracks: **`realworld`** (lead),
**`security`**, **`agents`**.

## Why it is safe to let an agent spend

The agent never holds a key that can move money freely. Each user's USDC sits in their
own vault contract, every payment goes through it, and the contract, not the prompt,
decides.

| Rule | Where it is enforced | Check it yourself |
|---|---|---|
| The money is USDC in the user's own vault | NEP-141 deposits into the vault; `pay()` sends the bill's USDC to the treasury, or reverses the payment | `get_state` on [`u-e2e541dbcb1.stark-usdc-fcb734.testnet`](https://testnet.nearblocks.io/address/u-e2e541dbcb1.stark-usdc-fcb734.testnet), and [a settled payment](https://testnet.nearblocks.io/txns/Ho5iZ7HaB7S235FDuqw7Ar5XfCERBKq7XEdxBXeHhcR8) |
| Monthly cap and per-payment cap, in naira | `pay()` in the vault contract | `get_policy` on the same vault |
| Only allowlisted meters can be paid | `pay()` in the vault contract | same call, `allowed_meters` |
| The server's key can call `pay` and nothing else | a NEAR function-call access key on each vault, methods `["pay"]` | `view_access_key_list` on the vault |
| The naira rate can't be moved by that key | `set_rate()` is funder-only | `apps/contracts/vault/src/tests.rs` |
| A vault's code can't be changed after it's deployed, by anyone, Stark included | each vault is created with its code deployed into it and only the agent's pay-only key, no full-access key; the contract has no upgrade method | `view_access_key_list` on the vault: one `FunctionCall` key, `["pay"]` |
| A payment over a limit waits for the owner's approval | backend approval queue, then `pay_approved()` | dashboard → Approvals |
| A question is never a payment | the agent offers no tools on a question, and `pay_bill` refuses one again in code | `apps/backend/tests/test_agent.py` |
| One switch stops everything | `pause()` in the contract and in the app | dashboard → Settings |

A leaked server key cannot withdraw, change the policy or pay another contract. NEAR
rejects a `pause` signed with it with `INVALID_TRANSACTION` before the contract runs.

Read a vault's live state (no account needed):

```sh
curl -s https://rpc.testnet.near.org -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"query","params":{"request_type":"call_function","finality":"final","account_id":"u-e2e541dbcb1.stark-usdc-fcb734.testnet","method_name":"get_state","args_base64":"e30="}}' \
  | python3 -c 'import json,sys; print(bytes(json.load(sys.stdin)["result"]["result"]).decode())'
```

## Try it in two minutes

1. **Look at the sample account** at [dash.hellostark.xyz/demo](https://dash.hellostark.xyz/demo).
   No sign-up, read-only. It shows the balance, the monthly cap and what is left of it.
2. **Sign up** at [dash.hellostark.xyz](https://dash.hellostark.xyz) (email or Google)
   and open **Talk**. Ask "how much can you still spend this month?" The answer comes
   from your account, and nothing is paid.
3. **Ask for more than a limit allows**: "pay 15000 for electricity". See it land in
   **Approvals** instead of being paid.
4. **Ask a hypothetical**: "if I pay DStv and top up 5000, how much is left?" See the
   arithmetic, and nothing paid.
5. **On Telegram**, open **Connect** in the app to link
   [@hellostarkai_bot](https://t.me/hellostarkai_bot), then send a text or a voice note.
   Same agent, same limits.

**To see a payment end to end** before the payment provider is live, run it locally
(below) and say "top up my meter with 5000" on Talk. The agent checks the policy and
signs `pay()`, and the receipt from `GET /v1/activity` carries the `tx_hash`. With
`STARK_BROADCAST=1` and the agent key set, the signed call goes to testnet.

## What is real today, and what is not

Last checked 2026-11-12.

| Piece | State |
|---|---|
| Vault contract | **Live on NEAR testnet, holding USDC.** One vault per user under `stark-usdc-fcb734.testnet`. Checked on chain: a deposit, a repeated deposit sent back, a ₦5,000 `pay` that moved 3.205130 USDC to the treasury, and over-cap and unlisted-meter payments refused |
| Agent signing `pay()` | **Proven on testnet**, with the pay-only key on each vault |
| Agent model | NEAR AI, **Private TEE end to end**: voice in is Whisper Large v3, chat is `deepseek-ai/DeepSeek-V4.1-Flash-1017`. A question takes about 2–3s to answer. A payment takes 5–15s because it makes several tool calls. `NEAR_AI_MODEL=google/gemini-2.5-flash-lite` is about 3× faster but runs outside a TEE |
| Web app, API, website | **Deployed**: [dash.hellostark.xyz](https://dash.hellostark.xyz), [geddon.hellostark.xyz/docs](https://geddon.hellostark.xyz/docs), [hellostark.xyz](https://hellostark.xyz) |
| Sign-in and storage | **Live**: Neon Auth, every account has its own wallet and receipts in Neon Postgres |
| Telegram | **Live**: `@hellostarkai_bot`, text and voice notes, same agent and limits as the app |
| Bill vending (naira side) | **Built, not yet live.** Flutterwave pays the bills. Its test mode refuses bill and transfer calls until the server's IP is whitelisted, so a real token has not been vended yet. The flow runs end to end in dry-run |
| Funding with crypto | **Built, not yet live**: NEAR Intents (1Click) quotes are read live; no deposit has completed |
| Mainnet | Nothing is on mainnet |

The user's money is USDC in their vault. When a bill is paid, its USDC moves on chain
to Stark's treasury, which pays the biller in naira through Flutterwave. The naira leg
is off chain: billers in Nigeria take naira.

## Run it locally

You need **Node 22+**, **Bun 1.3+** and **Python 3.9+**. Rust only if you change the
contract.

```sh
bun install
cd apps/backend && bun run setup && cd ../..   # Python venv for the API
bun dev                                       # website :5173, dashboard :5174, API :8000
```

The API needs `DATABASE_URL` (a Neon Postgres pooler URL; the schema creates itself)
and `NEON_AUTH_BASE_URL` (the same branch's Auth URL). See
[`apps/backend/.env.example`](apps/backend/.env.example). The team keeps them in
Infisical (`infisical login` once; the `dev` scripts pull them in). With nothing else
set, payments are dry-run, nothing touches a chain and a deterministic model replaces
the LLM.

Check it:

```sh
bun check    # typecheck + lint + backend unit tests
bun smoke    # end-to-end checks against a running API
```

Contract tests: `cd apps/contracts/vault && cargo test` (see
[`apps/contracts`](apps/contracts/README.md)).

**If something breaks:**

- `Address already in use`: find the old process with `lsof -nP -iTCP:8000 -sTCP:LISTEN`
  and stop it.
- Every request is 401: you are not signed in, or `NEON_AUTH_BASE_URL` is from a
  different Neon branch than `DATABASE_URL`.
- The dashboard shows no data: the API is not on `127.0.0.1:8000`.

## What's in the repo

| Path | What it is | Stack |
|---|---|---|
| [`apps/contracts`](apps/contracts) | the vault: caps, allowlist, pause, payment records | Rust, near-sdk |
| [`apps/backend`](apps/backend) | API, agent, vending, Telegram bot, voice | Python, FastAPI (Swagger at `/docs`) |
| [`apps/dashboard`](apps/dashboard) | the app people manage bills in | TanStack Start + Query |
| [`apps/website`](apps/website) | marketing site | React Router, pre-rendered |
| [`packages/ui`](packages/ui) | design system | shadcn/ui on Base UI, Tailwind v4 |
| [`packages/api`](packages/api) | typed `/v1` client | TanStack Query |
| [`docs`](docs) | [`API.md`](docs/API.md) (the contract), [`FRONTEND.md`](docs/FRONTEND.md), [`HANDOFF.md`](docs/HANDOFF.md) (engineering log) | |

Where to start reading the code:

- The rules: `apps/contracts/vault/src/policy.rs`, then `pay()` in `lib.rs`.
- The agent: `apps/backend/app/modules/agent/agent.py`, `Agent.respond`.
- Signing: `apps/backend/app/modules/chain/near_tx.py` and `vault_chain.py`.

## Ground rules

- Money is integer naira everywhere. No floats.
- No crypto jargon in what users see. The chain details are for judges and developers, here.
- `docs/API.md` is frozen: additive changes only.
- Never commit secrets.

## Built at NEAR HACKATHON

All of this repository was written inside the hackathon window. The first commit is
2026-10-20, the day after the announcement (Q-001). There is no baseline code from an
earlier project.

Libraries and services used (Q-005): near-sdk (Rust) for the contract; FastAPI and
pydantic for the API; React, TanStack Start/Router/Query, Tailwind v4, shadcn/ui on
Base UI for the web; NEAR AI Cloud for the model and Whisper; NEAR Intents (1Click)
for crypto funding quotes; Neon (Postgres and Auth); Flutterwave for naira bill
payments; ElevenLabs and Kokoro-82M for speech; Telegram Bot API. The repo layout
follows [midday](https://github.com/midday-ai/midday). AI coding assistants were used.

## License

MIT. See [`LICENSE`](LICENSE). Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md).
