from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.modules.settings.settings_service import MAX_FEE_NGN


class UpdateFeesDto(BaseModel):
    """Naira added to each payment of that kind. Leave a kind out to keep its fee."""

    electricity: Optional[int] = Field(default=None, ge=0, le=MAX_FEE_NGN, examples=[100])
    tv: Optional[int] = Field(default=None, ge=0, le=MAX_FEE_NGN, examples=[100])
    airtime: Optional[int] = Field(default=None, ge=0, le=MAX_FEE_NGN, examples=[0])
    data: Optional[int] = Field(default=None, ge=0, le=MAX_FEE_NGN, examples=[0])
