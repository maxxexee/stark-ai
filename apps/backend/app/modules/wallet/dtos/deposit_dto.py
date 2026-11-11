from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.common.dto.contract_field import ContractField


class StartDepositDto(BaseModel):
    amount_ngn: int = Field(default=0, examples=[20000],
                            description="Integer naira, ₦100 to ₦5,000,000.")
    method: Literal["bank", "crypto"] = Field(
        examples=["bank"],
        description="`bank` opens a Flutterwave checkout (bank transfer, card, USSD). "
                    "`crypto` quotes a NEAR Intents deposit from any listed asset.",
    )
    asset_id: Optional[str] = Field(
        default=None, examples=["nep141:tron-d28a265909efecdcee7c5028585214ea0b96f015.omft.near"],
        description="Required for `crypto`: an `asset_id` from GET /v1/wallet/crypto-assets.",
    )

    @field_validator("amount_ngn", mode="before")
    @classmethod
    def amount(cls, value: Any) -> int:
        return ContractField.integer(value, "bad_amount", "amount_ngn must be an integer")


class DepositTxDto(BaseModel):
    tx_hash: str = Field(min_length=8, max_length=200)


class DepositPayDto(BaseModel):
    """`checkout_url` for bank; asset/chain/amount/address/memo for crypto."""

    checkout_url: Optional[str] = None
    asset: Optional[str] = None
    chain: Optional[str] = None
    amount: Optional[str] = Field(default=None, description="Exactly this much, as a decimal.")
    address: Optional[str] = None
    memo: Optional[str] = Field(default=None, description="Must be sent with the transfer when set.")


class DepositDto(BaseModel):
    id: str
    method: Literal["bank", "crypto"]
    amount_ngn: int
    credited_ngn: Optional[int]
    status: Literal["open", "confirming", "credited", "expired", "failed", "refunded"]
    note: Optional[str]
    pay: DepositPayDto
    expires_at: Optional[str]
    created_at: str
    credited_at: Optional[str]


class CryptoAssetDto(BaseModel):
    asset_id: str
    symbol: str
    chain: str


class WithdrawMethodsDto(BaseModel):
    bank: bool
    crypto: bool


class FundingMethodsDto(BaseModel):
    bank: bool
    crypto: bool
    test_money: bool
    withdraw: WithdrawMethodsDto
