# Stark

An AI agent that pays your everyday bills, by voice or chat, inside spending limits
that live in a NEAR smart contract. It starts with Nigerian prepaid electricity, where
the meter runs out at the worst time, and also covers airtime, data and TV.

Built for **NEAR HACKATHON** (2026-11-01 → 11-14). Tracks: **`realworld`** (lead),
**`security`**, **`agents`**.

## Why it is safe to let an agent spend

The agent never holds a key that can move money freely. Every payment goes through the
vault contract, and the contract, not the prompt, decides.

| Rule | Where it is enforced | Check it yourself |
|---|---|---|
| Monthly cap and per-payment cap | `pay()` in the vault contract | `get_policy` on [`stark-vault.testnet`](https://testnet.nearblocks.io/address/stark-vault.testnet) |
| Only allowlisted meters can be paid | `pay()` in the vault contract | same call, `allowed_meters` |
| The server's key can call `pay` and nothing else | a NEAR function-call access key on `stark-agent.testnet`, receiver `stark-vault.testnet`, methods `["pay"]` | `view_access_key_list` on `stark-agent.testnet` |
| Over a limit → ask the human, don't fail silently | backend approval queue, then `pay_approved()` | dashboard → Approvals |
| A question is never a payment | the agent offers no tools on a question, and `pay_bill` refuses one again in code | `apps/backend/tests/test_agent.py` |
| One switch stops everything | `pause()` in the contract and in the app | dashboard → Settings |

A leaked server key cannot withdraw, change the policy or pay another contract: a
`pause` signed with it is refused by NEAR with `INVALID_TRANSACTION` before the
contract runs.

Read the live policy (no account needed):

```sh
curl -s https://rpc.testnet.near.org -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"query","params":{"request_type":"call_function","finality":"final","account_id":"stark-vault.testnet","method_name":"get_policy","args_base64":"e30="}}' \
  | python3 -c 'import json,sys; print(bytes(json.load(sys.stdin)["result"]["result"]).decode())'
```

## Try it in two minutes

1. **Look at the sample account** at [dash.hellostark.xyz/demo](https://dash.hellostark.xyz/demo).
   No sign-up, read-only. See the balance, the monthly cap and what is left of it.
2. **Sign up** at [dash.hellostark.xyz](https://dash.hellostark.xyz) (email or Google)
   and open **Talk**. Ask "how much can you still spend this month?" See an answer read
   from your account, with nothing paid.
3. **Ask for more than a limit allows**: "pay 15000 for electricity". See it land in
   **Approvals** instead of being paid.
4. **Ask a hypothetical**: "if I pay DStv and top up 5000, how much is left?" See the
   arithmetic, and nothing paid.
5. **On Telegram**, open **Connect** in the app to link
   [@hellostarkai_bot](https://t.me/hellostarkai_bot), then send a text or a voice note.
   Same agent, same limits.

**To see a payment end to end** before the payment provider is live, run it locally
(below) and say "top up my meter with 5000" on Talk: the agent checks the policy,
`pay()` is signed (and broadcast to testnet with `STARK_BROADCAST=1` and the agent key
set), and the receipt from `GET /v1/activity` carries the `tx_hash`.

## What is real today, and what is not

Measured, not assumed. Last checked 2026-11-12.

| Piece | State |
|---|---|
| Vault contract | **Live on NEAR testnet** at `stark-vault.testnet`. 9 payments recorded on chain under a ₦30,000 monthly / ₦10,000 per-payment cap |
| Agent signing `pay()` | **Proven on testnet.** The backend signs with the pay-only key above; the 9 recorded payments came through it |
| Agent model | NEAR AI. Voice in: **Whisper Large v3, Private TEE**. Chat: `google/gemini-2.5-flash-lite`, picked for speed (about 1.4s a turn) — it runs in NEAR AI's *Incognito* tier, **not** in a TEE. One env var (`NEAR_AI_MODEL`) moves chat to a Private TEE model at about 2.7s a turn |
| Web app, API, website | **Deployed**: [dash.hellostark.xyz](https://dash.hellostark.xyz), [geddon.hellostark.xyz/docs](https://geddon.hellostark.xyz/docs), [hellostark.xyz](https://hellostark.xyz) |
| Sign-in and storage | **Live**: Neon Auth, every account has its own wallet and receipts in Neon Postgres |
| Telegram | **Live**: `@hellostarkai_bot`, text and voice notes, same agent and limits as the app |
| Bill vending (naira side) | **Built, not yet live.** Flutterwave pays the bills. Its test mode refuses bill and transfer calls until the server's IP is whitelisted, so a real token has not been vended yet. The flow runs end to end in dry-run |
| Funding with crypto | **Built, not yet live**: NEAR Intents (1Click) quotes are read live; no deposit has completed |
| Mainnet | Nothing is on mainnet |

The vault keeps the **ledger and the rules**: balance, caps, allowlist, payment
records. It does not custody tokens yet; the naira that pays a bill sits with the
payment provider. Moving the stablecoin itself through the vault is the next step.

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
set, payments are dry-run, nothing touches a chain and a deterministic model stands in
for the LLM.

Check it:

```sh
bun check    # typecheck + lint + backend unit tests
bun smoke    # end-to-end checks against a running API
```

Contract tests: `cd apps/contracts/vault && cargo test` (see
[`apps/contracts`](apps/contracts/README.md)).

**If something breaks:** `Address already in use` → `lsof -nP -iTCP:8000 -sTCP:LISTEN`
and stop the old process. Every request is 401 → you are not signed in, or
`NEON_AUTH_BASE_URL` is from a different Neon branch than `DATABASE_URL`. Dashboard
shows no data → the API is not on `127.0.0.1:8000`.

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
- No crypto jargon in what users see. Judges and developers get the chain here instead.
- `docs/API.md` is frozen: additive changes only.
- Never commit secrets.

## Built at NEAR HACKATHON

All of this repository was written inside the hackathon window: the first commit is
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
