# Stark API — contract v1

**Status: frozen for the frontend.** Shapes here are what the UI may rely on. After
this point the only allowed change is **additive** (new fields, new endpoints).
Renames, removals and type changes mean bumping to `/v2`.

The FastAPI app in `apps/backend` implements all of this, and serves the same
surface as Swagger UI at **`/docs`** (spec at `/docs/openapi.json`), generated from
the DTOs the routes use — **only with `STARK_DOCS=1`** (local dev; off in production,
2026-11-12). This file stays the written contract: where they differ,
this file is the rule and the code is the bug.

---

## Conventions

| Rule | Detail |
|---|---|
| Base URL | `http://127.0.0.1:8000` locally. Prefix all product routes with `/v1`. |
| Money | **Integer naira**, field names end in `_ngn`. Never floats, never kobo, never strings. |
| Times | ISO 8601 UTC with a `Z` suffix, e.g. `2026-10-20T19:33:13Z`. |
| IDs | Opaque strings. Don't parse them, don't assume numeric. |
| Casing | `snake_case` everywhere. |
| CORS | Open on the stub, so any dev port works. |
| Auth | **Neon Auth session, enforced.** Sign up / sign in at the branch's Auth URL, then send `Authorization: Bearer <token>` on every `/v1` request — otherwise **401** `unauthorized`. The token is accepted **only** from that header, never from `?token=` (2026-11-12); `GET /v1/speak/stream` takes a short-lived ticket from `POST /v1/speak/ticket` instead. The Telegram webhook is the only `/v1` route without it: it authenticates with `X-Telegram-Bot-Api-Secret-Token`. Every token resolves to its own account, wallet and receipts. |

### Error shape

Every non-2xx response has this body:

```json
{
  "code": "over_cap",
  "message": "That would go over your monthly limit.",
  "detail": { "cap_ngn": 30000, "spent_ngn": 23000, "remaining_ngn": 7000 }
}
```

`code` is the machine-readable field — branch on it, never on `message`.

| `code` | HTTP | When |
|---|---|---|
| `unauthorized` | 401 | Missing, malformed or expired bearer token — sign in first |
| `admin_disabled` | 403 | `STARK_ADMIN_KEY` is not set, so admin routes refuse everyone (additive, 2026-11-11) |
| `paused` | 423 | The owner paused Stark; no payment is made until it is resumed (additive, 2026-11-03) |
| `unknown_request` | 404 | No payment request with that id (additive, 2026-11-03) |
| `request_closed` | 409 | The request was already approved, denied or has expired (additive, 2026-11-03) |
| `unknown_bill` | 404 | No bill with that id |
| `bad_amount` | 400 | `amount_ngn` missing, zero, or not an integer |
| `bad_watts` | 400 | Telemetry `watts` not a number |
| `over_per_payment_cap` | 409 | Payment exceeds the per-payment limit |
| `over_cap` | 409 | Payment would exceed the monthly cap |
| `insufficient_balance` | 409 | Payment or withdrawal exceeds the wallet balance |
| `bad_kind` | 400 | Bill or plan `kind` is not one of the supported kinds |
| `bad_reference` | 400 | Bill reference is not 4–32 characters |
| `bad_bill` | 400 | A bill add/patch field is invalid: an empty, too long (label over 40, provider over 48) or oddly spelled name — only letters, digits, spaces and `- ' . , & ( ) /` (2026-11-12) |
| `bad_renews_on` | 400 | `renews_on` is not a date like `2026-11-03` |
| `bad_audio` | 400 | `/v1/voice` `audio` is not valid base64 |
| `audio_too_large` | 413 | `/v1/voice` clip is over 8 MB, or the request body is over 12 MB |
| `bad_text` | 400 | `/v1/speak` or `/v1/speak/ticket` `text` is empty or over 2,000 characters |
| `rate_limited` | 429 | Too many speak or telemetry calls this minute for this account; `detail.retry_after_seconds` says when to try again (additive, 2026-11-12) |
| `unsupported_product` | 400 | No confirmed vendor product for that provider |
| `plan_required` | 400 | A data/TV bill was sent without a `plan` |
| `unknown_plan` | 400 | `plan` is not a code in the vendor catalogue |
| `duplicate_bill` | 409 | That kind + reference is already saved |
| `bill_in_flight` | 409 | The bill has a pending payment; try again after it settles |
| `bad_limits` | 400 | A limit is not positive, or per-payment exceeds monthly |
| `no_route` | 404 | Unknown path |
| `bad_request` | 400 | The body is not valid JSON, or a field has the wrong type (additive, 2026-10-27) |
| `not_configured` | 409 | `POST /v1/link/code` while `STARK_TG_OWNER_EMAIL` names no account (additive, 2026-10-27) |

> Ordering note: a **pause** beats everything. Otherwise the **per-payment** cap is checked first, then the **monthly** cap,
> then the balance. An amount that breaches all three returns `over_per_payment_cap`.
> Ordering matters when the caps differ: a ₦20,000 payment with a ₦10,000
> per-payment limit returns `over_per_payment_cap`, not `over_cap`.

---

## Endpoints

### `GET /v1/state`

Everything the dashboard needs in one call. Poll or refetch after any payment.

```json
{
  "user_id": "user_tunde",
  "first_name": "Tunde",
  "currency": "NGN",
  "balance_ngn": 64200,
  "cap_ngn": 30000,
  "spent_ngn": 23000,
  "remaining_cap_ngn": 7000,
  "paused": false,
  "units_left": 11.4,
  "days_left": 4,
  "bills": [ /* Bill objects, see below */ ],
  "due_soon": [
    {
      "id": "bill_dstv",
      "kind": "tv",
      "provider": "DStv",
      "label": "Living room TV",
      "renews_on": "2026-10-27",
      "days_until": 3,
      "price_ngn": 7900
    }
  ],
  "as_of": "2026-10-20T19:33:13Z"
}
```

`units_left` and `days_left` are worked out per account, never invented
(2026-10-27). `units_left` is the electricity units ever delivered minus the energy
the account's own readings (`POST /v1/telemetry`) measured since the first top-up;
`days_left` is that divided by the measured kWh a day over the last 7 days. Both are
`null` with no electricity bill; `units_left` is `null` before the first delivered
top-up, and `days_left` is `null` until there is at least an hour of readings.
Readings only cover devices that report, so measured use can only under-count.

`due_soon` is **additive** (2026-10-24): every bill whose `renews_on` is inside the
**7-day window**, soonest first — including one that went overdue inside that window
(`days_until` is then negative, which is the loudest reminder there is). A renewal
further out, or a date months in the past, is not listed: one is not due yet and the
other is stale data to fix. `price_ngn` is the plan's price, else the last amount
paid, else `null` — estimate it, never invent it. An empty list is the normal 
answer for a user with no renewal dates set.

After a **delivered** payment, that bill's `last_amount_ngn`, `last_units` and
`last_paid_at` update, and `units_left` increases by the delivered units. A `pending`
or `failed` payment changes none of them.

### `Bill`

```json
{
  "id": "bill_home_meter",
  "kind": "electricity",
  "provider": "Ikeja Electric",
  "label": "Home",
  "reference": "0101170026583",
  "last_amount_ngn": 5000,
  "last_units": 23.9,
  "last_paid_at": "2026-10-14T19:33:13Z",
  "renews_on": "2026-10-27"
}
```

