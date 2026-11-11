# Stark

An AI agent that pays your everyday bills from a crypto balance, within limits you
set, by voice or chat. Starts with Nigerian prepaid electricity; covers airtime,
data, TV, internet and water. Built for **NEAR HACKATHON** (2026-11-01 → 11-14).

- Tracks: `realworld` (lead), `security`, `agents`
- Design source (the exported artboards) lives outside the repo; ask a maintainer for access

## Quick start

You need **Node 22+** (24 recommended, see `.nvmrc`), **Bun 1.3+** and **Python 3.9+**.
Nothing else: the backend has no Python dependencies, and Rust is only needed if you
change the contract.

```sh
bun install
bun dev                       # website, dashboard and backend together
```

| App | URL |
|---|---|
| Marketing site | http://localhost:5173 |
| Dashboard | http://localhost:5174 |
| API | http://127.0.0.1:8000 |

The backend needs one thing before it starts: `DATABASE_URL`, the pooler URL of a Neon
Postgres branch (the schema creates itself on first boot). Sign-in needs
`NEON_AUTH_BASE_URL`, the same branch's Auth URL — without it every `/v1` call answers
401. Both are documented in [`apps/backend/.env.example`](apps/backend/.env.example)
and stored in Infisical (`dev`, folder `/backend`): install the CLI
(`brew install infisical/get-cli/infisical`) and run `infisical login` once, and the
`dev` scripts pull them in. Everything else runs offline:
payments are dry-run, nothing touches a chain, and a deterministic model stands in for
the LLM.

Check that it all works:

```sh
bun check                     # typecheck + lint + backend unit tests
bun smoke                     # 68 end-to-end checks (70 with the TTS sidecar up); needs the backend running
```

### Troubleshooting

- **`Address already in use`.** Something else holds a port (often an old backend).
  `lsof -nP -iTCP:8000 -sTCP:LISTEN` shows what; stop it and rerun. Under `bun dev`
  one app failing stops the others, so check the first error in the output.
- **Dashboard shows no data.** The backend is not running, or is on a different port;
  the dashboard only proxies `/v1` to `127.0.0.1:8000`.
- **Every request says 401.** You are not signed in (the dashboard routes you to
  `/login`), or `NEON_AUTH_BASE_URL` is missing/wrong in Infisical (`dev`, `/backend`) — it must
  be the Auth URL of the same Neon branch as `DATABASE_URL`.
- **`DATABASE_URL is not set`.** The backend will not start without a Neon Postgres
  URL; set it in Infisical (`dev`, `/backend`) to the pooler URL.
- **`infisical: command not found` / not logged in.** `brew install
  infisical/get-cli/infisical`, then `infisical login` (pick Infisical Cloud, US).
- **`bun: command not found`.** Install it with `curl -fsSL https://bun.sh/install | bash`.
- **Demo numbers drifted.** `curl -X POST http://127.0.0.1:8000/v1/_stub/reset`.

## What's in the repo

