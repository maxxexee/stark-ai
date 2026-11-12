from __future__ import annotations

from pydantic import BaseModel, Field


class SpeakTicketDto(BaseModel):
    url: str = Field(description="Path to play, relative to the API's base URL.",
                     examples=["/v1/speak/stream?ticket=3q2-7w…"])
    expires_in_seconds: int = Field(examples=[120])
