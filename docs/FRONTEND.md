# Stark: frontend handoff

You are picking up the web app and dashboard. The backend is already running and
every route your screens need exists today. This file tells you what to build,
what to call, and which rules matter. Read this first, then `docs/API.md` for
exact shapes.

Last updated: 2026-10-22.

---

## 1. Get it running in two minutes

```sh
cd apps/backend
bun run setup              # once: a .venv with FastAPI and uvicorn
bun dev                    # http://127.0.0.1:8000 — every route is browsable at /docs
```

In another shell:

```sh
cd apps/backend
bun smoke                  # 69 checks, exits 1 if anything is broken
```

That is the whole setup. Any python3 from 3.9 works. The server keeps its data in Neon Postgres (`DATABASE_URL` in
`apps/backend/.env`), so restarts keep history, balances and linked chats.

To return everything to the demo state (seeded bills, seed balance, seed
activity):

```sh
curl -X POST http://127.0.0.1:8000/v1/_stub/reset
```

Use it between demo runs. It deletes bills you added, so do not call it while
someone is demoing.

---

## 2. The rules that matter most

These are the ones that will hurt you if you ignore them.

**Branch on `code`, never on `message`.** Every error looks like this:

```json
{ "code": "over_cap", "message": "That would go over your monthly limit.", "detail": {} }
```

`code` is stable and machine readable. `message` is human copy that we may
reword at any time. If your UI does `if (message.includes("limit"))` it will
break silently.

**Money is integer naira.** Every field ending in `_ngn` is a whole number.
Never divide by 100, never treat it as kobo, never render it as a float. So
₦5,000 renders as `5000` in the payload and `"₦5,000"` on screen.

**A payment is not done until `status` is `delivered`.** The full list:

| `status` | What it means | Charged? |
|---|---|---|
| `delivered` | Vendor confirmed. Electricity also has a `token` | yes |
| `pending` | Still processing at the vendor. Not paid | no |
| `failed` | Vendor refused. Nothing charged | no |
| `declined` | Our policy gate refused it before the vendor call | no |
| `received` | Money in, a deposit, not a payment | n/a |
| `sent` | Money out, a withdrawal | n/a |

The demo story that matters: a `pending` payment must show as "still going
through", never as a success with a checkmark. Claiming a pending payment is
done would be lying to the user about money.

**Only electricity returns a `token`.** Airtime, data and TV come back with
`token: null`. If you show a token field on those bills, you are showing null.

**The wake gate is server side.** `/v1/voice` returns:

```json
{ "ignored": true, "reply": null }
```

when the transcript did not contain the word "stark". The client must stay
totally silent. No animation, no beep, no empty bubble. The point is that
ambient conversation in the kitchen does not trigger the assistant.

---

## 3. What to build, in this order

The backend is ahead of you on every one of these. Build in this order because
it is the order the demo needs.

| # | Screen | Endpoints | Status |
|---|---|---|---|
| 1 | Home dashboard | `GET /v1/state` | route live |
| 2 | Bills list | `GET /v1/bills` | route live |
| 3 | Activity | `GET /v1/activity` | route live |
| 4 | Voice | `POST /v1/voice` | route live |
| 5 | Add bill | `GET /v1/plans`, `POST /v1/bills` | route live |
| 6 | Bill detail | `GET /v1/bills/{id}`, `PATCH`, `DELETE` | route live |
| 7 | Limits | `GET /v1/limits`, `PATCH /v1/limits` | route live |
| 8 | Wallet / fund | `GET /v1/wallet`, `POST /v1/wallet/topup`, `POST /v1/wallet/withdraw` | route live |

Every one of these works against the running server right now. Nothing needs
mocking except what you choose to mock for speed.

If you are short on time, 1 through 4 are the demo. 5 through 8 make it feel
like a product.

---

## 4. Screen by screen

### Home dashboard

One call gets you everything:

```sh
curl http://127.0.0.1:8000/v1/state
```

```json
{
  "user_id": "user_tunde",
  "first_name": "Tunde",
  "currency": "NGN",
  "balance_ngn": 64200,
  "cap_ngn": 30000,
  "spent_ngn": 23000,
  "remaining_cap_ngn": 7000,
  "units_left": 11.4,
  "days_left": 4,
  "bills": [],
  "as_of": "2026-10-22T12:00:00Z"
}
```

`units_left` and `days_left` are `null` when the user has no electricity bill.
Do not render `null` as `0`. Hide the block instead. `days_left` is an estimate
from purchase history, so do not present it as a precision number.

Poll this, or refetch after any payment. There is no websocket.

### Bills

`GET /v1/bills` returns the array already inside `/v1/state`. Each bill:

