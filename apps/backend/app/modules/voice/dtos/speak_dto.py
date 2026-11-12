from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.common.dto.contract_field import ContractField

# Every character is paid for at the voice provider; a reply is a sentence or two.
MAX_SPEAK_CHARS = 2_000


class SpeakDto(BaseModel):
    text: str = Field(default="", examples=["You've got ₦64,200 in your wallet."],
                      description=f"At most {MAX_SPEAK_CHARS:,} characters.")

    @field_validator("text", mode="before")
    @classmethod
    def as_text(cls, value: Any) -> str:
        text = ContractField.text(value)
        if len(text) > MAX_SPEAK_CHARS:
            raise ContractField.fail("bad_text",
                                     f"`text` must be at most {MAX_SPEAK_CHARS:,} characters.")
        return text
