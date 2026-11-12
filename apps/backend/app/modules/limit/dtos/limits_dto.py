from __future__ import annotations

from pydantic import BaseModel, Field


class LimitsDto(BaseModel):
    monthly_cap_ngn: int = Field(examples=[30000])
    per_payment_cap_ngn: int = Field(examples=[10000])
    spent_ngn: int = Field(description="Delivered bill payments this calendar month (UTC).",
                           examples=[23000])
    remaining_cap_ngn: int = Field(description="Never negative.", examples=[7000])
    approval_window_minutes: int = Field(
        description="How long a payment over a limit waits for approval.", examples=[60])