- `kind` is one of `electricity`, `airtime`, `data`, `tv`, `internet`, `water`.
- `reference` is the meter / phone / smartcard number. **Never a wallet address.**
- `plan` and `plan_price_ngn` are **additive** (2026-10-22). Data and TV are sold as
  a *plan* (a Flutterwave item code such as `MD107`), not as a free amount, so those
  bills carry the plan and its vendor price. `amount_ngn` must equal
  `plan_price_ngn` or the payment is refused — a plan is not discountable. Electricity
  and airtime have no plan and take any amount inside the owner's limits.
- `last_units` and `last_amount_ngn` are `null` for a new bill.
- `renews_on` is **additive** (2026-10-24): a calendar date (`YYYY-MM-DD`) when the
  bill renews on a schedule — a DStv bouquet, an internet plan. **Absent** when unset
  (meters and phone lines usually are), not `null`. It is what puts the bill in
  `state.due_soon` and behind a reminder, so do not default it: a date a client made
  up is a nudge about nothing.

### `GET /v1/plans?kind=data&provider=mtn`

Every priced plan for **data** and **TV**, read from Flutterwave's live bill catalogue.
This is the list behind the plan picker — never hardcode prices in the app, they
change at the vendor.

```json
[
  {
    "kind": "data",
    "provider": "MTN",
    "service_name": "MTN",
    "plan": "MD107",
    "label": "MTN 1.5 GB",
    "price_ngn": 1000
  },
  {
    "kind": "tv",
    "provider": "DSTV",
    "service_name": "DSTV",
    "plan": "CB141",
    "label": "DSTV Access",
    "price_ngn": 1800
  }
]
```

Both query params are optional. `kind` must be `data` or `tv` (else `bad_kind`);
`provider` loosely matches a network name or biller code, so `mtn` finds MTN's data
biller (`BIL104`).
Sorted by `kind`, `provider`, then `price_ngn` ascending. `label` is the vendor's own
string — render it as-is.

### `POST /v1/bills`

Add a bill. Returns **201** with the `Bill` object.

```json
{
  "kind": "data",
  "provider": "MTN",
  "label": "My line",
  "reference": "08031234567",
  "plan": "MD107"
}
```

- `kind` — `electricity`, `airtime`, `data`, `tv`, `internet`, `water`.
- `provider` — required. For `electricity`/`data`/`tv`/`airtime` it must resolve to a
  Flutterwave biller (`MTN`, `mtn`, `Glo`, `9mobile` all work). Electricity is any
  disco's **prepaid** meter, by name or abbreviation (`Eko Electric`, `EKEDC`, `Ikeja
  Electric`, `IKEDC`, Abuja, Ibadan, Enugu, Benin, Port Harcourt, Kano, Kaduna, Jos;
  2026-11-12); anything else is `unsupported_product`. `internet` and `water`
  can be saved, but paying them refuses and charges nothing.
- `reference` — meter / phone / smartcard number; whitespace is stripped, 4–32 chars.
- `label` — optional, defaults to `provider`. At most 40 characters (provider: 48),
  letters, digits, spaces and `- ' . , & ( ) /` only, else `bad_bill` (2026-11-12):
  both are read to the agent, so free text there is a place to hide instructions.
- `plan` — required when the product is sold as a plan (data, DStv/GOtv/Showmax).
  Take the `plan` value from `GET /v1/plans`; the price is stored server-side as
  `plan_price_ngn`, so the client never sends a price the user could edit.
- `renews_on` — optional **additive** (2026-10-24): `YYYY-MM-DD` for a subscription
  that renews on a schedule. Validated exactly like the `PATCH` field below
  (`bad_renews_on`); omitting it saves a bill that never reminds.
- Adding a bill updates the payer's meter allowlist immediately — the agent can pay
  the new bill in the next turn.

Errors: `bad_bill`, `bad_kind`, `bad_reference`, `bad_renews_on`, `unsupported_product`,
`plan_required`, `unknown_plan`, and `duplicate_bill` (same `kind` + `reference`).

### `PATCH /v1/bills/{bill_id}`

Rename a bill, or change a data/TV plan. Every field is optional; returns the full
`Bill`.

```json
{ "label": "Living room", "plan": "dstv-yanga", "renews_on": "2026-11-03" }
```

Changing `plan` also rewrites `plan_price_ngn`. Errors: `unknown_bill`,
`bad_bill` (a label that is empty or breaks the rules under `POST /v1/bills`, or a
plan on a kind that has none), `unsupported_product`,
`unknown_plan`, and `bad_renews_on`.

`renews_on` is **additive** (2026-10-24) and has three states, because clearing a date
is a real thing users do:

| Sent | Result |
|---|---|
| `"2026-11-03"` (or any ISO string starting with a date) | stored as `YYYY-MM-DD` |
| `""` or `null` | the field is **removed** from the bill — it stops reminding |
| omitted | unchanged |

A date that does not parse is **400 `bad_renews_on`** — never silently dropped. A date
set to today or tomorrow shows up in `state.due_soon` on the next read, so a client can
prove the reminder works without waiting a week.

### `POST /v1/bills/{bill_id}/confirm` → `Bill`

A bill Stark saved from a chat or by voice comes back with `needs_confirmation:
true`, and stays off the list of references Stark (and the vault) may pay until its
owner confirms it here, signed in. Paying it before then is refused with **409**
`bill_unconfirmed`. Confirming removes the field; confirming twice changes nothing.
Unknown id: **404** `unknown_bill`.

### `DELETE /v1/bills/{bill_id}`

Returns `{ "deleted": true, "bill_id": "bill_abc123" }`. The bill's history stays in
`/v1/activity`.

Removing the last electricity bill sets `units_left` and `days_left` to `null` in
`/v1/state`; removing or adding any bill re-scopes the allowlist, so the agent cannot
pay a deleted bill and can pay a new one immediately.

Errors: `unknown_bill`, and `bill_in_flight` (409) while a payment for that bill is
still `pending` at the vendor.
- `last_paid_at` is `null` until first payment.

### `GET /v1/bills` → `Bill[]`

### `GET /v1/bills/{bill_id}` → `Bill`

404 `unknown_bill` if missing.

### `POST /v1/payments`

```json
{ "bill_id": "bill_home_meter", "amount_ngn": 5000 }
```

Returns **201** with a `Receipt`. Electricity adds `units` and a 20-digit `token`;
other kinds return `null` for both.

```json
{
  "id": "rcpt_3f9a1c",
  "bill_id": "bill_home_meter",
  "bill_label": "Home electricity",
  "amount_ngn": 5000,
  "units": 23.92,
  "token": "4821 0937 5512 8846 3019",
  "tx_hash": "8f2c1d4e...",
  "created_at": "2026-10-20T19:33:13Z",
  "status": "delivered",
  "request_id": "202610201930a1b2c3d4",
  "type": "bill",
  "source": "Telegram voice note"
}
```

`status` is **additive** (2026-10-22) and is the field that matters:

| `status` | Meaning | Charged? |
|---|---|---|
| `delivered` | The vendor confirmed; electricity also carries a `token` | yes |
| `pending` | Still processing at the vendor — **not** paid | held: out of `balance_ngn`, not in `spent_ngn`; no token |
| `failed` | The vendor refused, or the amount was wrong; nothing was charged | no |
| `declined` | The policy gate refused it before the vendor call | no |
| `received` | Money in (a deposit), not a payment | n/a |
| `sent` | Money out (a withdrawal), not a payment | n/a |

