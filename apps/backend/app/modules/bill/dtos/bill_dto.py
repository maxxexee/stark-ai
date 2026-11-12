from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.modules.bill.bill_kind import BillKind


class BillDto(BaseModel):
    """A saved bill. `plan`, `plan_price_ngn` and `renews_on` are absent when unset."""

    id: str = Field(examples=["bill_home_meter"])
    kind: BillKind
    provider: str = Field(examples=["Ikeja Electric"])
    label: str = Field(examples=["Home"])
    reference: str = Field(
        description="Meter, phone or smartcard number. Never a wallet address.",
        examples=["0101170026583"],
    )
    last_amount_ngn: Optional[int] = Field(examples=[5000])
    last_units: Optional[float] = Field(examples=[23.9])
    last_paid_at: Optional[str] = Field(examples=["2026-10-14T19:33:13Z"])
    plan: Optional[str] = Field(default=None, description="Data and TV only.",
                                examples=["dstv79"])
    plan_price_ngn: Optional[int] = Field(default=None, examples=[7900])
    renews_on: Optional[str] = Field(
        default=None, description="YYYY-MM-DD; absent (not null) when unset.",
        examples=["2026-11-03"],
    )
    needs_confirmation: Optional[bool] = Field(
        default=None, description=(
            "true on a bill Stark saved from a chat, until the owner confirms it with "
            "POST /v1/bills/{id}/confirm. Absent otherwise. Such a bill cannot be paid."),
        examples=[None])