```json
{
  "id": "bill_home_meter",
  "kind": "electricity",
  "provider": "Ikeja Electric",
  "label": "Home",
  "reference": "0101170026583",
  "last_amount_ngn": 5000,
  "last_units": 23.9,
  "last_paid_at": "2026-10-14T19:33:13Z"
}
```

`kind` is one of `electricity`, `airtime`, `data`, `tv`, `internet`, `water`.
`reference` is the meter, phone or smartcard number. It is never a wallet
address and must never be shown as one.

Data and TV bills also carry `plan` and `plan_price_ngn`, because those are
sold as fixed plans, not free amounts.

After a delivered payment, that bill's `last_amount_ngn`, `last_units` and
`last_paid_at` update and `units_left` goes up. Refetch after paying.

### Activity

`GET /v1/activity`, up to 20 rows, newest first. Same shape as a receipt, plus
`type` and `source`:

| `type` | Meaning | Counts as spend? |
|---|---|---|
| `bill` | A bill payment | yes, when delivered |
| `autotopup` | Automatic airtime top-up | no |
| `deposit` | Money added to the wallet | no |
| `withdrawal` | Money sent to a bank | no, but it lowers balance |

`source` is the channel that asked for it, like `Telegram voice note` or
`Wall phone`. `bill_id` is the string `wallet` for deposits and withdrawals.

A `declined` row is a payment our own gate refused. It is interesting UI. Show
it as "Stark stopped this" and never as a failure of the vendor.

### Voice

```sh
curl -X POST http://127.0.0.1:8000/v1/voice \
  -H 'Content-Type: application/json' \
  -d '{"transcript_hint": "hello stark what is my light bill"}'
```

Response:

```json
{
  "transcript": "hello stark what is my light bill",
  "ignored": false,
  "reply": "You have got 64,200 naira in your wallet and about 11.4 units left.",
  "token": null,
  "receipt_id": null
}
```

`reply` is already speakable text. Feed it to TTS as is. Do not reassemble
sentences and do not add your own punctuation rules.

Today you send `transcript_hint` as text. Real audio comes later, once speech
to text is keyed. Design the mic button now, wire it to the hint field, and
swap it when audio lands.

`actions` and `tx_hash` may also appear. They are for debugging. Never render
them.

### Add bill

Two steps in the UI: pick a provider, pick a plan.

First, load the catalogue. Never hardcode prices, they change at the vendor.

```sh
curl 'http://127.0.0.1:8000/v1/plans?kind=data&provider=MTN'
```

```json
[
  {
    "kind": "data",
    "provider": "mtn-data",
    "service_name": "MTN Data",
    "plan": "mtn-100mb-1000",
    "label": "N1000 1.5GB - 30 days",
    "price_ngn": 1000
  }
]
```

`label` is the vendor's own string. Render it as it comes.

Then create the bill:

```sh
curl -X POST http://127.0.0.1:8000/v1/bills \
  -H 'Content-Type: application/json' \
  -d '{"kind": "data", "provider": "MTN", "label": "My line",
       "reference": "08031234567", "plan": "mtn-100mb-1000"}'
```

The client never sends a price. The server looks it up. That is deliberate: a
client sent price would be a way to underpay a fixed price product.

Electricity accepts any disco's prepaid meter (the list in `BillKinds.providers`). Internet and water can be saved
but paying them refuses and charges nothing.

Errors to expect: `bad_kind`, `bad_reference`, `unsupported_product`,
`plan_required`, `unknown_plan`, `duplicate_bill`.

### Limits

```json
{
  "monthly_cap_ngn": 30000,
  "per_payment_cap_ngn": 10000,
  "spent_ngn": 23000,
  "remaining_cap_ngn": 7000
}
```

Patch either field. The change takes effect immediately, including for the
voice agent, with no restart.

```sh
curl -X PATCH http://127.0.0.1:8000/v1/limits \
  -H 'Content-Type: application/json' \
  -d '{"per_payment_cap_ngn": 5000}'
```

Values must be positive and the per-payment limit cannot exceed the monthly
one, otherwise `bad_limits`.

Be careful with the copy here. These are safety rails, not budgets. The design
deliberately has no sliders, because a slider invites dragging the limit up
mid purchase. Use steppers or presets and confirm the change.

### Wallet

```json
{
  "currency": "NGN",
  "balance_ngn": 64200,
  "spent_ngn": 23000,
  "monthly_cap_ngn": 30000,
  "remaining_cap_ngn": 7000,
  "added_this_month_ngn": 20000
}
```

Top up and withdraw both take an `amount_ngn` and an optional `request_id`:

```sh
curl -X POST http://127.0.0.1:8000/v1/wallet/topup \
  -H 'Content-Type: application/json' \
  -d '{"amount_ngn": 20000, "request_id": "dep_7f3c1a9b2d4e", "source": "Bank transfer"}'
```

