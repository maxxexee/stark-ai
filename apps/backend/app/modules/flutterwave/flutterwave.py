"""Flutterwave v3 — the one naira provider. Standard library only.

Every naira movement goes through one Flutterwave account, and they all share its
NGN balance:

| Movement | Endpoint | Notes |
|---|---|---|
| User adds money | `POST /payments` (hosted checkout) | Our deposit id is the `tx_ref`; confirmed with `GET /transactions/verify_by_reference`. |
| User pays a bill | `POST /billers/{biller}/items/{item}/payment` | Our receipt `request_id` is the `reference`; the answer's `tx_ref` is Flutterwave's id, and `GET /bills/{tx_ref}` re-reads it. |
| User withdraws | `POST /accounts/resolve` → `POST /transfers` | Our withdrawal id is the `reference`; `GET /transfers?reference=` says whether it was taken. |
| Treasury view | `GET /balances/NGN` | `available_balance`, whole naira. |
| Bill catalogue | `GET /bill-categories?country=NG` | Every biller and item with its price. |

v3 and not v4: v4 has no bill payments and no hosted checkout.

Amounts on the wire are naira numbers (`5000`, sometimes `"11.0000"`). This
codebase is integer naira, so `whole_naira` drops kobo here and nowhere else.

Webhooks carry `verif-hash`: the secret hash set in the dashboard, sent back as is
(v3 does not sign the body). It is compared in constant time.

Bills and transfers need the server's IP on the dashboard's whitelist, test mode
included; without it they answer `Please enable IP Whitelisting`.

Configuration: `FLW_SECRET_KEY` (`FLWSECK_TEST-…` or `FLWSECK-…`, one host for
both), `FLW_SECRET_HASH`. Unset = Flutterwave is off and the routes that need it
answer 501 `not_available` instead of pretending.
"""

from __future__ import annotations

import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Mapping, Optional

BASE_URL = "https://api.flutterwave.com/v3"
USER_AGENT = "stark-backend/1.0 (+https://hellostark.xyz)"


class FlutterwaveError(Exception):
    """A refusal or failure. `status` is the HTTP status, 0 when unreachable."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message

    @property
    def transient(self) -> bool:
        """Worth trying again with the same reference."""
        return self.status in (0, 429) or self.status >= 500


def whole_naira(amount: object) -> int:
    """`"11.0000"` or `2500.5` → whole naira. Kobo are dropped, never rounded up."""
    return int(Decimal(str(amount)).to_integral_value(rounding=ROUND_DOWN))


@dataclass(frozen=True)
class FlutterwaveClient:
    secret_key: str
    base_url: str = BASE_URL
    timeout: int = 30

    @property
    def test_mode(self) -> bool:
        return "_TEST" in self.secret_key

    # --- deposits ---------------------------------------------------------------

    def create_checkout(self, *, tx_ref: str, amount_ngn: int, email: str, name: str,
                        redirect_url: str, meta: dict[str, str]) -> str:
        """A hosted payment page for one deposit. Returns its link."""
        data = self._request("POST", "/payments", {
            "tx_ref": tx_ref,
            "amount": amount_ngn,
            "currency": "NGN",
            "redirect_url": redirect_url,
            "payment_options": "banktransfer,card,ussd",
            "customer": {"email": email, "name": name},
            "meta": meta,
            "customizations": {"title": "Stark", "description": "Add money to Stark"},
        })
        return data["link"]

    def verify_by_reference(self, tx_ref: str) -> dict[str, Any]:
        """The charge for our `tx_ref`. 400 `No transaction was found` until paid."""
        return self._request("GET", "/transactions/verify_by_reference?"
                             + urllib.parse.urlencode({"tx_ref": tx_ref}))

    # --- bills ------------------------------------------------------------------

    def bill_categories(self) -> list[dict[str, Any]]:
        return self._request("GET", "/bill-categories?country=NG")

    def validate_customer(self, item_code: str, biller_code: str,
                          customer: str) -> dict[str, Any]:
        """Check a meter or smartcard before paying it. Returns the customer's name."""
        return self._request("GET", f"/bill-items/{item_code}/validate?"
                             + urllib.parse.urlencode({"code": biller_code,
                                                       "customer": customer}))

    def pay_bill(self, *, biller_code: str, item_code: str, customer_id: str,
                 amount_ngn: int, reference: str) -> dict[str, Any]:
        """Buy one bill. The answer's `tx_ref` is the only id `bill_status` accepts."""
        return self._request("POST", f"/billers/{biller_code}/items/{item_code}/payment", {
            "country": "NG", "customer_id": customer_id, "amount": amount_ngn,
            "reference": reference,
        })

    def bill_status(self, tx_ref: str) -> dict[str, Any]:
        return self._request("GET", f"/bills/{urllib.parse.quote(tx_ref)}?verbose=1")

    # --- withdrawals ------------------------------------------------------------

    def banks(self) -> list[dict[str, Any]]:
        return self._request("GET", "/banks/NG")

    def resolve_account(self, bank_code: str, account_number: str) -> dict[str, Any]:
        return self._request("POST", "/accounts/resolve", {
            "account_number": account_number, "account_bank": bank_code,
        })

    def create_transfer(self, *, bank_code: str, account_number: str, amount_ngn: int,
                        reference: str, narration: str) -> dict[str, Any]:
        """Send money. Check `find_transfer` first: a lost answer may have gone through."""
        return self._request("POST", "/transfers", {
            "account_bank": bank_code, "account_number": account_number,
            "amount": amount_ngn, "currency": "NGN", "debit_currency": "NGN",
            "reference": reference, "narration": narration,
        })

    def find_transfer(self, reference: str) -> Optional[dict[str, Any]]:
        """The transfer Flutterwave holds under our `reference`, or None."""
        listed = self._request("GET", "/transfers?"
                               + urllib.parse.urlencode({"reference": reference}))
        return next((t for t in listed if t["reference"] == reference), None)

    def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/transfers/{transfer_id}")

    # --- treasury ---------------------------------------------------------------

    def ngn_balance(self) -> int:
        return whole_naira(self._request("GET", "/balances/NGN")["available_balance"])

    # --- plumbing ---------------------------------------------------------------

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        """The response's `data`. Raises `FlutterwaveError` for anything not `success`."""
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode()
        request = urllib.request.Request(self.base_url + path, data=payload, method=method,
                                         headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
            err.close()
        except urllib.error.URLError as err:
            raise FlutterwaveError(0, f"Could not reach Flutterwave: {err.reason}") from err
        try:
            envelope = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise FlutterwaveError(status, f"Flutterwave returned non-JSON (HTTP {status})") \
                from None
        if status >= 400 or envelope.get("status") != "success":
            raise FlutterwaveError(status if status >= 400 else 400,
                                   envelope.get("message") or f"HTTP {status}")
        return envelope["data"]


def client_from_env(env: Optional[Mapping[str, str]] = None) -> Optional[FlutterwaveClient]:
    source = os.environ if env is None else env
    key = (source.get("FLW_SECRET_KEY") or "").strip()
    if not key:
        return None
    if not key.startswith("FLWSECK"):
        raise ValueError("FLW_SECRET_KEY must start with FLWSECK_TEST- or FLWSECK-")
    return FlutterwaveClient(key)


def verify_webhook(headers: Mapping[str, str], secret_hash: str) -> bool:
    """True when `verif-hash` is our secret hash. `headers` must be case-insensitive."""
    sent = headers.get("verif-hash") or ""
    return bool(secret_hash) and hmac.compare_digest(sent.encode(), secret_hash.encode())
