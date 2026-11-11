"""Flutterwave's event push: verify, de-duplicate, hand to whoever owns the money.

| Event | Goes to |
|---|---|
| `charge.completed` | `DepositService.on_charge` — which re-verifies with Flutterwave |
| `transfer.completed` | `WithdrawalService.on_transfer` |
| anything else | acknowledged and ignored (bills are re-read on the retry) |

`verif-hash` is checked before anything parses the body. Delivery is at least
once, so `<event>:<data.id>` is recorded in `processed_messages` *after* it has
been handled: a crash halfway lets Flutterwave's retry finish the job, and every
handler is idempotent on its own reference anyway.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.database import neon
from app.modules.flutterwave import flutterwave
from app.modules.wallet.deposit_service import DepositService
from app.modules.wallet.withdrawal_service import WithdrawalService


class FlutterwaveWebhookService:
    def __init__(self, db: neon.Database, secret_hash: Optional[str],
                 deposits: DepositService, withdrawals: WithdrawalService) -> None:
        self.db = db
        self.secret_hash = secret_hash
        self.deposits = deposits
        self.withdrawals = withdrawals

    def handle(self, raw: bytes, headers: Mapping[str, str]) -> dict[str, Any]:
        if not self.secret_hash:
            raise ApiError(401, "webhook_unconfigured", "FLW_SECRET_HASH is not set")
        if not flutterwave.verify_webhook(headers, self.secret_hash):
            raise ApiError(401, "webhook_unverified", "Bad verif-hash")
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as err:
            raise ApiError(400, "bad_update", "Body is not JSON") from err

        event_type = event["event"]
        data = event["data"]
        event_id = f"{event_type}:{data['id']}"
        if self.db.one(
            "SELECT 1 AS seen FROM processed_messages WHERE channel = 'flutterwave'"
            " AND message_id = $1",
            [event_id],
        ) is not None:
            return {"ok": True, "duplicate": True}

        if event_type == "charge.completed":
            self.deposits.on_charge(data["tx_ref"])
        elif event_type == "transfer.completed":
            self.withdrawals.on_transfer(data["reference"], data["status"],
                                         data.get("complete_message"))

        self.db.query(
            "INSERT INTO processed_messages (channel, message_id, processed_at)"
            " VALUES ('flutterwave', $1, $2) ON CONFLICT DO NOTHING",
            [event_id, Clock.now_iso()],
        )
        return {"ok": True, "duplicate": False}
