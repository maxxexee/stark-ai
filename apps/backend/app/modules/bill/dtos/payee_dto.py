from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.modules.bill.bill_kind import BillKind


class PayeeDto(BaseModel):
    """A saved bill seen as somewhere Stark may send money, with what it has been paid."""

    bill_id: str = Field(examples=["bill_home_meter"])
    label: str = Field(examples=["Home"])
    kind: BillKind
    provider: str = Field(examples=["Ikeja Electric"])
    reference: str = Field(examples=["0101170026583"])
    paid_this_month_ngn: int = Field(description="Delivered payments since the 1st, UTC.",
                                     examples=[15000])
    paid_total_ngn: int = Field(description="Every delivered payment.", examples=[23000])
    payments: int = Field(examples=[3])
    last_paid_at: Optional[str] = Field(examples=["2026-11-02T19:33:13Z"])