Send your own `request_id`. If the same id is sent twice, the second call
returns the original entry and does not credit twice. That protects you from a
double tap on a flaky connection.

**Important honesty note.** This top up moves a number in a ledger. There is no
card processor and no bank transfer behind it. Do not design a flow that looks
like it takes a real payment until one is wired in. A demo screen that says
"Fund wallet" and instantly credits is fine as a demo. It is not a real product
feature yet.

---

## 5. Errors you must build UI for

The 409s are the interesting states. Build these first.

| `code` | HTTP | Your UI should say |
|---|---|---|
| `over_per_payment_cap` | 409 | Over your single payment limit |
| `over_cap` | 409 | Over your monthly limit |
| `insufficient_balance` | 409 | Not enough in the wallet |
| `unknown_bill` | 404 | That bill no longer exists, refetch |
| `bad_amount` | 400 | Fix the amount field |
| `vendor_failed` | 502 | Vendor refused. Nothing was charged |
| `duplicate_bill` | 409 | Already saved |
| `bill_in_flight` | 409 | That bill has a payment in progress |
| `bad_limits` | 400 | Fix the limits form |

`vendor_failed` carries the vendor's plain English line in `message`. Show it.
It is safe to show because it is written for humans, unlike our own `message`
strings which you should not branch on.

Ordering is per payment, then monthly, then balance. So a 20,000 payment
against a 10,000 single payment limit returns `over_per_payment_cap`, even when
it would also breach the monthly cap.

---

## 6. Design

The dashboard's tokens live at the top of `apps/dashboard/src/styles.css`. One of
each, nothing in between:

- **Theme:** light and neutral. Talk is the one dark, immersive screen (`talk-scope`).
- **Accent:** `#C2410C`, only for the main action, the current selection and focus.
- **Type:** Inter only. 12 / 13 / 14 / 16 / 20 / 24 / 32 via `text-xs` … `text-3xl`;
  no `text-[Npx]`, no serif, no uppercase eyebrows.
- **Radius:** one value, 8px, for buttons, fields, tabs, chips, rows, cards and
  dialogs. Fully round only for avatars, status dots and the mic.
- **Heights:** controls are 32px (sm) or 36px; a form's main action is 40px. A field
  and the button beside it are the same height.
- **Layout:** one centred column; the header row sits in that same column so the
  logo, titles and cards share a left and a right edge.
- No sliders anywhere in the product
- No crypto jargon at all

That last rule is absolute. No "vault", no "chain", no "wallet address", no
"transaction hash", no token symbols. The word "wallet" here means a naira
balance, which is the everyday Nigerian meaning, and that is fine. Money is
naira, always, and rendered with the naira sign.

The tone of the product is calm and confident. It does not nag and it does not
celebrate. A payment that went through gets a receipt and a quiet confirmation.
A payment that was refused gets a plain explanation of the rule that stopped it.

---

## 7. What is not real yet

Design around these. They will become real without any change to the shapes you
code against.

- **Payments are dry run.** Every purchase returns the same sample token:
  `4821 0937 5512 8846 3019`. Never present it as a live purchase and never put
  two of them side by side in the same screen or demo.
- **Auth is enforced.** Every `/v1` call needs a Neon Auth session: the dashboard
  signs up and signs in on `/login` (`VITE_NEON_AUTH_URL`), keeps the token, and the
  API answers **401 `unauthorized`** without it. A signed-out visit to an app route
  sends you back to `/login`.
- **Bills, limits and units reset on server restart.** The wallet, the receipt
  history and any linked chat persist in Neon Postgres (per account), but a freshly
  added bill and a patched limit live in memory. A restart returns them to the seed.
  Keep that in mind during a long demo session, or call reset and rebuild.
- **Voice takes text, not audio.** The mic button is a real button that posts a
  transcript for now.
- **TTS is not chosen.** Replies are text you can read aloud. Do not promise
  spoken answers until a provider is picked.

---

## 8. Working agreement

The backend contract in `docs/API.md` is frozen. Anything we change after this
point is additive: new fields, new endpoints. No renames, no removals, no type
changes. If you ever see a shape you were not promised change, that is a bug on
our side, so tell us rather than working around it.

If you need a field that does not exist, ask for it. Do not parse an id, do not
read a timestamp out of a message string, do not infer state from which fields
are null. Every id is opaque, every time is ISO 8601 UTC with a `Z`, every
field is `snake_case`.

The fastest way to get unstuck is to run the smoke test and then call the route
by hand:

```sh
cd apps/backend
bun smoke
open http://127.0.0.1:8000/docs   # Authorize with your token, then "Try it out"
```

If the smoke test passes and a route still misbehaves, it is ours, not yours.