Do not render a payment as complete unless `status` is `delivered`. Only electricity
returns a `token` — airtime, data and TV are delivered without one.
A `pending` receipt keeps its `request_id`; sending the same intent again re-queries
that purchase instead of buying a second time. Its amount is held (2026-11-11): it
leaves `balance_ngn` when the purchase is recorded, so it cannot be spent twice, and it
moves to `spent_ngn` on delivery or back to `balance_ngn` on failure. The server
re-reads pending purchases in the background, so a receipt can turn `delivered` or
`failed` without a retry; poll `/v1/activity` to see it change.

Errors: `over_per_payment_cap` (409), `over_cap` (409), `insufficient_balance` (409),
`unknown_bill` (404), `bad_amount` (400), and `vendor_failed` (502) when the bill
vendor refuses or is unreachable. Build UI for the three 409s now — they are the interesting states.
`vendor_failed` carries the vendor's plain-English line in `message`; show it, and
reassure the user that nothing was charged (that is true — charging happens only on
delivery).

`units` is `amount_ngn / tariff`, tariff ≈ ₦209/kWh, so ₦5,000 ≈ 23.9 units.

Two more refusals happen before anything is recorded or bought (2026-11-03):

- `float_low` (**503**): Stark's Flutterwave balance cannot cover the purchase right
  now. Show `message` and offer to try again in a few minutes.
- `authorisation_failed` (**502**): the user's vault did not sign the payment — its
  onchain caps refused it, or the chain could not be reached. `message` is plain
  English and ends "Nothing was charged."

