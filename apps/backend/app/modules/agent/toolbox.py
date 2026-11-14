"""What the agent may touch, and the owner's limits it is held to."""

from __future__ import annotations

from decimal import Decimal

from dataclasses import dataclass
from typing import Protocol

from app.modules.bill.dtos.create_bill_dto import CreateBillDto


class ToolBox(Protocol):
    """What the agent may touch. `AccountToolbox` implements it over one account."""

    def get_state(self) -> dict: ...
    def list_bills(self) -> list[dict]: ...
    def recent_activity(self) -> list[dict]: ...
    # Which ways of adding money are on, and the last few deposits.
    def funding(self) -> dict: ...
    def pay(self, bill_id: str, amount_ngn: int) -> dict: ...
    def add_bill(self, dto: CreateBillDto) -> dict: ...
    def find_plans(self, kind: str, provider: str) -> list[dict]: ...
    # A deposit in `DepositService.shape`: its `pay` is the link or the address.
    # A crypto deposit is sized in naira or, when `amount_crypto` is set, in the coin.
    def add_money(self, method: str, amount_ngn: int, asset: str, chain: str,
                  amount_crypto: Decimal | None = None) -> dict: ...
    # A payment over a limit, filed for the owner to approve in the app. Returns
    # the request with its `window_minutes`.
    def request_approval(self, bill_id: str, amount_ngn: int, reason: str) -> dict: ...
    # An activity row for a payment the rules refused, so the owner can see it.
    def record_refusal(self, bill_id: str, amount_ngn: int, reason: str) -> None: ...


@dataclass(frozen=True)
class Limits:
    """The owner's policy, mirrored from the vault's `get_policy()`."""

    monthly_cap_ngn: int
    per_payment_cap_ngn: int
    allowed_meters: frozenset[str]

    def __post_init__(self) -> None:
        if self.per_payment_cap_ngn > self.monthly_cap_ngn:
            raise ValueError("per-payment cap cannot exceed the monthly cap")