A Bun + Turborepo monorepo, laid out like [midday](https://github.com/midday-ai/midday). Each app
has its own README; start there when you work on it.

| Path | What it is | Stack |
|---|---|---|
| [`apps/website`](apps/website) | marketing site for hellostark.xyz | React Router, pre-rendered static HTML |
| [`apps/dashboard`](apps/dashboard) | the Stark app users manage bills in | TanStack Start (SPA) + TanStack Query |
| [`apps/backend`](apps/backend) | API, agent, bill vending, Telegram bot | Python, FastAPI (Swagger at `/docs`) |
| [`apps/contracts`](apps/contracts) | NEAR vault contract: caps and allowlist | Rust, near-sdk |
| [`packages/ui`](packages/ui) | the design system: shadcn/ui components on Base UI, themed to Stark | shadcn, Base UI, Tailwind v4, Reicon |
| [`packages/api`](packages/api) | typed `/v1` client, query options and mutations | TanStack Query |
| [`packages/utils`](packages/utils) | naira and date formatting, request ids | |
| [`docs`](docs) | the API contract, frontend guide, backend handoff | |

Which doc to read first:

- **Building the web app or dashboard?** [`docs/FRONTEND.md`](docs/FRONTEND.md): every
  screen, the route behind it, and the rules that matter.
- **Working on the backend?** [`docs/HANDOFF.md`](docs/HANDOFF.md): environment traps,
  what is verified versus guessed, and what to do next.
- **Calling the API?** [`docs/API.md`](docs/API.md) is the contract. It is frozen.

## Scripts

Run from the repo root.

| Command | What it does |
|---|---|
| `bun dev` | all three apps in parallel |
| `bun dev:website` / `bun dev:dashboard` / `bun dev:backend` | one app on its own |
| `bun run build` | build the website and dashboard |
| `bun typecheck` | TypeScript across the workspace |
| `bun lint` / `bun format` | Biome |
| `bun run test` | backend unit tests (207, hermetic) |
| `bun check` | typecheck + lint + test, what CI should run |
| `bun smoke` | end-to-end checks against a running backend |
| `bun tts` | the local Kokoro voice sidecar on :8010 (needs `.venv-tts`, see [`apps/backend`](apps/backend/README.md#voice-output-tts)) |

Contract commands are in [`apps/contracts`](apps/contracts/README.md); they need a Rust
toolchain, so they are not part of `bun run test`.

## Current state

**Nothing is live yet.** The bill API, the vault contract and the agent all exist and
are tested, but every payment is dry-run: no real token has been vended, no transaction
broadcast and no contract deployed. The NEAR AI model and Whisper were called live on
2026-10-22 — a real tool call and real transcripts came back.

| Piece | Status |
|---|---|
| API contract | **frozen** — see [`docs/API.md`](docs/API.md) |
| Stub server | working, 68/68 smoke checks (70 with the sidecar up), 367 unit tests |
| App routes | **built** — plans, bill add/edit/delete, limits and wallet, additive to `/v1` |
| Flutterwave | **one provider for deposits, bills and withdrawals** (2026-11-03). Test key works for the catalogue, checkout, banks and account lookup; bills and transfers wait on IP whitelisting, so **no bill or transfer has run yet** |
| Vending (M3) | **wired** — electricity, airtime, data and TV through Flutterwave bills, 45 tests |
| Storage | **Neon Postgres** — accounts, wallets, receipts, channel identities; created on first boot, survives restart. Bills, limits and `units_left` stay in memory |
| Auth | **live** — sign-up/sign-in against Neon Auth, the backend verifies sessions from its JWKS and gives every account its own wallet and receipts; `/v1` answers **401** without a bearer token |
| Receipts | **persisted** in Neon Postgres: token ↔ tx hash ↔ request_id, per account, survives restart |
| Vault contract | **deployed to testnet** — `stark-vault.testnet` (2026-10-26); cap, allowlist and pause rules exercised live. 38/38 tests, wasm target checks clean, clippy clean. Ledger-only: it does not move tokens yet |
| Agent + LLM | **built (M2)** — tool routing, policy gate, `pay()` signing. 59 tests. Real NEAR AI turn verified 2026-10-22. **Broadcasts when `STARK_BROADCAST=1`** (2026-10-26) against `stark-vault.testnet`: the key is a scoped function-call key on `stark-agent.testnet` that may only call `pay`, so a leak cannot withdraw, change the policy or touch another contract — a `pause` signed with it comes back `INVALID_TRANSACTION`, refused by the access key before the contract runs. **Fast model for the demo (2026-10-24):** `google/gemini-2.5-flash-lite`, 1.35s a turn vs 7.1s for `Qwen/Qwen3.8-27B`, with the account snapshot in the prompt — one env var back if the TEE claim matters |
| Telegram bot (M4) | **built, fail-closed** — webhook auth, identity linking, dedupe, voice wake gate, renewal pushes. 22 tests. Needs `TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET` to go live; no real update has ever arrived |
| Reminders | **built 2026-10-24** — a bill carries `renews_on`, appears in `state.due_soon` inside a 7-day window, and the same line is pushed to a linked chat. No push has ever been sent (no bot token) |
| Voice (Whisper) | **live-verified 2026-10-22, real audio in 2026-10-24** — `/v1/voice` now takes the clip itself (base64 or multipart) from both the browser and Telegram; a transcript is never invented (`stt: ok\|failed\|no_key`) |
| TTS | **built 2026-10-24, two providers, streamed** — ElevenLabs Flash (`ELEVENLABS_API_KEY`) answers a reply in well under a second, Kokoro-82M sidecar (`bun tts`) is the local fallback, text is always the floor. Talk shows text first (`speak: false`), then plays `GET /v1/speak/stream`, which speaks on the first bytes (falls back to `POST /v1/speak`); Telegram voice notes reply in voice. Kokoro has no Nigerian voice and a free ElevenLabs key gets premade voices only (library voices are HTTP 402) — cloning is the accent path |
| Suggestions | **computed 2026-10-24**, not seeded — meter runway, cap usage, load imbalance, due bills; a line with no data behind it is not returned, so the old "AC is 78%" fake is gone |
| AC telemetry | `/v1/telemetry` stores readings and `load_imbalance` reads them; **no real meter exists** (M6) |

## Ground rules

- **The contract is frozen.** Additive changes only. Renames or type changes mean
  `/v2`, and they break the frontend for no reason.
- **Money is integer naira** everywhere. No floats.
- **No crypto jargon in user-facing copy.** No "vault", no "USDC", no addresses.
- **No sliders**, anywhere in the app.
- **Never commit secrets.** Keys go in env vars.

## Build order

| # | Milestone | Cutting order if behind |
|---|---|---|
| M0 | Contract frozen, VTpass sandbox confirmed | — |
| M1 | Vault contract + caps | **built (not deployed)** |
| M2 | Agent server, signed `pay()` | never cut |
| M3 | Real token vending, receipts | never cut |
| M4 | Telegram + Whisper voice | 4th |
| M5 | NEAR Intents funding | 3rd |
| M6 | AC telemetry + suggestions | 1st |
| M7 | Frontend wired, demo recorded | — |

## Deploy

All three apps deploy to [Brimble](https://brimble.io) from `main`: the marketing site to
[hellostark.xyz](https://hellostark.xyz), the API to `geddon.hellostark.xyz` and the
dashboard to `dash.hellostark.xyz` (see [`apps/website`](apps/website/README.md#deploy)).
The vault contract is on NEAR testnet at `stark-vault.testnet`; nothing is on mainnet.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).