`tx_hash` is the vault's `pay` transaction whenever a chain is configured, on every
path (the app's own `POST /v1/payments` included), not only on agent payments.

### `GET /v1/activity`

Returns up to 20 entries, newest first. Same `Receipt` shape as above.

`type` and `source` are **additive** (2026-10-22):

| `type` | Meaning | Counts as spend? |
|---|---|---|
| `bill` | A bill payment — electricity, airtime, data or TV | yes, when `delivered` |
| `autotopup` | An automatic airtime top-up | no |
| `deposit` | Money added to the wallet (`status: received`) | no |
| `withdrawal` | Money sent to a bank (`status: sent`) | no, but it lowers the balance |

`source` is the channel that asked for it (`Telegram voice note`, `Wall phone`,
`Bank transfer`) and may be `null` for entries created before this field existed.
A `declined` entry is a bill the policy gate refused before any vendor call; it is
never charged. `bill_id` is `"wallet"` for a `deposit` and a `withdrawal`.

### `GET /v1/limits`

```json
{
  "monthly_cap_ngn": 30000,
  "per_payment_cap_ngn": 10000,
  "spent_ngn": 23000,
  "remaining_cap_ngn": 7000
}
```

`remaining_cap_ngn` never goes negative. `spent_ngn` counts **delivered bill
payments only** — deposits, withdrawals, autotop-ups and declined entries do not
consume the cap.

### `PATCH /v1/limits`

Send either or both fields; returns the full object above.

```json
{ "per_payment_cap_ngn": 5000, "monthly_cap_ngn": 40000 }
```

- Each value must be a positive integer (`bad_limits`).
- The per-payment limit cannot exceed the monthly limit (`bad_limits`).
- Takes effect **immediately for the agent as well as REST payments** — the next
  voice turn is refused at the new limit, with no restart.
- Stored per account (2026-10-27), so a restart keeps it. An account that never
  set one starts at `₦30,000` / `₦10,000`.

### `GET /v1/controls`, `POST /v1/controls/pause`, `POST /v1/controls/resume`

The owner's off switch (additive, 2026-11-03). All three return:

```json
{ "paused": true, "paused_at": "2026-11-03T09:12:00Z" }
```

- While paused, every payment is refused with **423 `paused`**: `POST /v1/payments`,
  the agent (voice, Telegram, the wall phone) and reminder nudges, which stay quiet.
  Questions are still answered.
- Pausing twice keeps the first `paused_at`; resuming an active account is a no-op.
- Stored per account, so a restart keeps it. `/v1/state` mirrors it as `paused`.
- A linked Telegram chat can send `/pause` and `/resume`.

### `GET /v1/approvals`, `POST /v1/approvals/{id}/approve`, `POST /v1/approvals/{id}/deny`

Payments over a limit wait for the owner (additive, 2026-11-03). When the agent is
asked for a payment that breaks the per-payment or monthly cap, it files a request
instead of only refusing, and says so: "…I've sent it to the Stark app for you to
approve. Nothing is paid unless you approve it within an hour."

```json
{
  "id": "req_3f9a1c2b4d",
  "bill_id": "bill_home_meter",
  "bill_label": "Home electricity",
  "amount_ngn": 15000,
  "reason": "over_per_payment_cap",
  "status": "pending",
  "created_at": "2026-11-03T09:12:00Z",
  "expires_at": "2026-11-03T10:12:00Z",
  "decided_at": null,
  "receipt_id": null
}
```

- `GET` lists the latest 20, newest first; lapsed ones read `expired`. `status` is
  `pending | approved | denied | expired`; only `pending` can be decided.
- **Only the signed-in app decides.** No chat command approves a request, so a voice
  in the room can ask but never also say yes.
- `approve` pays that one amount past the cap it broke and returns
  `{ "request": …, "receipt": Receipt }`. The pause, the balance and the vendor still
  apply: if the payment cannot go through nothing is charged, the error is returned
  (`paused`, `insufficient_balance`, `vendor_failed`, `unknown_bill`) and the request
  stays `pending` until it expires.
- `deny` returns the request and adds a `declined` entry to `/v1/activity`.
- Asking again for the same bill and amount while one is pending returns that one.
- Other refusals (paused, unlisted meter, short balance) never become requests; the
  agent logs them to `/v1/activity` as `declined`, with `reason` set.
- The wait is `approval_window_minutes` on `/v1/limits`: one of 15, 30, 60 (default),
  360 or 1440, set with `PATCH /v1/limits` (`bad_limits` otherwise).

### `GET /v1/payees`

Where Stark may pay, and what each has been paid (additive, 2026-11-03). One row per
saved bill, in the order they were added; Stark can pay nowhere else.

```json
[{ "bill_id": "bill_home_meter", "label": "Home", "kind": "electricity",
   "provider": "Ikeja Electric", "reference": "0101170026583",
   "paid_this_month_ngn": 15000, "paid_total_ngn": 23000, "payments": 3,
   "last_paid_at": "2026-11-02T19:33:13Z" }]
```

Only delivered bill and automatic payments count, the same rule as the monthly spend.
"This month" starts at midnight UTC on the 1st, where the monthly cap resets.

### `GET /v1/demo`

A made-up sample account for the public demo page (additive, 2026-11-03). **No
`Authorization` needed**, no database read, and nothing can be paid from it.

```json
{ "state": State, "activity": Receipt[], "approvals": PaymentRequest[],
  "limits": { "monthly_cap_ngn": 30000, "per_payment_cap_ngn": 10000 } }
```

Built from the same seed as `POST /v1/_stub/reset`, with timestamps that move with
the clock, so it always has a renewal due and one request waiting.

### `GET /v1/wallet`

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

### `GET /v1/wallet/methods`

```json
{ "bank": true, "crypto": true, "test_money": false,
  "withdraw": { "bank": true, "crypto": false } }
```

Which ways of adding money are switched on. `test_money` is true only while no
payment rail is configured. `withdraw` says which ways of taking it out are on;
`withdraw.crypto` stays false while Flutterwave runs on a test key, whose checkouts
credit naira nobody paid.

### `POST /v1/wallet/topup`

```json
{ "amount_ngn": 20000, "request_id": "dep_7f3c1a9b2d4e" }
```

**Test money**: nothing is collected. The entry's `source` is always `"Test money"`.
Refused with **501** `not_available` once Flutterwave or the crypto treasury is
configured, so a deployed app cannot mint balance, and minted balance can never leave
as real USDC.

Returns **201** with `{ "wallet": { /* GET /v1/wallet */ }, "entry": { /* Receipt */ } }`.
`entry.type` is `deposit`, `entry.status` is `received`, `entry.bill_id` is `"wallet"`.
Repeating `request_id` returns **200** with the original entry and credits nothing.
Top-ups never count towards the monthly cap.

### `POST /v1/wallet/deposits` → `Deposit`

```json
{ "method": "bank", "amount_ngn": 20000 }
{ "method": "crypto", "amount_ngn": 20000,
  "asset_id": "nep141:tron-d28a265909efecdcee7c5028585214ea0b96f015.omft.near" }
```

Returns **201**. Nothing moves yet: the balance changes when the deposit reads
`credited`, and from that moment it can be spent.

```json
{
  "id": "dep_1a2b3c4d5e6f7a8b",
  "method": "crypto",
  "amount_ngn": 20000,
  "credited_ngn": null,
  "status": "open",
  "note": null,
  "pay": { "asset": "USDT", "chain": "tron", "amount": "13.46",
           "address": "TQ…", "memo": null },
  "expires_at": "2026-11-03T13:00:00Z",
  "created_at": "2026-11-03T12:00:00Z",
  "credited_at": null
}
```

| `method` | `pay` | What the user does |
|---|---|---|
| `bank` | `{ "checkout_url" }` | go to it in the same tab: bank transfer, card or USSD on Flutterwave's page; it returns to `/wallet/add?deposit=<id>` |
| `crypto` | `{ asset, chain, amount, address, memo }` | send exactly `amount` of `asset` on `chain` to `address`, with `memo` when set |

`status`: `open` → `confirming` (bank only) → `credited`, or `expired`, `failed`,
`refunded` (crypto: the swap could not complete and what was sent goes back; `note`
says why). `credited_ngn` is what landed: a crypto deposit is credited at the rate
locked when it was quoted, and never above `amount_ngn`.

Errors: `bad_amount` (₦100–₦5,000,000), `bad_method`, `bad_asset` (400),
`not_available` (501, rail not configured), `provider_failed` (502).

### `GET /v1/wallet/deposits/{id}` → `Deposit`, `GET /v1/wallet/deposits` → `Deposit[]`

Reading an open deposit checks it with its rail first, so read it when something
happens (the redirect lands, the user comes back) and never on a timer. Between
reads, the `charge.completed` webhook settles a bank deposit, and Stark checks every
open deposit itself: half its age apart, one to fifteen minutes. 1Click has no
webhook, so that is what settles a crypto deposit. `404 unknown_deposit` for another
account's id.

### `POST /v1/wallet/deposits/{id}/tx`

```json
{ "tx_hash": "0x…" }
```

Optional, crypto only: tells the rail about the user's transfer so it is noticed
sooner. Errors `bad_method`, `bad_tx`.

### `GET /v1/wallet/crypto-assets`

```json
[{ "asset_id": "nep141:tron-d28a…omft.near", "symbol": "USDT", "chain": "tron" }]
```

Empty while crypto deposits are not configured.

### `POST /v1/wallet/deposits/preview`

```json
{ "asset_id": "nep141:sol.omft.near", "amount_ngn": 20000 }
→ { "asset_id": "nep141:sol.omft.near", "amount_ngn": 20000, "amount_in": "0.178036425", "rate": "1372.12" }

{ "asset_id": "nep141:sol.omft.near", "amount_in": "0.5" }
→ { "asset_id": "nep141:sol.omft.near", "amount_ngn": 56795, "amount_in": "0.5", "rate": "1372.12" }
```

Prices a crypto deposit from either side with a **dry** 1Click quote: nothing is
reserved, so call it as the user types (debounced). Send exactly one of `amount_ngn`
or `amount_in` (a decimal in the asset). Starting the deposit with the shown
`amount_ngn` locks its own quote, so its `pay.amount` can differ by a hair from a
preview made from the crypto side. Errors `bad_amount`, `bad_asset`, `not_available`,
`provider_failed`, and **`below_minimum`** (400) when 1Click refuses a swap that small;
its message names the floor in naira. `POST /v1/wallet/deposits` returns
`below_minimum` the same way.

### `GET /v1/wallet/rates`

```json
{ "deposit": "1370.56", "withdraw": "1390.56" }
```

Naira per USDC right now, as decimal strings: Paycrest's live rate less Stark's
spread for a deposit, plus it for a withdrawal. Refreshed at most once a minute. A
crypto deposit locks its own rate when it is quoted, so this is a guide, not a promise.
`provider_failed` (502) when no rate is known.

### `GET /v1/wallet/banks`, `POST /v1/wallet/bank-accounts/resolve`

```json
[{ "name": "Guaranty Trust Bank", "code": "058" }]
```

```json
{ "bank_code": "058", "account_number": "0123456789" }
→ { "account_name": "ADA OKAFOR", "bank_code": "058", "account_number": "0123456789" }
```

Show the resolved name before sending. `bad_account` (400) when the number does not
match the bank or is not 10 digits.

### `POST /v1/wallet/withdraw` → `Withdrawal`

```json
{ "amount_ngn": 10000, "bank_code": "058", "account_number": "0123456789" }
```

Returns **201**. The money leaves the balance at once (an activity entry with
`type: "withdrawal"`, `status: "processing"`), so it cannot be spent twice.

```json
{ "id": "wd_…", "method": "bank", "amount_ngn": 10000, "status": "processing",
  "note": null, "crypto": null, "created_at": "…", "updated_at": "…" }
```

`status`: `sending` (Flutterwave has not taken the transfer yet; it is retried with the
same reference) → `processing` → `paid`, or `returned` — the money is back in the balance and `note`
says why. The activity entry becomes `sent` or `failed` to match.

Errors: `bad_amount` (below ₦100), `bad_account`, `insufficient_balance` (409),
`not_available` (501), `provider_failed` (502). `GET /v1/wallet/withdrawals` lists recent ones,
bank and crypto together.

### `POST /v1/wallet/withdraw/crypto` → `Withdrawal`

```json
{ "amount_ngn": 20000, "asset_id": "nep141:tron-…omft.near", "address": "TQn9Y2kh…" }
```

`asset_id` is one from `GET /v1/wallet/crypto-assets`; `address` is the user's, on that
asset's chain. Returns **201**. The naira leaves the balance at once, becomes USDC at
Stark's rate (rounded down), and NEAR Intents swaps it into the asset and delivers it.

```json
{ "id": "wd_…", "method": "crypto", "amount_ngn": 20000, "status": "processing",
  "note": null,
  "crypto": { "asset": "USDT", "chain": "tron", "address": "TQn9Y2kh…",
              "amount": "13.21", "tx_hash": "8xK…" },
  "created_at": "…", "updated_at": "…" }
```

`status`: `sending` (the transfer is going out) → `processing` (the swap is running) →
`paid`, or `returned` with the money back in the balance and `note` saying why.
`crypto.amount` is what arrives: the quote, then the settled amount once `paid`.

Errors: `bad_amount` (below ₦1,000, or too little for that asset), `over_limit` (400,
over the per-withdrawal cap), `daily_limit` (409, Stark's daily crypto total is used up),
`bad_asset`, `bad_address` (400, 1Click refused it for that chain),
`insufficient_balance` (409), `not_available` (501, no treasury key),
`provider_failed` (502). Nothing is taken on any refusal.

### `POST /v1/flutterwave/webhook`

Flutterwave calls this, not the app. No bearer token: the `verif-hash` header must equal
the secret hash set in Flutterwave's dashboard (`FLW_SECRET_HASH`); **401**
`webhook_unverified` otherwise, `webhook_unconfigured` while it is unset. A
`charge.completed` is never credited from its body: the deposit is verified with
Flutterwave first. `transfer.completed` settles a withdrawal.

### `GET /v1/admin/overview`

Operator only. No bearer token: send `X-Stark-Admin-Key` equal to `STARK_ADMIN_KEY`,
compared in constant time. A wrong or missing key is **401** `unauthorized`; with no
key configured every request is **403** `admin_disabled`.

```json
{
  "treasury": {
    "owed_to_users_ngn": 1250000,
    "held": {"flutterwave_ngn": 900000, "pending_purchases_ngn": 5000,
             "treasury_usdc_as_ngn": 600000},
    "treasury_usdc": "400.25",
    "coverage_ngn": 245000,
    "unsettled_vault_ops": 0
  },
  "deposits": [{"method": "bank", "status": "credited", "count": 12, "amount_ngn": 300000}],
  "withdrawals": [{"method": "crypto", "status": "processing", "count": 1, "amount_ngn": 20000}],
  "withdrawals_in_flight": [{"id": "wd_…", "user_id": "…", "method": "crypto",
                             "amount_ngn": 20000, "status": "processing", "note": null,
                             "created_at": "…", "updated_at": "…"}],
  "deposits_open": [{"id": "dep_…", "user_id": "…", "method": "crypto",
                     "amount_ngn": 15000, "status": "open", "created_at": "…",
                     "expires_at": "…"}]
}
```

A balance that could not be read is `null`, not zero, and `coverage_ngn` then counts
only what was read. `treasury_usdc` is a decimal string. The in-flight lists hold at
most 50 rows each, oldest first.

### `GET /v1/suggestions`

```json
[
  {
    "id": "sug_units",
    "text": "About 11.4 units left — roughly 4 days.",
    "severity": "warn",
    "reason": "units_low"
  }
]
```

`severity` is `info` | `warn` | `alert`. `reason` is for debugging, not display.
Copy arrives as finished sentences — render, don't reassemble.

**Computed, not seeded** (2026-10-24). Every line comes from state the server
actually holds, and a signal without the data behind it is simply **not returned** —
the old hardcoded "your AC is 78% of your usage" line is gone. An empty list is a
normal answer, not an error. Worst news first, at most **4** items.

| `reason` | Fires when | `severity` |
|---|---|---|
| `units_low` | Meter runway ≤ 5 days, from **two or more delivered electricity top-ups on different days** (units/day) | `alert` ≤ 2 days, `warn` ≤ 4, else `info` |
| `units_low_estimate` | Same, but the pace is the state's own `days_left` estimate — the text says "roughly" | as above |
| `cap_near` | ≥ 80% of the monthly limit spent | `alert` ≥ 95%, else `warn` |
| `load_imbalance` | Two or more devices reported telemetry in the last 24h and one average draw is ≥ 60% of measured load | `info` |
| `bill_due` | A `renews_on` inside the reminder window (the `state.due_soon` rule), at most two items | `alert` on the day or overdue, `warn` ≤ 3 days, else `info` |

The `id`s are stable (`sug_units`, `sug_cap`, `sug_load`, `sug_due_<bill_id>`) — key a
dismissal on the `id`, not the copy, which is live text.

### `POST /v1/voice`

One endpoint for Telegram, the wall phone and any future speaker.

**Accepts either:**
- `application/json` with `{"audio": "<base64>", "audio_type": "audio/webm"}` — what
  the dashboard sends, because it records a Blob in the browser
- `multipart/form-data` with an `audio` file part (and optional `audio_type`) — what
  Telegram-style clients send
- `{"transcript_hint": "hello stark what's my light bill"}` — **no audio**, for probes
  and tests only

**Real audio in** (M4 finish, 2026-10-24). `audio` may be bare base64 or a full
`data:` URL. `audio_type` is the clip's MIME (`audio/webm`, `audio/ogg`, `audio/wav`,
`audio/mp4`). Send it: it decides how the clip is decoded. Max **8 MB**
(`audio_too_large`, 413). It is checked **before** `transcript_hint`, so a client that
can record never has to fake words with the hint.

**WebM and MP4 are decoded server-side.** The speech provider accepts WAV and
OGG/Opus and refuses WebM whatever it is called (measured 2026-10-24 — HTTP 400,
"audio could not be processed"), so the server transcodes any other container to
16 kHz mono WAV with `ffmpeg` before it is sent. That means:

- **Send the true MIME — the label decides.** WAV and OGG/Opus go straight through;
everything else is transcoded. A webm labelled `audio/wav` skips the conversion and
is then refused by the provider (`stt: failed`), because the provider sniffs the
bytes after the server has decided not to touch them.
- `ffmpeg` must be on the server for a browser clip to work. Without it the clip is
sent unchanged and comes back `stt: failed` — never a guessed transcript.
- A clip ffmpeg cannot decode also comes back `stt: failed`, not `bad_audio`:
the upload was well-formed, the sound was not usable.

The transcript is echoed in `transcript`. Every audio answer carries `stt`:

| `stt` | Meaning | What the client should do |
|---|---|---|
| `ok` | Whisper transcribed; the wake gate and agent ran on the words | normal |
| `failed` | Nothing was heard (`transcript: ""`, `reply: "I didn't catch that. Say it again?"`) | stay silent, keep listening |
| `no_key` | The server has no speech key (`transcript: ""`, reply says so) | offer the keyboard |

**A transcript is never invented.** When the clip is not understood the agent is not
called at all, `transcript` is empty, and no `audio` is synthesised. Bad base64 is
**400 `bad_audio`**, not a silent miss.

```json
{
  "transcript": "hello stark what's my light bill",
  "ignored": false,
  "reply": "You've got ₦64,200 in your wallet and about 11.4 units left — roughly 4 days at this rate.",
  "token": null,
  "receipt_id": null,
  "actions": ["get_state"],
  "tx_hash": null,
  "audio": "data:audio/wav;base64,UklGRi…",
  "stt": "ok"
}
```

`stt` is **additive** (2026-10-24) and only present on a request that carried audio —
a `transcript_hint` request keeps the exact old shape.

`actions` and `tx_hash` are **additive** (2026-10-22). `actions` lists the tools the
agent ran, which is useful for debugging a bad answer; `tx_hash` is set only when a
payment was signed onchain. Neither is user-facing copy — do not render them.

`audio` is **additive** (2026-10-23): the same reply, spoken by ElevenLabs when it is
keyed, as a WAV data URL — or `null`
whenever voice is off (no key configured, ElevenLabs down, synthesis failed, or
`ignored: true`). Play it when present; when it is `null`, render `reply` as text.
`reply` stays the source of either way.

**The voice does not read `₦`.** It is not in the voice's pronunciation
dictionary. It says the letter N (measured 2026-10-24 by synthesising and
transcribing the clip back), so amounts are handed to the voice as `64,200 naira`.
`reply` keeps the sign for display; do not treat the two as byte-identical, and do not
send your own text to a voice expecting `₦` to be read.

**Text first, always.** Send `{"speak": false}` to skip synthesis entirely: the
words come back in one model turn and `audio` is `null`. Speak afterwards with
`POST /v1/speak` (below). The dashboard does exactly this, because a reply you
cannot read yet is not fast — speaking must never decide when text appears.
`speak` defaults to `true`, so clients that ignore it keep the old behaviour.

Since M2 the reply is produced by the agent: a model picks tool calls, the policy
gate checks them against the same caps the contract enforces, and `reply` comes back
already speakable. With no model key configured the server uses a deterministic
rule-based model, so the endpoint behaves and tests identically without a key.

`/v1/voice` is one utterance per request and keeps no memory between calls: a
question the answer depends on has to arrive with it. The Telegram door does keep
the last few turns of each chat (see `POST /v1/tg/webhook`), because a chat is a
conversation and a bare "500" there is only an amount while the question that
asked for it is still in front of the model.

**The wake gate is server-side.** If the transcript does not look like it was aimed
at Stark, the response is `{"ignored": true, "reply": null}` and the client must stay
silent. Do not play anything on `ignored: true`.

The rule tolerates what recognizers do to the wake word — see `wake.py` in
`apps/backend`, one implementation shared with the Telegram voice path:

- `stark` (or `hey stark`) **anywhere** in the transcript passes untouched, minus a
  noun said with it: "stark ai what is left" reaches the agent as "stark what is
  left", because "ai" is part of the name rather than the first word of the
  question.
- A **wake attempt at the opening** — `start`, `stock`, `starn`, `stop`, `starky`,
  `starquad`, or anything within two edits of "stark" — sitting in the first few
  tokens **behind filler** (`hey`, `um`, `so`, …) is rewritten as `Stark, …` with the
  misheard token dropped, so "um start what's my light bill" reaches the agent as
  "Stark, what's my light bill".
- A name the recognizer **split across two or three tokens** — `star quad`, `star k`,
  `st ar k`, `sto p` — is joined and treated the same way, so neither half leaks
  into the question.
- It has to open with the address: "I start the car" is not a wake word. The cost of
  the tolerance is that a handful of ordinary openings (`start the car`, `state of
  the grid`) also count as addressed; the agent still will not pay without an
  instruction.
- Everything else is `ignored`, because a gate that fires on every sentence is not
  a gate. `transcript` in the response always echoes what was actually said, not
  the rewritten form.

`reply` is already speakable text. When `audio` is present, play it instead — it *is*
this reply, spoken. Only fall back to your own TTS for `audio: null`.

### `POST /v1/speak`

**Additive** (2026-10-23). Speak text the client already has — normally the `reply`
of an answered `/v1/voice`.

```json
{ "text": "You've got ₦64,200 in your wallet…" }
```

```json
{ "audio": "data:audio/wav;base64,UklGR…" }
```

`audio` is a WAV data URL, or `null` when voice is off — **200 either way** (voice is
an enhancement, never an error). Missing/empty `text`, or more than **2,000
characters**, is **400 `bad_text`**. Each call counts toward the account's speak limit
(`STARK_SPEAK_PER_MINUTE`, default 30 a minute): over it is **429 `rate_limited`**.

### `POST /v1/speak/ticket`

**Additive** (2026-11-12). A link for an `<audio>` element, which cannot send
`Authorization`. Same body and `bad_text` rules as `POST /v1/speak`:

```json
{ "text": "Your light bill is 5,000 naira." }
```

```json
{ "url": "/v1/speak/stream?ticket=3q2-7wQ…", "expires_in_seconds": 120 }
```

`url` is relative to the API's base URL. The ticket opens only
`GET /v1/speak/stream`, only for this text, for two minutes; the text stays on the
server, so neither it nor the session token travels in a URL. It may be fetched more
than once while it lives (browsers re-request an `src`). Counts toward the speak limit.

### `GET /v1/speak/stream`

**Additive** (2026-10-24). The same voice, sent as it is produced, for a player that
can start on partial data. **Changed 2026-11-12:** it takes only a ticket from
`POST /v1/speak/ticket` — no `?text=`, no `?token=`, no `Authorization`:

```
GET /v1/speak/stream?ticket=3q2-7wQ…
```

- **200**, `Content-Type: audio/mpeg` when streaming (no `Content-Length` — the body
  is deliberately not buffered), `audio/wav` when a whole buffered clip is substituted.
- **401 `unauthorized`** for an unknown or expired ticket, **429 `rate_limited`**
  when the account is over its speak limit (every fetch counts), **503 `no_voice`** (JSON) when no provider is
  configured at all, so a client expecting audio can tell "quiet" from "refused".
- Measured 2026-10-24: first byte **~0.5s**, whole clip ~1.0s, against **~1.3s** for
  the buffered `POST /v1/speak` before a single sample could play.

`POST /v1/speak` remains the simple contract — Telegram and anything that needs one
complete `data:` URL should keep using it. The dashboard fetches a ticket, plays this
stream and falls back to `POST /v1/speak` if it errors.

### `POST /v1/telemetry`

From the AC meter bridge. Returns **202**.

```json
{ "device_id": "ac-plug-1", "watts": 1480 }
```

Stored per account, and stamped with the **server's** clock when it arrives: a `ts`
in the body is ignored (2026-10-27), because `units_left` and `days_left` are worked
out from the gaps between readings, and a wrong device clock would move the meter.
Post each sample as it is taken. `watts` must be a number of 0 or more (`bad_watts`).
At most `STARK_TELEMETRY_PER_MINUTE` readings (default 120) a minute per account;
beyond that **429 `rate_limited`** (2026-11-12).
**It feeds `/v1/suggestions`** (2026-10-24):
the `load_imbalance` line needs two or more `device_id`s in the last 24 hours, and
reads each device's **average** watts — ten samples of one plug are one habit, not
ten air conditioners. One device alone can never trigger it, by design.

### `POST /v1/tg/webhook`

Telegram's update push (M4). **The frontend does not call this** — Telegram does.
Documented so nobody exposes it or is surprised by it.

Every request must carry `X-Telegram-Bot-Api-Secret-Token` matching
`TELEGRAM_WEBHOOK_SECRET`; otherwise **401** with `webhook_unconfigured` (no
secrets set on the server) or `webhook_unverified` (wrong/missing header). It is
checked in constant time **before the body is parsed**, and the bot refuses
everything while unconfigured — there is no "open webhook" mode.

A verified update returns 200:

```json
{ "ok": true, "handled": "agent", "update_id": 918273645 }
```

`handled` is for debugging, not display: `agent` (the user asked something),
`command` (`/link`, `/whoami`, `/unlink`, `/help`), `unlinked` (linking
instructions only — the agent was never called), `asleep` (a voice note without
the word "stark"), `voice_unheard` (no STT configured), `duplicate` (a
re-delivered update — processed once), or `ignored`.

How a linked user talks to the bot: send `link 482913` (the code comes from the
app) to bind the chat, then ask in plain text or as a voice note. Voice notes go
through the same wake rule as `/v1/voice`: no "stark", no answer. Typed messages
in the DM skip it — you already know who you are talking to.

**A chat has a memory (2026-10-25).** Each chat keeps its last six exchanges,
dropped after ten minutes of silence, and they go in front of the new message.
Without it every line was answered cold, so an answer split across two messages
could never complete: measured 2026-10-25, "top up my airtime" → "how much?" →
"500" → "which bill would you like to pay 500 for?", round and round, while the
same bare "500" on a cold turn paid the *electricity* bill. Memory is keyed by
chat id, so two chats never see each other's turns, and it lives in the process —
a restart starts a new conversation. `/v1/voice` stays one-shot.

Errors: `webhook_unconfigured` (401), `webhook_unverified` (401),
`bad_update` (400, body is not JSON).

### `POST /v1/link/code`

**Additive (2026-10-25).** The app half of identity linking: mints one
single-use code that binds a chat to this account. Before this existed, only
tests could mint a code, so every `/link` in a real chat was refused.

The server stores a hash of the code, never the code itself, so this response is
the only time it is readable.

```json
{
  "code": "491804",
  "channel": "telegram",
  "expires_in": 600,
  "bot_username": "hellostarkai_bot",
  "deep_link": "https://t.me/hellostarkai_bot?start=491804",
  "user_id": "user_tunde"
}
```

`deep_link` is `null` when the server has no `TELEGRAM_BOT_TOKEN` or Telegram
was unreachable — the code still works, typed by hand as `link 491804`. The
code expires after `expires_in` seconds (10 minutes), is single-use, and a chat
gets five redeem attempts before it is locked out. Redeeming it links the chat
(`/start <code>` from the deep link, or `/link <code>` typed); an already-linked
chat is never rebound and must `/unlink` first.

No request body. Errors: none specific — a failure to reach Telegram degrades to
`deep_link: null` rather than an error, because the code is the part that
matters.

### `GET /v1/turnlog`

**Debug route, not part of the product contract** (2026-10-24). The
conversation log, readable from outside the box — because "why did it say
that" is unanswerable from the reply alone.

**Operator only** (2026-11-12): send `X-Stark-Admin-Key`, like the admin routes;
a user session is refused (401, or 403 `admin_disabled` with no key configured).
The log is one file for every account, and until this change any signed-in
user could read everyone's turns.

```json
{
  "enabled": true,
  "count": 1,
  "entries": [
    {
      "kind": "turn",
      "ts": "2026-10-24T21:40:11.512Z",
      "outcome": "answered",
      "heard": "hey stark whats my balance",
      "said": "whats my balance",
      "reply": "Your current balance is ₦64,200.",
      "actions": ["get_state"],
      "model": "google/gemini-2.5-flash-lite",
      "ms": { "total": 1450, "agent": 1380 },
      "conversation": [
        { "role": "system", "content": "You are Stark … Current account: {…}" },
        { "role": "user", "content": "whats my balance" },
        { "role": "assistant", "content": "Your current balance is ₦64,200." }
      ]
    }
  ]
}
```

`conversation` is the whole exchange with the model: prompt and account
snapshot first, then every user, assistant and tool message in order. It is
present only on turns that reached the agent — `asleep` and `unheard` turns
have no `conversation` key at all. `kind: "speak"` entries record synthesis
text and timings instead.

`channel` says which door the turn came through — `voice` or `telegram`
(**additive, 2026-10-25**). Telegram turns were not logged at all before that:
the first real conversation on the bot read back as `count: 0`, and the only way
to see what it heard was to replay it locally.

`account_id` says whose turn it was (**additive, 2026-11-12**; absent on older
entries and on `kind: "speak"` lines). `?account=<id>` keeps only that
account's turns.

`?limit=N` keeps the newest N entries (default **100**); `?limit=0` returns the
whole file. A value that is not a number falls back to the default.

**404 `turnlog_off`** while `STARK_TURN_LOG` is unset — off in every local run,
set only on the deployed API. The file itself is
`apps/backend/logs/turns/turns.jsonl` (gitignored). No secret is ever written
into it, but it does contain what people said: treat it as user data.

### `POST /v1/_stub/reset`

**Stub only — not part of the product contract, and off by default.** It exists
only when the server runs with `STARK_STUB_RESET=1`; otherwise it answers **404**
`no_route` like any unknown route. When on, it replaces the caller's data with the
artboard seed so smoke runs are repeatable: the three seed bills, limits
`₦30,000` / `₦10,000`, balance `₦64,200`, spent `₦23,000`, the six seed activity rows
(their 110 delivered units become `units_left`), and no readings. New accounts are
**not** seeded: they open with no bills, ₦0 and no activity.

---

## What is stubbed vs real

| Piece | Stub today | Real in |
|---|---|---|
| Auth | none | M4 |
| Balances | per account, starts at ₦0. **Flutterwave** (bank transfer, card, USSD) and **NEAR Intents** (any chain) deposits credit it; test money only while neither is configured | live once `FLW_SECRET_KEY` + `STARK_APP_URL` / `STARK_TREASURY_NEAR_ACCOUNT` are set — **no real deposit has run yet** |
| Withdrawals | Flutterwave transfers, money held at request | live once Flutterwave is keyed and the server IP is whitelisted — **never run against Flutterwave** |
| Payments | every path checks Stark's Flutterwave balance, then signs `pay` on the user's own vault (`tx_hash`); a vendor failure refunds the vault | dry-signed by default; broadcast with `STARK_BROADCAST=1` — **per-user vaults have never been created on testnet** |
| Token | **vended through Flutterwave bills**; a `FLWSECK_TEST-` key uses Flutterwave's test environment | **blocked on IP whitelisting, so no bill has been bought yet** |
| Voice | **real** — Whisper hears the clip; `transcript_hint` remains a probe | M4a done. Voice notes in Telegram and the browser both work |
| Suggestions | **computed** from meter, telemetry, delivered receipts and renewals; empty when the data is not there | M6 (the AC sensor makes `load_imbalance` routine rather than demo data) |
| Persistence | **Neon Postgres**: accounts, wallets, receipts, bills, limits, readings and channel identities, scoped per account, consistent across restarts | M3 + auth |

Shapes will not change as these land. Only the values become real.

---

## Changelog

| Date | Change |
|---|---|
| 2026-10-20 | v1 frozen. Stub implemented and smoke-tested (27 checks). |
| 2026-10-22 | M2: `/v1/voice` runs the agent loop. Additive fields `actions` and `tx_hash`. No shape changes. |
| 2026-10-22 | M3: `Receipt` gains `status` and `request_id`; new error `vendor_failed` (502). Receipts and wallet persist in SQLite. No shape changes. |
| 2026-10-22 | Product breadth: airtime, data and TV vend through confirmed VTpass services. `Bill` gains `plan` and `plan_price_ngn`. Per-payment cap 5,000 → 10,000 (a DStv bouquet is 7,900). |
| 2026-10-22 | Additive endpoints for the design's screens: `GET /v1/plans`, `POST`/`PATCH`/`DELETE /v1/bills`, `GET`/`PATCH /v1/limits`, `GET /v1/wallet`, `POST /v1/wallet/topup`, `POST /v1/wallet/withdraw`. New codes `over_per_payment_cap`, `bad_kind`, `bad_reference`, `bad_bill`, `unsupported_product`, `plan_required`, `unknown_plan`, `duplicate_bill`, `bill_in_flight`, `bad_limits`. `Receipt.type` gains `withdrawal`. No existing shape changed. |
| 2026-10-24 | Reminders, real suggestions, real audio in. `Bill` gains `renews_on`; `/v1/state` gains `due_soon`; `PATCH /v1/bills` accepts and clears `renews_on`; `/v1/suggestions` computed from state instead of seeded copy; `/v1/voice` accepts base64/multipart `audio` and returns `stt`. New codes `bad_renews_on`, `bad_audio`, `audio_too_large`. `GET /v1/speak/stream` added. No existing shape changed. |
| 2026-10-24 | Debug route added: `GET /v1/turnlog` reads the conversation log back (404 `turnlog_off` when the log is off), and a logged turn gains `conversation` — the full message exchange with the model. No existing shape changed. |
| 2026-10-25 | `POST /v1/link/code` added: a single-use, 10-minute code plus the bot's `t.me` deep link, so a chat can be linked from the app. `/start <code>` now redeems it too. No existing shape changed. |
| 2026-11-12 | `GET /v1/turnlog` needs `X-Stark-Admin-Key` and no longer accepts a user session. Turns gain `account_id`, and `?account=` filters on it. |
| 2026-10-25 | Telegram chats keep their last six exchanges (ten-minute idle expiry) and Telegram turns are written to `/v1/turnlog` with `channel: "telegram"`. `/v1/voice` is unchanged: one turn per request. Additive only. |
| 2026-10-26 | **Auth enforced + storage moved.** Every `/v1` route except the Telegram webhook needs `Authorization: Bearer <token>` from Neon Auth, else **401 `unauthorized`** (`GET /v1/speak/stream` also takes `?token=`); `POST /v1/auth/logout` added. Receipts, wallets, accounts and channel identities now live in Neon Postgres instead of SQLite, scoped per account — two sign-ins no longer share a wallet. New code `unauthorized`. No response shape changed. |
| 2026-10-27 | No mock data for real accounts. New accounts open empty (no bills, ₦0, no activity). Bills, limits and readings are stored per account. `units_left`/`days_left` computed from top-ups and readings; `/v1/telemetry` ignores a client `ts`. Top-ups are labelled test money; `POST /v1/wallet/withdraw` answers 501 `not_available`. `POST /v1/_stub/reset` is off unless `STARK_STUB_RESET=1`. No shape changed. |
| 2026-10-27 | **Backend on FastAPI**, organised per feature module (controller, service, DTOs); Swagger UI at `/docs`. Every shape and code is unchanged. Request bodies are JSON (as every client already sends) except `/v1/voice`, which still takes multipart; a body that is not JSON is `400 bad_request`. `PATCH /v1/bills` `renews_on: null` now clears the date as documented. `POST /v1/link/code` answers `409 not_configured` instead of a 500 when the bot has no owner account. |
| 2026-11-03 | Pause: `GET /v1/controls`, `POST /v1/controls/pause`, `POST /v1/controls/resume`; `/v1/state` gains `paused`; new code `paused` (423), checked before every other payment rule. Telegram gains `/pause` and `/resume`. Additive only. |
| 2026-11-03 | Approvals: `GET /v1/approvals`, `POST /v1/approvals/{id}/approve`, `POST /v1/approvals/{id}/deny`; `/v1/limits` gains `approval_window_minutes` (also patchable); `Receipt` gains `reason` for `declined` entries, which the agent now writes for refusals. New codes `unknown_request`, `request_closed`. Additive only. |
| 2026-11-03 | `GET /v1/demo`: a public, read-only sample account (no auth). Additive only. |
| 2026-11-03 | `GET /v1/payees`: each saved bill with its delivered totals (this month, all time, count). Additive only. |
| 2026-11-03 | **Money flow.** Deposits: `GET /v1/wallet/methods`, `POST`/`GET /v1/wallet/deposits`, `GET /v1/wallet/deposits/{id}`, `POST /v1/wallet/deposits/{id}/tx`, `GET /v1/wallet/crypto-assets`. Withdrawals: `GET /v1/wallet/banks`, `POST /v1/wallet/bank-accounts/resolve`, `GET /v1/wallet/withdrawals`; `POST /v1/wallet/withdraw` now takes `bank_code` + `account_number` and returns a `Withdrawal` instead of 501. `POST /v1/bachs/webhook`. `POST /v1/wallet/topup` answers 501 once Bachs is configured. Payments gain `float_low` (503) and `authorisation_failed` (502); `tx_hash` is set on every path when a chain is configured. New codes `unknown_deposit`, `bad_method`, `bad_asset`, `bad_tx`, `bad_account`, `provider_failed`. |
| 2026-11-03 | **One provider: Flutterwave.** Bachs and VTpass are gone. Deposits are Flutterwave checkout, bills are Flutterwave bill payments, withdrawals are Flutterwave transfers, all from one NGN balance. `POST /v1/bachs/webhook` → `POST /v1/flutterwave/webhook` (`verif-hash`). Plan codes are Flutterwave item codes (`MD107`, `CB141`) and `GET /v1/plans` providers are network names (`MTN`, `DSTV`). A bank `Withdrawal` starts `sending` instead of `reviewing`. Showmax is no longer sold. |
| 2026-11-12 | Security fixes. A bill the agent saves carries `needs_confirmation: true` and cannot be paid (409 `bill_unconfirmed`) until the owner calls `POST /v1/bills/{id}/confirm`. Test money is off whenever the crypto treasury is configured, and crypto withdrawals are off while Flutterwave runs on a test key. |
| 2026-11-03 | Crypto withdrawals: `POST /v1/wallet/withdraw/crypto`. `Withdrawal` gains `method` and `crypto` (null for bank), and `status` gains `sending`; `/v1/wallet/methods` gains `withdraw`. New codes `bad_address`, `over_limit`, `daily_limit`. Additive only. |
| 2026-11-11 | `GET /v1/wallet/rates`: the live naira/USDC deposit and withdrawal rates. Crypto rates now follow Paycrest instead of a fixed `STARK_USDC_NGN_RATE`. Additive only. |
| 2026-11-11 | `POST /v1/wallet/deposits/preview`: a dry crypto deposit quote from either side. New code `below_minimum` (400), also on `POST /v1/wallet/deposits`, in place of `provider_failed` when 1Click's swap floor is the reason. |
| 2026-11-12 | **API surface hardening.** The session token is read only from `Authorization: Bearer`; `?token=` is refused on every route. `GET /v1/speak/stream` now takes only `?ticket=` from the new `POST /v1/speak/ticket` (`?text=` and `?token=` are gone). `/v1/speak` and `/v1/speak/ticket` refuse `text` over 2,000 characters (`bad_text`); `/v1/voice` refuses a body over 12 MB (`audio_too_large`) while reading it. New code `rate_limited` (429) on speak routes and `/v1/telemetry`. Bill `label` (40) and `provider` (48) are length- and charset-checked (`bad_bill`). `/docs`, `/redoc` and the spec are served only with `STARK_DOCS=1`, and `GET /` no longer lists routes. The agent pays only an amount the user said (`amount_mismatch` on its reply `code`) and strips web links from its reply text. |
| 2026-11-11 | `GET /v1/admin/overview` behind `X-Stark-Admin-Key` (`STARK_ADMIN_KEY`): both pots, coverage, and deposits and withdrawals by status. New code `admin_disabled` (403). Additive only. |
