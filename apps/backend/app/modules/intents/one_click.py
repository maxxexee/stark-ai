"""NEAR Intents, through the 1Click API — how a deposit from any chain arrives.

The user picks what they hold (USDT on Tron, ETH, SOL, BTC…) and a naira amount.
1Click quotes a swap into **USDC on NEAR, delivered to Stark's treasury**, and
returns a one-off deposit address. When the user's transfer lands, market makers
fill the swap and the status turns `SUCCESS`; Stark then credits the naira.

Shapes are from the live spec (`/docs/v0/openapi.yaml`, v0.1.10, read 2026-11-03):

* `POST /v0/quote` — amounts are integer strings in the asset's smallest unit.
  `EXACT_OUTPUT` fixes what the treasury receives; `quote.amountIn` is what the
  user must send. Refunds go to the treasury's Intents account (`refundType:
  INTENTS`), so the user is never asked for a refund address — Stark returns a
  refund by hand, which the operator sees on the deposit.
* `GET /v0/status?depositAddress=` — `KNOWN_DEPOSIT_TX`, `PENDING_DEPOSIT`,
  `INCOMPLETE_DEPOSIT`, `PROCESSING`, `SUCCESS`, `REFUNDED`, `FAILED`.
* Auth: `X-API-Key: <partner JWT>` (`ONECLICK_API_KEY`). Optional; without one
  1Click adds 0.25% to every quote.

There is no testnet. Exercise it with `dry: true` quotes and a dust-sized swap.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Mapping, Optional

BASE_URL = "https://1click.chaindefuser.com"
# Native Circle USDC on NEAR mainnet (6 decimals), confirmed in /v0/tokens.
USDC_NEAR = "nep141:17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1"
USDC_DECIMALS = 6

# What the Add money screen offers. Each must be in /v0/tokens; `tokens()` drops
# any that 1Click stops listing.
OFFERED_SYMBOLS = frozenset({"USDT", "USDC", "ETH", "SOL", "BTC", "NEAR"})
TERMINAL = frozenset({"SUCCESS", "REFUNDED", "FAILED"})
USER_AGENT = "stark-backend/1.0 (+https://hellostark.xyz)"


SwapType = Literal["EXACT_INPUT", "EXACT_OUTPUT"]
MINIMUM_USD = re.compile(r"minimum swap amount is \$([\d.]+)")


class OneClickError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message

    def minimum_usd(self) -> Optional[Decimal]:
        """The swap floor 1Click named when it refused a quote as too small, if it did."""
        found = MINIMUM_USD.search(self.message)
        return Decimal(found.group(1)) if found else None


@dataclass(frozen=True)
class OneClickClient:
    api_key: Optional[str]
    base_url: str = BASE_URL
    timeout: int = 20

    def tokens(self) -> list[dict[str, Any]]:
        """The assets a user can pay with: offered symbols, minus the destination."""
        listed = self._request("GET", "/v0/tokens")
        return [
            t for t in listed
            if t["symbol"] in OFFERED_SYMBOLS and t["assetId"] != USDC_NEAR
        ]

    def quote(self, *, origin_asset: str, swap_type: SwapType, amount: int, recipient: str,
              deadline: str, dry: bool = False) -> dict[str, Any]:
        """A swap of `origin_asset` into USDC on NEAR. `EXACT_OUTPUT`: `amount` is the USDC
        out; `EXACT_INPUT`: `amount` is the origin asset in. A dry quote reserves no
        deposit address, so it is safe to ask for on every keystroke."""
        return self._request("POST", "/v0/quote", {
            "dry": dry,
            "swapType": swap_type,
            "slippageTolerance": 100,
            "originAsset": origin_asset,
            "depositType": "ORIGIN_CHAIN",
            "destinationAsset": USDC_NEAR,
            "amount": str(amount),
            "refundTo": recipient,
            "refundType": "INTENTS",
            "recipient": recipient,
            "recipientType": "DESTINATION_CHAIN",
            "deadline": deadline,
        })

    def quote_withdrawal(self, *, destination_asset: str, usdc_in: int, recipient: str,
                         treasury: str, deadline: str) -> dict[str, Any]:
        """The other direction: an exact amount of the treasury's USDC on NEAR, swapped
        to `destination_asset` and delivered to the user's `recipient` address.

        The deposit address is on NEAR (`ORIGIN_CHAIN`), so the treasury funds it
        with a plain `ft_transfer`; a failed swap refunds the USDC to the treasury.
        1Click checks `recipient` against the destination chain's address format.
        """
        return self._request("POST", "/v0/quote", {
            "dry": False,
            "swapType": "EXACT_INPUT",
            "slippageTolerance": 100,
            "originAsset": USDC_NEAR,
            "depositType": "ORIGIN_CHAIN",
            "destinationAsset": destination_asset,
            "amount": str(usdc_in),
            "refundTo": treasury,
            "refundType": "ORIGIN_CHAIN",
            "recipient": recipient,
            "recipientType": "DESTINATION_CHAIN",
            "deadline": deadline,
        })

    def status(self, deposit_address: str, deposit_memo: Optional[str]) -> dict[str, Any]:
        query = {"depositAddress": deposit_address}
        if deposit_memo:
            query["depositMemo"] = deposit_memo
        return self._request("GET", "/v0/status?" + urllib.parse.urlencode(query))

    def submit_deposit(self, deposit_address: str, tx_hash: str,
                       memo: Optional[str]) -> dict[str, Any]:
        """Tell 1Click about the user's transfer so it is picked up sooner."""
        body: dict[str, Any] = {"txHash": tx_hash, "depositAddress": deposit_address}
        if memo:
            body["memo"] = memo
        return self._request("POST", "/v0/deposit/submit", body)

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        # Cloudflare in front of 1Click refuses Python's default `Python-urllib/x`
        # agent with 403, so every request names itself.
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                         headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as err:
            try:
                detail = err.read().decode("utf-8", "replace")[:300]
            finally:
                err.close()
            raise OneClickError(err.code, detail) from err
        except urllib.error.URLError as err:
            raise OneClickError(0, f"Could not reach 1Click: {err}") from err


def client_from_env(env: Optional[Mapping[str, str]] = None) -> OneClickClient:
    source = os.environ if env is None else env
    return OneClickClient(api_key=(source.get("ONECLICK_API_KEY") or "").strip() or None)
