from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ReceiptDto(BaseModel):
    """A payment, deposit or withdrawal. Render a payment as complete only when
    `status` is `delivered`."""

    id: str = Field(examples=["rcpt_3f9a1c"])
    bill_id: str = Field(description='"wallet" for a deposit or withdrawal.',
                         examples=["bill_home_meter"])
    bill_label: str = Field(examples=["Home electricity"])
    amount_ngn: int = Field(examples=[5000])
    units: Optional[float] = Field(examples=[23.92])
    token: Optional[str] = Field(description="Electricity only.",
                                 examples=["4821 0937 5512 8846 3019"])
    tx_hash: Optional[str] = Field(examples=[None])
    tx_url: Optional[str] = Field(
        description="The NEAR explorer page for `tx_hash`, on the network Stark runs on.",
        examples=["https://nearblocks.io/txns/6ZQGL474kqJCxhjEfGSK3EGg76RUpCfvGsFZS7XxYiNv"],
    )
    created_at: str = Field(examples=["2026-10-20T19:33:13Z"])
    status: str = Field(
        description="delivered | pending | failed | declined | received | sent",
        examples=["delivered"],
    )
    request_id: str = Field(examples=["202610201930a1b2c3d4"])
    type: str = Field(description="bill | autotopup | deposit | withdrawal",
                      examples=["bill"])
    source: Optional[str] = Field(examples=["Telegram voice note"])
    reason: Optional[str] = Field(
        default=None,
        description="Why a declined entry was stopped, in plain words; null otherwise.",
        examples=["That's over the most you allow in one go."],
    )
