# @stark/backend

The Stark API: bills, payments, wallet, limits, voice and the Telegram bot. A
FastAPI app, laid out after [awesome-nest-boilerplate](https://github.com/NarHakobyan/awesome-nest-boilerplate):
one module per feature, each with its controller, service and DTOs. Python 3.9 or
newer (the Docker image runs 3.12).

The HTTP contract the frontend relies on is [`docs/API.md`](../../docs/API.md). It is
**frozen**: additive changes only. **Swagger UI is at
[`/docs`](http://127.0.0.1:8000/docs)** (ReDoc at `/redoc`, the spec at
`/docs/openapi.json`), generated from the same DTOs the routes use. They are served
only with `STARK_DOCS=1`: set it in Infisical `dev`, never in `prod`, where the spec
would map every route for anyone. For the full
backend state, environment traps and what to do next, read
[`docs/HANDOFF.md`](../../docs/HANDOFF.md).

## Quick start

```sh
cd apps/backend && bun run setup   # once: .venv with FastAPI, uvicorn, httpx
infisical login                    # once: secrets come from Infisical (dev, /backend)
bun dev:backend                    # from the repo root → http://127.0.0.1:8000, docs at /docs
bun smoke                          # in another shell: 69 checks
```

`DATABASE_URL` (Neon Postgres, pooler URL with `sslmode=require`) is the one hard
requirement: accounts, wallets, receipts, bills, limits, readings and linked identities
live there and the schema creates itself on first boot. `NEON_AUTH_BASE_URL` (the same
branch's Auth URL) makes sign-in work. Without it every `/v1` request answers 401.
Everything else is off: without `FLW_SECRET_KEY` nothing can be bought, deposited or
withdrawn (test money still works), nothing is signed or broadcast, and a
deterministic model stands in for the LLM. Each remaining
variable in [`.env.example`](.env.example) switches one piece on.

| Command (from `apps/backend`) | What it does |
|---|---|
| `.venv/bin/python -m app` | API on `HOST:PORT` (127.0.0.1:8000; no secrets unless you wrap it in `infisical secrets-manager run`) |
| `.venv/bin/python -m tests.smoke_test` | 69 end-to-end checks (sign-up, auth, every endpoint) against a running server; `STARK_SMOKE_BASE` points it elsewhere |
| `.venv/bin/python -m unittest discover -s tests -t .` | the unit tests, no server needed (`bun run test` from the root) |
| `curl -X POST http://127.0.0.1:8000/v1/_stub/reset` | back to the demo seed (only with `STARK_STUB_RESET=1`) |

`ffmpeg` on your `PATH` (`brew install ffmpeg`) is **required for voice input**. It
decodes Telegram's OGG and the browser's WebM. Without it, voice
asks for text instead of guessing.

## Layout

```
app/
  main.py                create_app(): modules, error filter, CORS, Swagger
  __main__.py            `python -m app`: uvicorn on HOST:PORT
  app_module.py          the composition root: every repository and service, wired once
  setup_swagger.py       /docs, /redoc, /docs/openapi.json (no fake 422s)
  common/                ApiError, Clock, dto/ (ErrorDto, ContractField)
  decorators/            AuthUser (the signed-in account), Module (the AppModule), ApiResponses
  guards/auth_guard.py   bearer only → Neon Auth session → Account, else 401
  filters/               every failure → the contract's {code, message, detail}
  shared/services/       ApiConfigService: the settings the HTTP layer reads
  database/neon.py       Neon Postgres over HTTPS: connection pool, schema
  modules/
    account/             per-account bills, caps and agent, kept warm; AccountRepository
    auth/                session lookup, sign-out
    bill/  plan/         saved bills; the priced plan catalogue
    payment/             BillPaymentService (the contract's checks) → PaymentService (vend, charge on delivery)
    receipt/             ReceiptRepository: receipts + wallet; request_id is the idempotency key
    wallet/  limit/      balance and test-money top-ups; spending caps
    state/  suggestion/  GET /v1/state; the computed suggestion feed
    telemetry/           readings (server-stamped) and the meter maths
    voice/               /v1/voice, /v1/speak: stt, tts, audio, the wake rule
    agent/               model loop, prompt, tools, payment gate, intent judge; the per-account toolbox
    chain/               borsh + ed25519 + base58 + RPC: builds and signs pay()
    flutterwave/         the one naira provider: client, webhook (checkout, bills, transfers)
    vending/             bill catalogue and kind → biller/item; buys through Flutterwave
    telegram/            the bot: webhook, identity linking, the owner's agent
    reminder/            renewal windows and the push loop
    turnlog/  stub/      the conversation log; the demo seed and reset
    health_checker/      GET /, GET /health
tests/                   unit tests, support.py (TempAccount, ApiHarness), smoke_test.py
requirements*.txt        the API's dependencies; -dev adds the test client
```

Each module follows the same shape: `<name>_controller.py` (an `APIRouter`, thin),
`<name>_service.py` (the rules and their error codes), `dtos/` (one pydantic model
per file). Request DTOs validate once at the edge and fail with the contract's own
codes (`bad_amount`, `bad_limits`, …) through `ContractField`. Response DTOs document
the shapes for Swagger. Routes return a `JSONResponse` themselves, so the frozen
bytes, including fields that are *absent* rather than `null` like `renews_on`, never
pass through a serializer that could change them.

## Running it

```sh
bun dev:backend              # from the repo root, with secrets from Infisical (dev, /backend)
.venv/bin/python -m app      # or directly, from apps/backend, with no secrets
```

Both serve http://127.0.0.1:8000, with the API documented at
http://127.0.0.1:8000/docs.

In another shell, run the smoke checks:

```sh
STARK_STUB_RESET=1 bun dev:backend   # the smoke run resets to the demo seed
bun smoke                            # 69 checks, exits 1 on failure
```

New accounts open empty: no bills, ₦0, no activity. `POST /v1/_stub/reset` (with
`STARK_STUB_RESET=1`) replaces the caller's data with the artboard seed: ₦64,200
balance, ₦30,000 monthly cap, ₦23,000 spent, the "Home" meter, "Living room TV" on
DStv Compact, "My line" airtime and the six activity entries, so screens render with
the numbers already in the design. Shapes and error codes are in
[`docs/API.md`](../../docs/API.md) and at `/docs`.

## Agent

The voice endpoint is the agent. One loop, and two model calls that start together:

```
transcript ─┬─ model picks a tool ─┬─ payment gate → sign pay() → book the payment → reply
            └─ intent judge ───────┘
```

- **The policy gate is code, not a prompt.** `PaymentGate.pay` (`payment_gate.py`)
  checks the per-payment cap, the monthly cap, the meter allowlist and the balance
  before anything is signed or charged. A model that ignores every instruction still
  cannot overspend.
- **Same rules as the contract.** `policy.py` mirrors [`policy.rs`](../contracts/vault/src/policy.rs),
  and a test reads the Rust source and fails if a code or sentence drifts.
- **A key is needed.** Without `NEAR_AI_API_KEY` every turn fails before any request,
  the user hears that Stark lost connection, and nothing is paid. The tests drive the
  same loop, tools and gate with scripted models (`tests/regex_model.py`) and need no
  network.
- **A question never spends.** The first gate in `pay_bill` is a second model call
  (`payment_intent.py`): no tools, shown only Stark's last reply and the user's message,
  and it must answer one word. `PAY` lets the payment go on, `AGAIN` also lifts the
  duplicate check below, and anything else, including no answer, refuses with
  `not_a_payment_request`. A failed call refuses too. It starts with the turn, beside
  the main model call, so a payment does not wait for two rounds in a row. It replaced a
  set of regexes after a failure on 2026-10-24: with `pay_bill` on offer, "if I pay
  DStv and top up 5 thousand, how much is left?" **paid the airtime**, and "I'm
  confused, DStv says I owe, what should I do?" tried to pay DStv. "Can you pay my DStv"
  still pays, because it grants permission, and a bare "yes" pays only when Stark has
  just offered to. Checked live on 2026-11-13: 42 of 42 phrasings, including pidgin the
  prompt was not written against.
- **An unpriced charge asks instead of guessing.** Two more refusals sit in the gate,
  both written after a live session on 2026-10-24 where "recharge my airtime number"
  bought ₦1,000 **twice, 29 seconds apart**, with the model choosing the figure both
  times. With no amount spoken and no plan price, it refuses with `amount_required`
  ("How much would you like to pay? Nothing has been charged yet."), and a figure the
  user did not say — "pay 500" sent as ₦5,000 — refuses with `amount_mismatch`
  (2026-11-12; every figure in the transcript counts, so "home 5000 and office 3000"
  still pays both; `spoken_amounts.py` reads the figures by splitting words, not by
  pattern). The same bill for the same figure, delivered or pending within five minutes,
  refuses with `duplicate_payment` unless the intent judge answered `AGAIN`, so a
  refused repeat can still be confirmed. A plan-priced bill needs no figure because the plan
  sets it, and seeded demo receipts (`seed-*`) do not count as recent payments.
- **It says what it cannot do.** The prompt forbids implying a message was sent. There
  is no forwarding to Telegram, email or anywhere else, and the model says so instead
  of inventing a receipt-sending feature.

```sh
.venv/bin/python -m unittest tests.test_agent     # policy parity, RFC 8032, the cap gate
.venv/bin/python -m unittest tests.test_vending   # store, idempotent retry, plans
.venv/bin/python -m unittest tests.test_live_paths # Flutterwave's wire format, over loopback
.venv/bin/python -m unittest tests.test_tg        # the Telegram door and its gates
.venv/bin/python -m unittest tests.test_tts       # the voice path, against a fake ElevenLabs
```

## Telegram bot

The bot runs the same agent behind the same policy gate. It **refuses everything**
until both secrets are set, because an unauthenticated webhook would let anyone on the
internet talk to a wallet:

```sh
# Infisical, folder /backend
TELEGRAM_BOT_TOKEN=123456:ABC-your-token     # from @BotFather
TELEGRAM_WEBHOOK_SECRET=...                  # openssl rand -hex 32
```

Then set the webhook so Telegram pushes updates to it, with the same secret:

```sh
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://<your-host>/v1/tg/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

In Telegram: send `link 482913` with the code shown in the app, then ask by text or
voice note. Voice notes need the word "stark" first, the same rule `/v1/voice`
uses. Without `NEAR_AI_API_KEY` the bot says it cannot hear voice notes rather than
guessing what you said.

Each account gets its **own vault** on NEAR, a sub-account of Stark's funder
(`u-<id>.stark-vault.testnet`), created on its first money movement. To turn the
chain on:

```sh
STARK_FUNDER_ACCOUNT=stark-vault.testnet   # parent of every vault; creates, funds, refunds
STARK_FUNDER_KEY=ed25519:<base58 secret>   # its full-access key
STARK_AGENT_KEY=ed25519:<base58 secret>    # added to each vault, may only call `pay`
STARK_NETWORK=testnet                      # or mainnet
STARK_BROADCAST=0                          # 1 to actually send
# once per contract change, publish the code every vault points at:
.venv/bin/python -m app.modules.chain.vault_chain publish \
  ../contracts/vault/target/wasm32-unknown-unknown/release/stark_vault.wasm
```

With no funder configured, payments book off-chain. With
one, every payment path signs `pay` on the user's vault before buying, and a
signature that cannot be produced **refuses the payment**. Deposits, withdrawals
and refunds reach the vault through an outbox (`chain_ops`) the money loop retries.
`python -m app.modules.treasury.treasury_service` prints what Stark owes against
what it holds (the Flutterwave NGN balance and treasury USDC).

**Limits:** the borsh layout was round-tripped on 2026-11-03, when a `pay()` signed here
was accepted on chain; the global-contract actions have not been. The NEAR AI model and Whisper *have* run live (2026-10-22). `/v1/voice` takes real
audio, as base64 `audio` in JSON or a multipart file part, and `transcript_hint` is
kept only as a probe for tests (2026-10-24). See [`HANDOFF.md`](../../docs/HANDOFF.md) §6.

## What it can answer

Everything in the snapshot: balance, monthly cap and what is left, each bill's label,
provider, **reference (meter/smartcard/phone number)**, plan and price, renewal date,
and the last five payments. So "what's my most recent subscription?", "read my meter
number", "when does my DStv renew?" and "how many units are left?" are one model call
each, no tool round trip (measured 1.1–1.5s, 2026-10-24). A hypothetical ("if I pay A
and top up B, what is left?") is arithmetic on those numbers, answered without paying.

It cannot: send or forward anything (Telegram, email or elsewhere), issue a new
meter number or token, or see a bill that was never saved.

## Voice input (Whisper)

`/v1/voice` takes the clip itself. There is no stub transcription in the product path
(2026-10-24):

```sh
# the browser: a recorded Blob, base64'd. `audio_type` must be what was recorded.
curl -s -X POST http://127.0.0.1:8000/v1/voice \
  -H 'Content-Type: application/json' \
  -d "{\"audio\": \"$(base64 -i clip.webm)\", \"audio_type\": \"audio/webm\"}"

# anything that streams a file: multipart, the same field name
curl -s -X POST http://127.0.0.1:8000/v1/voice \
  -F audio=@clip.ogg \
  -F audio_type=audio/ogg
```

`transcript_hint` is only a probe for tests and `curl`. The server checks audio
**first**, so a client that can record never has to send words.

**The provider refuses WebM** (measured 2026-10-24). Whisper reads WAV and OGG/Opus.
A Chrome `MediaRecorder` WebM comes back HTTP 400 *"Audio could not be processed"*
whatever filename or content type it is given, because the container itself is
refused. So `stt.hear` decodes anything that is
not WAV/OGG to 16 kHz mono WAV with `ffmpeg` before sending (`audio.transcode`, the
same step a Telegram OGG already took), and names the result `audio.wav`. WAV and
OGG skip ffmpeg entirely. Without ffmpeg the clip is sent unchanged and the answer is
`stt: failed`, never a guessed transcript. That makes `ffmpeg` **required** for the
dashboard's voice button, not just for Telegram.

Every audio answer carries `stt`: `ok` (transcribed, then the wake gate and agent
ran), `failed` (nothing heard: `transcript: ""` and the reply asks again) or `no_key`
(no `NEAR_AI_API_KEY`: the reply says so and asks for text). **An unheard clip
never reaches the agent and never gets a made-up transcript.** Bad base64 is 400
`bad_audio`; over 8MB is 413 `audio_too_large`.

## Voice output (TTS)

Replies come back **spoken** when ElevenLabs is keyed, and as text when it is not.
Text never waits on the voice. `/v1/voice` carries an additive `audio` field (a WAV
data URL, or `null`). A Telegram voice note gets a voice note back (OGG/Opus via
`sendVoice`). The dashboard's Talk screen plays it.

**Amounts are spoken as words, not symbols.** The voice does not read `₦`. ElevenLabs
said the letter *N* ("Your balance is N sixty-four thousand…"), measured 2026-10-24 by
synthesising a real reply and transcribing the clip back. So `tts.speakable()` rewrites
`₦64,200` as `64,200 naira` before anything is synthesised, for the WAV, the stream and
the Telegram voice note. The reply the user *reads* keeps the sign. Only amounts with
`₦` change. Numbers, decimals and commas without it are left alone (`SpeakableCase` in
`test_tts.py` covers both).

**Text never waits for voice.** The dashboard sends `{"speak": false}` so the words
land in one model turn. Then it fetches the voice from `POST /v1/speak` and plays it a
beat later.

**ElevenLabs Flash v2.5.** With `ELEVENLABS_API_KEY` set, `tts.py` asks ElevenLabs for
the reply. A Stark-length answer comes back in well under a second, and it reads
`₦5,000`, "Ikeja" and dates correctly. `tts.py` wraps the raw 24 kHz PCM it returns
into a WAV, so the dashboard's `data:` URL, `ffmpeg` for Telegram and `/v1/speak` all
see a WAV.

The free tier gives **10,000 credits a month** at 0.5 to 1 credit per character on
Flash. That is about 10k to 20k characters, 13 to 26 minutes of speech, or **70 to 130
Stark replies**. It is non-commercial, and **the Voice Library is not available to free
keys over the API**: asking for Rachel (`21m00Tcm4TlvDq8ikWAM`) returns HTTP 402
`paid_plan_required`, measured 2026-10-24. So a free key is limited to the account's
**premade** voices (`ELEVENLABS_VOICE_ID`, default "Daniel, Steady Broadcaster"; `GET
/v1/voices` lists them). There is no Nigerian accent among them. A cloned or library
voice needs Starter ($6/mo, $1 for the first month), which is also where the
commercial license lives.

If ElevenLabs is down or unkeyed, the text is already on screen. The key is optional,
and the demo works without it.

**Streaming.** `POST /v1/speak` hands over a whole clip, which cannot start playing
until synthesis finishes (~1.3s). `GET /v1/speak/stream?ticket=…` (the ticket from `POST /v1/speak/ticket`, so an
`<audio>` element needs no token in its URL) sends the MP3 as
ElevenLabs produces it, and the Talk screen plays that first. Measured **first byte
0.53 to 0.82s** against **1.25 to 1.30s** buffered, so speech starts while the clip is
still being built. The stream falls back to `POST /v1/speak` in the browser, and on the
server to a whole ElevenLabs WAV. No voice at all is a 503 `no_voice`, not silence.

It fails closed like `stt.py`. With no key, ElevenLabs down, no ffmpeg, or a Telegram
refusal, the answer still arrives as text. `bun smoke` runs its checks with voice off
(`audio` null) or on.

## Conversation log (turnlog)

With the log on, every exchange appends one JSON line, so a real conversation can be
reviewed afterwards:

```sh
STARK_TURN_LOG=1 bun dev:backend     # or set it in Infisical; a path works too
tail -f apps/backend/logs/turns/turns.jsonl
```

A `kind: "turn"` line holds the whole exchange: `heard` (the transcript
verbatim), `said` (after the wake gate), `reply`, `actions` (what it actually
did), `code` (the rule that refused, when one did), `model`, and `ms` per
stage (`total`, `stt`, `agent`, `tts`). A **missing** stage key means that
stage did not run, not that it was instant. `outcome` is `answered`, `asleep`
(the wake gate kept it) or `unheard` (STT failed: no transcript, no agent,
no guess). When a clip was uploaded, `audio` points at `audio/<stamp>-in.webm`
beside the log.

A `kind: "speak"` line is the other half of the exchange: `text` as written,
`spoken` as the provider received it (after the naira rewrite), the provider,
and `ms`: time to first byte on the stream, whole-synthesis time on
`POST /v1/speak`.

Off by default, `logs/` is gitignored, and a log that cannot be written is
discarded rather than returned as a 500.

From outside the box, `GET /v1/turnlog` reads it back for the operator only: it
needs `X-Stark-Admin-Key`, never a user session, because the file holds every
account's turns. Each turn carries `account_id`; `?account=<id>` keeps one
account's.

## Flutterwave

One account does all the naira: deposits (hosted checkout), bills, and withdrawals
(transfers), from one NGN balance. v3 API, standard library client in
`app/modules/flutterwave/flutterwave.py`.

```sh
FLW_SECRET_KEY=FLWSECK_TEST-...    # a test key talks to Flutterwave's test environment
FLW_SECRET_HASH=...                # the webhook's secret hash, set in the dashboard too
STARK_APP_URL=http://localhost:5174
```

Three facts about the Flutterwave account, not the code:

- **Bills and transfers need the server's IP whitelisted** (dashboard → Settings →
  Whitelisted IP addresses), test mode included. Until then they answer `Please
  enable IP Whitelisting`, and Stark reports the bill as not paid, charging nothing.
- **Collections settle into the balance later** (batched daily, and only if
  settlement goes to the Flutterwave wallet, not a bank). A deposit is spendable at
  once, so Stark fronts it from the balance in the meantime; `float_low` refuses a
  payment the balance cannot cover.
- **There is no dry mode and no fixture data.** The bill catalogue is read live
  (`GET /bill-categories`, hourly); without a key nothing can be sold.

## Vending and receipts

A payment runs in this order, and the order is what makes it safe:

```
policy check → sign pay() → record the intent → buy → charge → speak the token
```

- **Record before buying.** The receipt exists with a `request_id` and status
  `pending` before the vendor is called. If the process dies mid-purchase, the id
  survives and the purchase is re-read instead of duplicated: the `request_id` is the
  bill's `reference` at Flutterwave, which refuses a reused one.
- **Charge only on delivery.** Flutterwave's payment call only says the order was
  taken; a status read follows, and only `successful` counts. `pending` and `failed`
  never move money. A delivered meter top-up with no token is treated as pending.
- **A retry reuses its request_id.** Paying the same bill for the same amount while a
  purchase is still pending re-reads it rather than buying again.

**What is sold**, read from Flutterwave's catalogue by biller name:

| Kind | Flutterwave billers | Priced by |
|---|---|---|
| electricity | Ikeja prepaid (`IKEDC  PREPAID`) | amount, ₦500 minimum |
| airtime | MTN, Airtel, Glo, 9mobile | amount |
| data | `… DATA BUNDLE` | **plan** (`MD…` item) |
| tv | DSTV, GOTV, STARTIMES | **plan** (`CB…` item) |

A plan is a Flutterwave item code with a fixed price. Those bills carry `plan` and
`plan_price_ngn`, and a payment for any other amount is refused rather than silently
accepted. Water and internet are not wired: asking for them refuses and charges
nothing. Flutterwave does not report units for a token, so they are worked out from
the tariff (≈ ₦209/kWh).

The demo's per-payment cap is ₦10,000 because a mid-range DStv bouquet costs more
than ₦5,000.

Receipts, wallets and linked identities live in Neon Postgres, one set per account.
`POST /v1/_stub/reset` wipes the signed-in account's rows and re-seeds the artboards'
six activity entries.
