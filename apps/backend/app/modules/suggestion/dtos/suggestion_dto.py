from __future__ import annotations

from pydantic import BaseModel, Field


class SuggestionDto(BaseModel):
    id: str = Field(description="Stable: key a dismissal on it, not on the copy.",
                    examples=["sug_units"])
    text: str = Field(description="A finished sentence. Render, don't reassemble.",
                      examples=["About 11.4 units left, roughly 4 days."])
    severity: str = Field(description="info | warn | alert", examples=["warn"])
    reason: str = Field(description="For debugging, not display.", examples=["units_low"])
