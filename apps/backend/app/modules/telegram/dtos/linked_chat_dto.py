from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LinkedChatDto(BaseModel):
    channel: str = Field(examples=["telegram"])
    channel_user_id: str = Field(description="What `DELETE` names. Show `chat_hint` instead.",
                                 examples=["5512094821"])
    chat_hint: str = Field(description="The id's last four digits, for display.",
                           examples=["•••• 4821"])
    display_name: Optional[str] = Field(description="The Telegram first name or username "
                                                    "the chat linked with.",
                                        examples=["Tunde"])
    linked_at: str = Field(examples=["2026-11-12T09:12:00Z"])
