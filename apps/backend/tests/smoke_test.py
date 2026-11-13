#!/usr/bin/env python3
"""Smoke test for the Stark API stub. Zero dependencies.

Start the server first:  STARK_STUB_RESET=1 python3 server.py
Then:                    python3 smoke_test.py

`STARK_STUB_RESET=1` switches on `/v1/_stub/reset`, which the run uses to start
from the artboard's seed. A deployed API leaves it off, and answers it with 404.

Exits 0 if every check passes, 1 otherwise. Order matters: the payment
checks mutate in-memory state, so run it against a freshly started server.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message

from app.database import neon

BASE = os.environ.get("STARK_SMOKE_BASE", "http://127.0.0.1:8000").rstrip("/")
failures: list[str] = []
checks = 0

# Accounts are real now, so the smoke run needs one. It signs itself in against
# Neon Auth and carries the bearer token on every call below; the account is a
# fixed demo one so repeated runs reuse it instead of littering the project.
AUTH_BASE = (os.environ.get("NEON_AUTH_BASE_URL")
             or neon.read_env_value("NEON_AUTH_BASE_URL") or "").rstrip("/")
SMOKE_EMAIL = os.environ.get("STARK_SMOKE_EMAIL", "smoke.run@example.com")
SMOKE_PASSWORD = os.environ.get("STARK_SMOKE_PASSWORD", "SmokeDemo2026!")


def _auth_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        AUTH_BASE + path,
        data=json.dumps(body).encode(),
        method="POST",
        # Neon Auth refuses a request with no Origin: the browser always sends one,
        # and without it the provider cannot tell which site asked.
        headers={"Content-Type": "application/json", "Origin": "http://localhost:5174"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def _sign_in() -> str:
    """Create the smoke account on first run, then sign in. Returns the token."""
    if not AUTH_BASE:
        raise SystemExit("NEON_AUTH_BASE_URL is not set (apps/backend/.env).")
    try:
        session = _auth_post("/sign-up/email", {
            "email": SMOKE_EMAIL, "password": SMOKE_PASSWORD, "name": "Smoke Test",
        })
    except urllib.error.HTTPError:
        # Already registered from a previous run — or the password changed.
        session = _auth_post("/sign-in/email", {
            "email": SMOKE_EMAIL, "password": SMOKE_PASSWORD,
        })
    token = session.get("token")
    if not token:
        raise SystemExit(f"Could not sign in as {SMOKE_EMAIL}: {session}")
    return token


TOKEN = _sign_in()


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list, Message]:
    data = json.dumps(body).encode() if body is not None else None
    # A browser always sends Origin cross-site, and CORS headers answer it.
    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": "http://localhost:5174"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        # 30s: a /v1/voice reply can be a live LLM turn (or two) plus a
        # spoken reply on top. Genuine failures refuse instantly anyway —
        # this ceiling only guards against a hang.
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null"), resp.headers
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, (json.loads(raw) if raw else {}), err.headers


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}{(' — ' + detail) if detail else ''}")
        failures.append(name)


print("Stark API stub — smoke test\n")

# Make the run repeatable regardless of prior payments.
call("POST", "/v1/_stub/reset")

# --- read endpoints ---------------------------------------------------------
status, index, _ = call("GET", "/")
check("GET / names the service, not its routes",
      status == 200 and index.get("service") == "stark-api" and "routes" not in index,
      f"status={status}")

status, health, _ = call("GET", "/health")
check("GET /health ok", status == 200 and health.get("status") == "ok", f"status={status}")

status, st, _ = call("GET", "/v1/state")
check("GET /v1/state 200", status == 200, f"status={status}")
check("state balance is 64200", st.get("balance_ngn") == 64200, str(st.get("balance_ngn")))
check("state cap is 30000", st.get("cap_ngn") == 30000, str(st.get("cap_ngn")))
check("state has 3 bills", len(st.get("bills", [])) == 3, str(len(st.get("bills", []))))

# Reminders: the DStv bill renews inside the window (seeded 3 days out), and
# state carries it so the agent's snapshot and the dashboard both see it.
due = st.get("due_soon", [])
check("state due_soon carries the DStv renewal",
      len(due) == 1 and due[0].get("id") == "bill_dstv"
      and due[0].get("days_until") == 3 and (due[0].get("price_ngn") or 0) > 0,
      str(due))

status, bills, _ = call("GET", "/v1/bills")
check("GET /v1/bills 200", status == 200 and len(bills) == 3, f"status={status}")

status, bill, _ = call("GET", "/v1/bills/bill_home_meter")
check("bill detail is electricity", status == 200 and bill.get("kind") == "electricity")

status, missing, _ = call("GET", "/v1/bills/nope")
check("unknown bill -> 404 unknown_bill",
      status == 404 and missing.get("code") == "unknown_bill", f"status={status}")

# --- plans, add/remove bill ------------------------------------------------
status, plans, _ = call("GET", "/v1/plans?kind=tv")
check("GET /v1/plans 200", status == 200 and len(plans) > 1, f"status={status}")
# Prices come from Flutterwave's live catalogue, so the test takes two of its plans.
dstv = [p for p in plans if p.get("provider") == "DSTV"] or plans
first, second = dstv[0], (dstv[1] if len(dstv) > 1 else plans[1])

# A picker's provider chip says "MTN" / "mtn"; the data biller is found loosely.
status, mtn, _ = call("GET", "/v1/plans?kind=data&provider=mtn")
check("plans provider filter is loose",
      status == 200 and len(mtn) > 0 and all(p.get("provider") == "MTN" for p in mtn),
      f"status={status} n={len(mtn)}")

new_bill = {"kind": "tv", "provider": first["provider"], "label": "Test TV",
            "reference": "9998887776", "plan": first["plan"]}
status, added, _ = call("POST", "/v1/bills", new_bill)
check("POST /v1/bills 201", status == 201, f"status={status} {added}")
check("added bill carries plan price",
      added.get("plan_price_ngn") == first["price_ngn"], str(added))
status, dup, _ = call("POST", "/v1/bills", new_bill)
check("duplicate bill -> 409",
      status == 409 and dup.get("code") == "duplicate_bill",
      f"status={status} {dup.get('code')}")
if second["provider"] == first["provider"]:
    status, patched, _ = call("PATCH", f"/v1/bills/{added.get('id')}",
                              {"plan": second["plan"]})
    check("PATCH plan takes the new price",
          status == 200 and patched.get("plan_price_ngn") == second["price_ngn"],
          f"status={status} {patched}")
status, deleted, _ = call("DELETE", f"/v1/bills/{added.get('id')}")
check("DELETE bill -> 200",
      status == 200 and deleted.get("deleted") is True, f"status={status} {deleted}")
status, gone, _ = call("GET", f"/v1/bills/{added.get('id')}")
check("deleted bill -> 404",
      status == 404 and gone.get("code") == "unknown_bill", f"status={status}")

# Suggestions are computed now (suggestions.py): the DStv renewal comes from live
# state and the old hardcoded "AC is 78%" line is gone.
#
# The meter line is deliberately *not* asserted to be present. `units_left` and
# `days_left` are derived (telemetry.meter.reading) rather than seeded, so with
# no readings yet the seed's 110 units read as ~21 days of runway, and
# `_units_item` returns None because a full meter is not news — the same rule
# tests.test_suggestions pins as `test_a_meter_far_from_empty_is_not_news`.
# Asserting `sug_units` here was asserting the old in-memory seed, and it rotted
# the day the meter became computed. What must still hold is that any units line
# that does appear is a real one, with a reason we actually compute.
status, sugg, _ = call("GET", "/v1/suggestions")
sug_text = " ".join(s.get("text", "") for s in sugg)
units_lines = [s for s in sugg if s.get("id") == "sug_units"]
check("suggestions computed from state",
      status == 200 and any(s.get("reason") == "bill_due" for s in sugg)
      and "78%" not in sug_text
      and all(s.get("reason") in ("units_low", "units_low_estimate")
              for s in units_lines),
      f"status={status} {[s.get('id') for s in sugg]}")

# --- renews_on --------------------------------------------------------------
status, patched, _ = call("PATCH", "/v1/bills/bill_dstv", {"renews_on": "2026-11-05"})
check("PATCH renews_on sets a date",
      status == 200 and patched.get("renews_on") == "2026-11-05", f"status={status}")
status, bad_date, _ = call("PATCH", "/v1/bills/bill_dstv", {"renews_on": "whenever"})
check("PATCH renews_on rejects nonsense -> 400 bad_renews_on",
      status == 400 and bad_date.get("code") == "bad_renews_on", f"status={status}")
status, cleared, _ = call("PATCH", "/v1/bills/bill_dstv", {"renews_on": ""})
check("PATCH renews_on clears with an empty string",
      status == 200 and "renews_on" not in cleared, f"status={status} {cleared}")
status, gone_due, _ = call("GET", "/v1/state")
check("a cleared renewal leaves due_soon", gone_due.get("due_soon") == [],
      str(gone_due.get("due_soon")))
call("PATCH", "/v1/bills/bill_dstv", {"renews_on": "2099-01-01"})   # far future: not due
status, back, _ = call("GET", "/v1/state")
check("a far-future renewal is not due", back.get("due_soon") == [],
      str(back.get("due_soon")))
call("POST", "/v1/_stub/reset")                                       # restore the seed

status, activity, _ = call("GET", "/v1/activity")
check("activity seeded with 6", status == 200 and len(activity) == 6, f"status={status}")

# --- payments ---------------------------------------------------------------
status, receipt, _ = call("POST", "/v1/payments",
                          {"bill_id": "bill_home_meter", "amount_ngn": 5000})
check("pay 5000 -> 201", status == 201, f"status={status}")
check("receipt has token", bool(receipt.get("token")), str(receipt))
check("units = 5000 / 209", receipt.get("units") == 23.92, str(receipt.get("units")))

status, st2, _ = call("GET", "/v1/state")
check("balance dropped to 59200", st2.get("balance_ngn") == 59200, str(st2.get("balance_ngn")))
check("spent rose to 28000", st2.get("spent_ngn") == 28000, str(st2.get("spent_ngn")))

home = next((b for b in st2.get("bills", []) if b.get("id") == "bill_home_meter"), {})
check("bill last amount updated", home.get("last_amount_ngn") == 5000, str(home))
check("bill last units updated", home.get("last_units") == 23.92, str(home.get("last_units")))
check("bill last paid updated", home.get("last_paid_at") == receipt.get("created_at"),
      str(home.get("last_paid_at")))
# Units left are worked out from delivered top-ups minus measured use: the seed's
# 23.9 + 47.8 + 38.3 and this 23.92, with no readings yet after the reset.
check("units left rose to 133.92", st2.get("units_left") == 133.92, str(st2.get("units_left")))

status, _, _ = call("POST", "/v1/payments", {"bill_id": "bill_home_meter", "amount_ngn": 1000})
check("second pay 1000 -> 201", status == 201, f"status={status}")

status, over, _ = call("POST", "/v1/payments",
                       {"bill_id": "bill_home_meter", "amount_ngn": 20000})
check("over per-payment -> 409 over_per_payment_cap",
      status == 409 and over.get("code") == "over_per_payment_cap",
      f"status={status} {over.get('code')}")
check("over per-payment states cap",
      over.get("detail", {}).get("cap_ngn") == 10000, str(over.get("detail")))

status, over, _ = call("POST", "/v1/payments",
                       {"bill_id": "bill_home_meter", "amount_ngn": 2000})
check("over cap -> 409 over_cap",
      status == 409 and over.get("code") == "over_cap", f"status={status} {over.get('code')}")
check("over_cap states remaining", over.get("detail", {}).get("remaining_ngn") == 1000,
      str(over.get("detail")))

status, bad, _ = call("POST", "/v1/payments", {"bill_id": "bill_nope", "amount_ngn": 1000})
check("unknown bill payment -> 404", status == 404 and bad.get("code") == "unknown_bill")

status, zero, _ = call("POST", "/v1/payments", {"bill_id": "bill_home_meter", "amount_ngn": 0})
check("zero amount -> 400 bad_amount",
      status == 400 and zero.get("code") == "bad_amount", f"status={status}")

# The agent's default top-up is ₦5,000; reset so it still fits the monthly cap.
call("POST", "/v1/_stub/reset")

# --- voice ------------------------------------------------------------------
status, answer, _ = call("POST", "/v1/voice", {"transcript_hint": "hello stark what's my light bill"})
# Phrasing-independent: a live model words this differently every time, and
# since 2026-10-24 the account comes in the prompt as a snapshot, so `get_state`
# need not be in `actions` any more. What must still hold is that the answer is
# *grounded*: every number it says is a number the state holds. A reply with no
# number at all passes — inventing one is the failure this catches.
status, st, _ = call("GET", "/v1/state")
state_text = json.dumps(st)
spoken = re.findall(r"\d[\d,]*(?:\.\d+)?", answer.get("reply") or "")
grounded = all(d.replace(",", "") in state_text for d in spoken)
check("voice query answers from state",
      status == 200 and bool(answer.get("reply")) and grounded,
      f"{answer.get('actions')} {(answer.get('reply') or '')[:60]}")

# Real audio in (M4 finish): the clip goes up as base64, the server hears it
# with Whisper. Garbage bytes must never 500 and never be answered as if
# understood — the reply either explains the miss or asks for the words again.
import base64                                       # noqa: E402 - section-local

garbage = base64.b64encode(b"this is not audio at all").decode()
status, unheard, _ = call("POST", "/v1/voice",
                         {"audio": garbage, "audio_type": "audio/webm",
                          "speak": False})
check("voice hears a clip or says why it cannot",
      status == 200 and unheard.get("stt") in ("ok", "failed", "no_key")
      and isinstance(unheard.get("reply"), str) and bool(unheard.get("reply")),
      f"status={status} stt={unheard.get('stt')} {unheard.get('reply')}")
check("an unheard clip carries no fabricated transcript",
      unheard.get("stt") == "ok" or unheard.get("transcript") == "",
      str(unheard.get("transcript")))

status, bad_audio, _ = call("POST", "/v1/voice", {"audio": "!!! not base64 !!!"})
check("bad base64 -> 400 bad_audio",
      status == 400 and bad_audio.get("code") == "bad_audio", f"status={status}")

status, ig, _ = call("POST", "/v1/voice", {"transcript_hint": "what time is it"})
# Two halves of one gate (wake.py): plain speech stays silent, and a wake word
# the recognizer wrote as "start" is still an address — the half that used to
# fail for anyone whose "stark" came back as "start", "stock" or "starn".
near_status, near, _ = call("POST", "/v1/voice",
                            {"transcript_hint": "start what's my light bill",
                             "speak": False})
check("wake gate ignores plain speech and accepts a misheard wake word",
      status == 200 and ig.get("ignored") is True
      and near_status == 200 and near.get("ignored") is False
      and bool(near.get("reply")),
      f"ignored={ig.get('ignored')} near={near.get('ignored')} {near.get('reply')}")

# The canonical pay phrase (the same one /help advertises): unambiguous for a
# live LLM, which asks a clarifying question on vaguer input — correct product
# behaviour, but this check exists to prove the pay path fires.
status, pay, _ = call("POST", "/v1/voice",
                     {"transcript_hint": "hello stark pay 5000 for electricity",
                      "speak": False})
check("voice pay returns token", status == 200 and bool(pay.get("token")),
      str(pay.get("reply"))[:80])

# The reply comes back spoken when ElevenLabs is keyed (ELEVENLABS_API_KEY), and
# the additive `audio` field is present either way — null when voice is off.
audio_field = answer.get("audio", "missing")
check("voice reply carries audio field", audio_field != "missing")
check("audio is a WAV data URL or null",
      audio_field is None or (
          isinstance(audio_field, str)
          and audio_field.startswith("data:audio/wav;base64,")
      ), str(audio_field)[:60])
if isinstance(audio_field, str) and audio_field.startswith("data:audio/wav;base64,"):
    spoken = base64.b64decode(audio_field.split(",", 1)[1])
    check("spoken audio decodes to a real WAV",
          spoken[:4] == b"RIFF" and len(spoken) > 1000, f"len={len(spoken)}")
check("ignored reply never carries audio", ig.get("audio") is None, str(ig.get("audio"))[:40])

# Text-first path: the dashboard asks for words only (speak: false), then
# fetches the voice from /v1/speak — reading never waits on synthesis.
status, fast, _ = call("POST", "/v1/voice",
                      {"transcript_hint": "hello stark what is my light bill",
                       "speak": False})
check("speak:false answers text without audio",
      status == 200 and fast.get("audio") is None and bool(fast.get("reply")),
      str(fast.get("audio"))[:40])

status, spoken, _ = call("POST", "/v1/speak", {"text": "hello stark, your meter is fine"})
check("POST /v1/speak answers with the audio field",
      status == 200 and "audio" in spoken, f"status={status}")
speak_audio = spoken.get("audio")
check("speak audio is a WAV data URL or null",
      speak_audio is None or (isinstance(speak_audio, str)
                              and speak_audio.startswith("data:audio/wav;base64,")),
      str(speak_audio)[:60])
if isinstance(speak_audio, str) and speak_audio.startswith("data:audio/wav;base64,"):
    said = base64.b64decode(speak_audio.split(",", 1)[1])
    check("speak audio decodes to a real WAV", said[:4] == b"RIFF" and len(said) > 1000,
          f"len={len(said)}")

status, no_text, _ = call("POST", "/v1/speak", {})
check("POST /v1/speak without text -> 400 bad_text",
      status == 400 and no_text.get("code") == "bad_text", f"status={status}")

# --- streamed voice ---------------------------------------------------------
# Raw, not JSON: the whole point is that the body arrives before it is finished.
# `<audio>` sends no headers, so this one route takes a short-lived ticket, and the
# session token itself is refused there.
status, ticket, _ = call("POST", "/v1/speak/ticket",
                         {"text": "Your light bill is 5,000 naira."})
check("POST /v1/speak/ticket -> a stream URL", status == 200
      and str(ticket.get("url", "")).startswith("/v1/speak/stream?ticket="), f"status={status}")
try:
    urllib.request.urlopen(BASE + "/v1/speak/stream?token=" + urllib.parse.quote(TOKEN),
                           timeout=30)
    t_status = 200
except urllib.error.HTTPError as err:
    t_status = err.code
check("the session token in a query string is refused", t_status == 401, f"status={t_status}")
req = urllib.request.Request(BASE + str(ticket.get("url", "")))
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        s_status, s_type, s_len, s_body = resp.status, resp.headers.get("Content-Type", ""), resp.headers.get("Content-Length"), resp.read()
except urllib.error.HTTPError as err:
    s_status, s_type, s_len, s_body = err.code, err.headers.get("Content-Type", ""), err.headers.get("Content-Length"), err.read()
check("GET /v1/speak/stream is audio, unbuffered, or an honest 503",
      (s_status == 200 and s_type.startswith("audio/") and s_len is None
       and len(s_body) > 1000)
      or (s_status == 503 and b"no_voice" in s_body),
      f"status={s_status} type={s_type} content-length={s_len} len={len(s_body)}")
# The stream handler writes its own body; the dispatcher used to fall through and
# send a 500 JSON body after the audio, corrupting the clip for the player. A
# trailing error is the bug, so assert the tail is audio and nothing else.
check("streamed audio is not followed by an error body",
      s_status != 200 or b"stub_error" not in s_body[-512:],
      str(s_body[-120:]))

# --- limits and wallet ------------------------------------------------------
status, limits, _ = call("GET", "/v1/limits")
check("GET /v1/limits",
      status == 200 and limits.get("monthly_cap_ngn") == 30000
      and limits.get("per_payment_cap_ngn") == 10000, str(limits))
status, limits2, _ = call("PATCH", "/v1/limits",
                          {"monthly_cap_ngn": 40000, "per_payment_cap_ngn": 15000})
check("PATCH /v1/limits",
      status == 200 and limits2.get("monthly_cap_ngn") == 40000
      and limits2.get("per_payment_cap_ngn") == 15000, str(limits2))
status, st3, _ = call("GET", "/v1/state")
check("state cap follows limits", st3.get("cap_ngn") == 40000, str(st3.get("cap_ngn")))

status, wallet, _ = call("GET", "/v1/wallet")
check("GET /v1/wallet",
      status == 200 and wallet.get("added_this_month_ngn") == 20000, str(wallet))
before = int(wallet.get("balance_ngn") or 0)
status, topup, _ = call("POST", "/v1/wallet/topup", {"amount_ngn": 5000})
check("topup credits",
      status == 201 and topup.get("wallet", {}).get("balance_ngn") == before + 5000,
      f"status={status} {topup.get('wallet')}")
check("topup is test money", topup.get("entry", {}).get("source") == "Test money",
      str(topup.get("entry")))
status, withdraw, _ = call("POST", "/v1/wallet/withdraw", {"amount_ngn": 1000})
check("withdraw -> 501 not_available",
      status == 501 and withdraw.get("code") == "not_available",
      f"status={status} {withdraw.get('code')}")
status, wallet_after, _ = call("GET", "/v1/wallet")
check("withdraw took nothing", wallet_after.get("balance_ngn") == before + 5000,
      str(wallet_after.get("balance_ngn")))

# --- telemetry, telegram, cors ---------------------------------------------
status, tel, _ = call("POST", "/v1/telemetry", {"device_id": "ac-plug-1", "watts": 1480})
check("telemetry accepted", status == 202 and tel.get("accepted") is True, f"status={status}")

# The Telegram webhook must refuse an unauthenticated update, whether or not the
# bot is configured — a missing header is 401 in both worlds, so this is testable
# without any secret. (§8A: verify before parsing.)
def raw_call(path: str, body: dict, headers: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, (json.loads(raw) if raw else {})

status, tg = raw_call("/v1/tg/webhook", {"update_id": 42}, {})
check("telegram webhook without secret -> 401",
      status == 401 and tg.get("code") in ("webhook_unconfigured", "webhook_unverified"),
      f"status={status} {tg.get('code')}")
status, tg = raw_call("/v1/tg/webhook", {"update_id": 42},
                      {"X-Telegram-Bot-Api-Secret-Token": "definitely-wrong"})
check("telegram webhook with wrong secret -> 401",
      status == 401 and tg.get("code") in ("webhook_unconfigured", "webhook_unverified"),
      f"status={status} {tg.get('code')}")

status, _, headers = call("GET", "/v1/state")
check("CORS header present", headers.get("Access-Control-Allow-Origin") == "http://localhost:5174",
      str(headers.get("Access-Control-Allow-Origin")))

# Leave the demo seeded even when the run is used interactively.
call("POST", "/v1/_stub/reset")

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("failed: " + ", ".join(failures))
    sys.exit(1)
print("all good")
