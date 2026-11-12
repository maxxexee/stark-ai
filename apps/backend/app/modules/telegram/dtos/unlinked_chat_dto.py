from __future__ import annotations

from pydantic import BaseModel, Field


class UnlinkedChatDto(BaseModel):
    unlinked: bool = True
    channel: str = Field(examples=["telegram"])
    channel_user_id: str = Field(examples=["5512094821"])
