# Stark: handoff

**Rewritten 2026-11-13, merged with the 2026-11-14 chain check.** This file says what is true now. It is not a log: history is in
`git log`, and an entry that stops being true is edited or deleted, not appended to. If
the code and this file disagree, the code wins, and the fix is to correct this file in
the same change.

Each claim carries the date it was last checked. "Not verified" means exactly that: do
not repeat it as a fact to a user, a judge or the README.

---

## 1. What Stark is

An AI agent that pays everyday Nigerian bills (prepaid electricity, airtime, data, TV)
from a balance, within limits the owner sets, by voice or chat. You say *"what's my
light bill"* and it answers from the account; you say *"top it up with 5000"* and a
meter token comes back, but only if the vault contract lets the payment through.

Product rules that hold everywhere:

- Money in the app is **whole naira, stored as integers**. No floats, no strings.
- No chain words in user-facing copy. Adding money is the one place a coin appears:
  crypto is the default, sized in the coin the user names (USDC unless they say).
- Black and burnt orange (`#C2410C`, `#F08A4B` on dark), Crimson Pro headings, Inter
  body, no sliders anywhere.
- `docs/API.md` is frozen: changes only add to it.

---

## 2. State, as of 2026-11-14

| Part | State | Last checked |
|---|---|---|
| Vault contract | Live on testnet; user vaults sit under `stark-usdc-fcb734.testnet` (e.g. `u-e2e541dbcb1.stark-usdc-fcb734.testnet`). Deposits, a repeated deposit sent back, a ₦5,000 `pay` that moved 3.205130 USDC to the treasury, and refusals over the cap and to an unlisted meter all happened on chain. | 2026-11-12 (README) |
| Rate bound (§5) | **In code, not on chain.** Built and tested on 2026-11-13; `apps/backend/assets/stark_vault.wasm` is rebuilt. Two mainnet vaults read on 2026-11-14 carry different `code_hash`es, so they do not follow one published contract; with no upgrade method, the three existing vaults never get it. Vaults created from the new wasm do (§8.2). | 2026-11-14 |
| Mainnet | Production runs on mainnet from 2026-11-12, with `funder.moonboys-stark.near` as funder and treasury (there is no `treasury.*` account). Three user vaults, `u-312d6989246f5965`, `u-fbda9ededd79777a` and `u-278a146620c99d70` under the funder, each with deployed code, one `pay`-only key, USDC and real policies; `payment_count` 6, 8 and 0. Their `owner` is still the funder (§5). | 2026-11-14 |
| Bill payment | Flutterwave is the only provider for bills, bank deposits and bank withdrawals, from one NGN balance. It only accepts calls from whitelisted IPs; **the production IP was whitelisted on 2026-11-13** (owner). No live token is recorded in this file yet: record the first one here (§8.1). | 2026-11-13 |
| Bank deposits | Hosted checkout built. On 2026-11-03 every checkout link showed `Initialization failed` in test mode, and the dashboard's *Enable v3 webhooks*, *Enable webhook retries* and *Settle to my payout balance* were not set. Not rechecked since. | 2026-11-03 |
| Crypto deposits | NEAR Intents (1Click) quotes are live, mainnet only. No deposit has completed. | 2026-11-12 (README) |
| Crypto withdrawals | Built (`wallet/crypto_withdrawal_service.py`); off unless `STARK_TREASURY_NEAR_ACCOUNT` and a full-access `STARK_TREASURY_KEY` are set for the environment. | 2026-11-03 |
| Agent | NEAR AI. Default model `Qwen/Qwen3.6-35B-A3B-FP8` since 2026-11-13 (`model.py`); `STARK_MODEL` pins another per deploy. No regex left in the agent (§4). | 2026-11-13 |
| Voice | Whisper Large v3 on NEAR AI (Private TEE) in; ElevenLabs Flash out, streamed. | 2026-11-03 |
| Doors | Web app Talk screen and Telegram (`@hellostarkai_bot`, webhook `/v1/tg/webhook`). SMS, WhatsApp, TV control and the Kokoro voice were removed on 2026-11-12. | 2026-11-12 |
| Apps | [dash.hellostark.xyz](https://dash.hellostark.xyz) (app, `/demo` needs no sign-up), [geddon.hellostark.xyz](https://geddon.hellostark.xyz) (API; Swagger only with `STARK_DOCS=1`), [hellostark.xyz](https://hellostark.xyz). Deployed by Brimble on push to `main`. | 2026-11-12 |
| Sign-in and storage | Neon Auth sessions on every `/v1` route; accounts, bills, limits, receipts, wallets, identities and telemetry in Neon Postgres, scoped per account, surviving restarts. | 2026-11-11 |
| Admin | Operator page: service fee, operator limits, alerts, treasury coverage including users' vault USDC. | 2026-11-13 |

---

## 3. The money flow

```
FUND      Flutterwave checkout ─► verify by tx_ref ─┐   (webhook, redirect or a due check)
          1Click quote ─► /v0/status SUCCESS ───────┼─► wallet credit (keyed on the deposit id)
                                                    │   + vault fund(amount, id)
PAY       intent judge says PAY? ─► gate (paused, caps, allowlist, balance, float) ─► vault pay
          (agent key) or pay_approved (owner key, approved over a cap) ─► record ─► Flutterwave
          bill ─► charge on delivery │ vendor failed ─► vault refund(payment_id)
WITHDRAW  resolve name ─► hold + vault debit ─► Flutterwave transfer (reference = withdrawal id;
          GET /transfers?reference= first) ─► SUCCESSFUL │ FAILED ─► credit back + vault fund
CRYPTO    hold ─► USDC at market + STARK_USDC_NGN_SPREAD ─► treasury ft_transfer to a 1Click address
LOOP      every 30s: flush vault ops, send withdrawals, settle pending bills, warn on low float
```

- **Stark fronts the naira.** A credited deposit is spendable at once from Stark's
  Flutterwave balance; Flutterwave settles collections into it later (batched daily).
  A payment the balance cannot cover is refused `float_low` before anything is signed.
  `python -m app.modules.treasury.treasury_service` reports owed against held.
- **Record before buying, charge on delivery.** The receipt is written `pending` with
  its `request_id` and the amount held (`record_debit`) before the vendor call;
  delivery turns the hold into spend, failure returns it. A retry reuses the
  `request_id`, and `BillPaymentService.settle_pending` re-reads every pending bill older
  than a minute, so nothing depends on a retry.
- **The biller is off chain.** Billers in Nigeria take naira, so after `pay()` moves the
  USDC to the treasury, Flutterwave pays the biller. The chain shows the payment and, if
  the vendor failed, its refund; the token and the vendor's reference live in Postgres.

Decisions behind it (owner, 2026-11-03): one Flutterwave account for everything (it
replaced Bachs and VTpass, so no float to refill); one vault per user, a sub-account
`u-<id>.<funder>` created in one transaction from a global contract; deposits credited
only from the provider's own verify call, never from a webhook body; caps synced to the
vault lazily before each payment.

---

## 4. The agent

`apps/backend/app/modules/agent/`, split by job on 2026-11-13:

| File | Holds |
|---|---|
| `agent.py` | `Agent.respond`: the snapshot, the model loop, tool routing, link scrubbing |
| `prompt.py`, `tools.py` | what the model is told, and the tool schema |
| `model.py` | `NearAiModel`: pooled keep-alive connections, 10s round timeout, 3 attempts on network errors |
| `payment_gate.py` | `PaymentGate.pay`: every rule a payment passes, in code |
| `payment_intent.py` | `PaymentIntentJudge`: did the user ask to pay? |
| `spoken_amounts.py` | the naira figures in a transcript |
| `toolbox.py`, `account_toolbox.py`, `errors.py` | what the agent may touch, and its refusals |
| `policy.py` | the vault's rules in Python; a test fails if it drifts from `policy.rs` |

The gate, in order. Each refusal says nothing was charged:

1. **The intent judge.** A second model call, started with the turn beside the main one,
   with no tools, shown only Stark's last reply and the user's message. It must answer
   `PAY` or `AGAIN`; anything else, two verdicts, no answer or a failed call refuses with
   `not_a_payment_request`. It replaced regexes, which missed phrasings people use.
   Checked live on 2026-11-13: 42 of 42 phrasings, 10 of them pidgin and other wording
   the prompt was not written against. A judgment took 0.6 to 6.8s that day, but runs in
   parallel, so a payment does not wait for two rounds in a row.
2. **The bill.** Unknown bills refuse; a plan pays its own price only. A bill is payable
   from the moment it is saved, from any door; the caps, pause and balance still apply.
3. **The figure.** No figure said and no plan price is `amount_required`; a figure the
   user did not say is `amount_mismatch` ("pay 500" can never become ₦5,000).
4. **A repeat.** The same bill and figure, delivered or pending within five minutes, is
   `duplicate_payment` unless the judge said `AGAIN`.
5. **The limits,** per payment → monthly → balance, the same order as `POST /v1/payments`.
   Over a cap goes to the owner for approval (`pay_approved` on chain); what one request
   already paid a bill counts toward the per-payment cap, so a split goes for approval.

Also: the snapshot (account, bills, last five payments, limits, funding) rides in the
system prompt, and the read tools are withheld while it is there; links the model writes
are removed from the reply; with no
`NEAR_AI_API_KEY` every turn answers that Stark lost connection and pays nothing.

**Latency.** On 2026-11-13 the NEAR AI host was slow for calls that carry tools: three
payment turns on unchanged `main` took 27 to 38s, with read timeouts and retries. That is
the provider, not the agent; `STARK_TURN_LOG` records each retry and why. One model call
now gives up after 25s in all (`RETRY_BUDGET_SECONDS`), and a pooled socket the host has
already closed is dropped instead of lent out.

---

## 5. Trust model: what the chain guarantees, and what it does not

| Guarantee | How |
|---|---|
| The agent's key can only call `pay` on its own vault | one function-call key per vault, scoped to `pay` |
| Monthly cap, per-payment cap, meter allowlist, pause | checked in `pay()`; owner-only to change |
| Over-cap payments need the owner | `pay_approved` is owner-only |
| The rate cannot drain a vault | `set_rate` refuses a rate above the owner's `set_rate_ceiling`, or more than 5% above the rate the day opened at, even when the funder signs; falls are free; `get_state` shows `max_usdc_per_kngn`. **Only in vaults created from the new wasm (§8.2).** |
| Deposits only from Stark | USDC from anyone but the funder or treasury is sent back untouched |
| Code cannot change under a vault | no upgrade method; vaults run the published global contract |

What it does **not** guarantee, said plainly:

- **Stark is custodial.** Users sign in with email and hold no NEAR key, so Stark's
  funder is each vault's owner. Ownership can move to the user's own account
  (`propose_owner` then `accept_owner`), but no flow in the app does that yet. While
  Stark is owner it could raise the rate ceiling; it still cannot raise the rate more
  than 5% a day.
- **The treasury is Stark's.** A paid bill's USDC goes to it, crypto deposits are
  bought by it, and it pays Flutterwave. The vault's balance is real USDC; the naira
  behind a bill payment is Stark's.
- **The last step is off chain** (§3).
- **The chat model is not claimed private.** Whisper runs in a Private TEE. The chat
  model's tier depends on `STARK_MODEL`; check near.ai/models before saying anything
  about it.
- **The monthly cap in Python counts delivered spend**, so two simultaneous payments can
  each pass it in Python; the vault's own cap still binds on chain.

### Doors and identity

One brain, many doors: every door verifies, dedupes, resolves the identity, then calls
the same `Agent.respond`. A door never branches money logic on its channel.

- **Verify before parsing.** Telegram's `X-Telegram-Bot-Api-Secret-Token` is checked in
  constant time before any JSON is read; a failure is 401 and processes nothing.
- **An unlinked sender never reaches the agent** and never gets a wallet: it gets link
  instructions only. Linking is the only way a channel claims an account; a user id in
  a message or webhook body is never trusted. Telegram keys on the numeric user id.
- **Link codes** are 6 digits, single use, 10 minutes, stored hashed, 5 attempts per
  sender per 10 minutes. `unlink` removes the identity.
- **Dedupe** on `(channel, message_id)`, so a re-delivered update cannot pay twice.
- **The wake gate** (`voice/wake.py`) applies to voice, not typing: a voice note must
  open with "Stark" or a near-miss recognizers produce for it.
- **Fail closed:** a bad signature, unknown sender, expired code or missing session all
  mean no payment.

---

## 6. Not built, or not verified

- **No live bill purchase is recorded here.** Every bill shape (result, token, pending)
  comes from Flutterwave's docs and faked clients until the first live one is checked
  against `vending.py` (§8.1).
- **No completed deposit or withdrawal**, bank or crypto (§2).
- **Global-contract publish and per-user vault creation on mainnet** have not been
  round-tripped; check the publish transaction on the explorer before creating a vault.
- **A voice note to a real Telegram chat** and a **delivered reminder push** have not
  been recorded.
- **Telemetry suggestions** (`load_imbalance`) need two reporting devices; no real meter
  has posted.
- **Apple Messages, iOS Siri intents, the wall-phone PWA install** are design only.
- **Water and internet** bills can be saved but not paid; paying one fails plainly and
  charges nothing.
- **Unmeasured:** Whisper accuracy on Nigerian-accented English; NEAR AI's minimum
  top-up; whether the AC is on a 13A plug (16A smart plug) or hardwired (CT clamp).
- **Design source jargon** (in `Desktop/export/`, not this repo): `Talk.dc.html:63`
  "Checking your vault", `Main.dc.html:284` "the vault still blocks…", `Fund.dc.html:64`
  coin list and a raw `0x…` address.
- History is not rewritten on purpose: renaming a bill keeps old receipts' `bill_label`,
  deleting one keeps its activity rows, and a plan change never reprices past receipts.

---

## 7. Hackathon

Re-read `nearhackathon.com/HACKATHON.md` before submitting; it warns rules may change.

| Fact | Value |
|---|---|
| Build window | `2026-11-01T00:00:00Z` → **`2026-11-14T23:59:00Z`** |
| Judging | starts 11-16, results by 11-18 |
| Submit | `POST https://nearhackathon.com/api/applications` (12000-byte body) |
| Repo | `github.com/maxxexee/stark-ai`, branch `main`; must be **public** by the deadline |
| Demo | the human publishes a public X post with video or screenshots |
| Tracks | **`realworld`** (lead) and **`security`**. Not `agents`: Stark spends under a policy but does not earn or negotiate, so the claim was dropped on 2026-11-13. Not `privacy`. |

Submission traps: `website` is a spam trap (any value rejects the submission); one
immutable submission per team (`409` on a reused name or email); payout needs a mainnet
named account the human creates; `size` is exactly `1`, `2 - 4`, `4 - 6`, `6 - 8` or
`8+`; `requestId` is one UUID reused on retries; `403` means submissions are closed, do
not retry. AI judges read the README: "do X – see Y" steps, no marketing.

---

## 8. Next, in order

1. **First live bill (now unblocked).** Buy one Ikeja prepaid token, check the result,
   token and pending shapes against `vending/vending.py`, and record the token's receipt
   id and date in §2. Then one checkout deposit and one bank withdrawal end to end,
   watching the webhook arrive; set the three Flutterwave dashboard switches in §2 first.
2. **Ship the rate bound to vaults (owner).** New vaults are deployed from
   `STARK_VAULT_CODE`; once it points at the rebuilt `assets/stark_vault.wasm` (or, for
   `global:<funder>`, once that code is published with `vault_chain publish`), every
   vault created after that carries the bound. The three existing mainnet vaults are
   pinned to the code they were created with and have no upgrade method, so they keep it: move
   their users to new vaults if they need the bound. Then set a ceiling on each new
   vault with `set_rate_ceiling`, signed by its owner. The backend already follows
   `max_usdc_per_kngn` when it syncs the rate, and covers the gap when the market moves
   faster than 5% a day.
3. **Crypto withdrawals (owner).** Set `STARK_TREASURY_NEAR_ACCOUNT` and a funded
   full-access `STARK_TREASURY_KEY` for the environment; until then they stay off.
4. **Hand a vault to its user** (product decision): a way for a user to create a NEAR
   key and `accept_owner`. That is the step that ends custody (§5).

**Never without explicit human confirmation:** submit the application, publish on X,
make the repo public, sign or broadcast transactions, spend tokens, deploy to mainnet,
or commit secrets.

---

## 9. Working in this repo

```sh
bun install && (cd apps/backend && bun run setup)   # once
bun dev                                             # website :5173, dashboard :5174, API :8000
cd apps/backend && bun run test                     # backend unit tests
cd apps/contracts/vault && cargo test               # 91 contract tests
```

- **Secrets are in Infisical**, project `stark`, folders `/backend`, `/dashboard`,
  `/website` in `dev` and `prod`. The `dev` scripts run
  `infisical secrets-manager run --env=dev --path=/<app>`. Never write a `.env`.
- **`DATABASE_URL` is required.** The API refuses to start without a Neon pooler URL;
  the schema creates itself.
- **Hermetic suites** (`tests.test_agent`, `tests.test_live_paths`) need no secrets.
  The full suite under dev secrets takes over ten minutes and has failures that also
  happen on `main` (fees, settlement, vending disco lookup, top-up/withdraw 501, approvals
  past cap, Telegram no-speech). Re-run a failure on `main` before calling it a regression.
- **Neon Auth refuses a request with no `Origin`.** Send `Origin: http://localhost:5174`
  from scripts.
- **1Click sits behind Cloudflare, which answers Python's default User-Agent with 403
  (error 1010).** Every live call failed while the faked tests passed. The clients send
  `stark-backend/1.0`; keep it on any new client.
- **A push to `main` is a deploy** (Brimble). After editing `brimble.toml`, redeploy the
  services one at a time.
- **Contract changes:** `cargo near build non-reproducible-wasm`, copy
  `target/near/stark_vault.wasm` to `apps/backend/assets/`, then publish (§8.2). New
  state goes under raw storage keys (see `PENDING_OWNER_KEY`, `RATE_CEILING_KEY`), never
  as a new `Vault` field: that would stop existing vaults from deserialising.
- If `cargo` says there is no default toolchain although rustup is installed, `$HOME` is
  redirected: set `RUSTUP_HOME` to the real `~/.rustup`.

Code rules worth knowing before an edit:

- **Charge only on delivery**, inside the payment service. Charging earlier turns a
  vendor hiccup into a double charge; there are tests for pending, failed, no-token and
  settlement races.
- **Sign before booking, and fail closed.** An unbroadcast signature costs nothing; a
  configured signer that cannot sign refuses the payment (`authorisation_failed`).
- **`receipts.api_shape()` is the API surface**; the stored row has vendor fields the
  API never shows.
- **`POST /v1/_stub/reset` replaces the signed-in account's rows.** Tests and demos only.
- **Errors are `{code, message, detail}`**; callers branch on `code`. Times are ISO 8601
  UTC with `Z`.

---

## 10. Reference

**Design source:** 24 artboards in `Desktop/export/design-source/` on the original dev
machine (`Main`, `Connect`, `AddMeter`, `Fund`, `Dashboard`, `Bills`, `BillDetail`,
`TopUp`, `Activity`, `Wallet`, `Limits`, `Talk`, `Telegram`, plus `m-*` phone versions).
Live canvas: `https://claude.ai/artifact/7EjFC1ozPTinbkhLHxZTEm`.

**Verified external facts** (checked against the live service or primary docs):

| Fact | Evidence |
|---|---|
| NEAR AI runs Whisper Large v3 as Private TEE | near.ai/models, 2026-11-03 |
| NEAR AI pricing is USD per 1M tokens | matches OpenAI's own `gpt-5-nano` $0.05/$0.40 |
| AI cost is fractions of a cent a turn | the electricity bought costs ~150× the model |
| Picovoice's free tier ended 2026-06-30 | so the wake word is a `"stark"` transcript prefix (`voice/wake.py`) |
| ElevenLabs free keys get HTTP 402 on library voices | only the account's premade voices work; `pcm_24000` is in the free tier |
| 1Click needs a real mainnet `refundTo` and refuses small amounts | ~1.9 USDC minimum for Tron, 2026-11-03 |

**Hardware for the wall phone:** a spare Android phone running the PWA (HTTPS, Wake
Lock) as the ears, a wired or Bluetooth speaker as the mouth, mic muted while Stark
speaks. Keep it ventilated: a phone held at 100% all day swells its battery.
