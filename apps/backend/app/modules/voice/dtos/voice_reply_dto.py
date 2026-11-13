from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.modules.wallet.dtos.deposit_dto import DepositDto


class VoiceReplyDto(BaseModel):
    """On `ignored: true` the client stays silent. `stt` is present only when the
    request carried audio; `actions` and `tx_hash` are for debugging, not display."""

    transcript: str = Field(description="What was actually said, not the rewritten form.",
                            examples=["hello stark what's my light bill"])
    ignored: bool = Field(examples=[False])
    reply: Optional[str] = Field(examples=["You've got ₦64,200 in your wallet."])
    token: Optional[str] = Field(examples=[None])
    receipt_id: Optional[str] = Field(examples=[None])
    actions: Optional[list[str]] = Field(default=None, examples=[["get_state"]])
    tx_hash: Optional[str] = Field(default=None, examples=[None])
    deposit: Optional[DepositDto] = Field(
        default=None, description="A deposit the agent started: show `pay` under the reply.")
    audio: Optional[str] = Field(description="The reply as a WAV data URL, or null.",
                                 examples=[None])
    speak_url: Optional[str] = Field(
        default=None, description=(
            "A short-lived link that streams this reply as audio, or null. Saves the "
            "client a ticket round trip after the words land."),
        examples=["/v1/speak/stream?ticket=..."])
    stt: Optional[str] = Field(default=None, description="ok | failed | no_key",
                               examples=["ok"])
