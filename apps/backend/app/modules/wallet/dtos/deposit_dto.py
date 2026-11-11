from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.common.api_error import ApiError

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


class DepositPreviewDto(BaseModel):
    """Exactly one of `amount_ngn` (what to credit) or `amount_in` (what the user sends)."""

    asset_id: str = Field(description="An `asset_id` from GET /v1/wallet/crypto-assets.")
    amount_ngn: Optional[int] = Field(default=None, examples=[150000])
    amount_in: Optional[Decimal] = Field(default=None, gt=0, examples=["0.5"],
                                         description="In the asset, as a decimal.")

    @model_validator(mode="after")
    def one_side(self) -> "DepositPreviewDto":
        if (self.amount_ngn is None) == (self.amount_in is None):
            raise ApiError(400, "bad_amount", "Send amount_ngn or amount_in, not both.")
        return self


class DepositPreviewResultDto(BaseModel):
    asset_id: str
    amount_ngn: int = Field(description="What the deposit would credit, in naira.")
    amount_in: str = Field(description="What the user would send, in the asset.")
    rate: str = Field(description="Naira per USDC the deposit would lock.")


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


class UsdcRatesDto(BaseModel):
    """Naira per USDC right now, as decimals. A deposit locks `deposit` when it is
    quoted; a withdrawal is priced at `withdraw` when it is sent."""

    deposit: str = Field(examples=["1370.56"], description="Naira credited per USDC paid in.")
    withdraw: str = Field(examples=["1390.56"], description="Naira charged per USDC sent out.")


class WithdrawMethodsDto(BaseModel):
    bank: bool
    crypto: bool


class FundingMethodsDto(BaseModel):
    bank: bool
    crypto: bool
    test_money: bool
    withdraw: WithdrawMethodsDto
