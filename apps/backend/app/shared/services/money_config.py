"""The money settings, parsed once at boot. See `.env.example` for each variable."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Optional

from app.modules.liquidity import usdc_rate as rate
from app.modules.liquidity.float_service import FloatSettings
from app.modules.liquidity.usdc_rate import UsdcRate
from app.modules.treasury.treasury_watch import WatchSettings
from app.modules.wallet.crypto_withdrawal_service import CryptoPayoutSettings
from app.modules.wallet.deposit_service import FundingSettings
from app.modules.wallet.withdrawal_service import WithdrawalSettings


@dataclass(frozen=True)
class MoneyConfig:
    funding: FundingSettings
    float_settings: FloatSettings
    watch: WatchSettings
    withdrawals: WithdrawalSettings
    crypto_payouts: CryptoPayoutSettings
    flutterwave_secret_hash: Optional[str]
    money_tick_seconds: int

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "MoneyConfig":
        source = os.environ if env is None else env
        fixed = (source.get("STARK_USDC_NGN_RATE") or "").strip()
        usdc_rate = UsdcRate(
            spread_ngn=Decimal(source.get("STARK_USDC_NGN_SPREAD") or "10"),
            fixed=Decimal(fixed) if fixed else None,
            floor=Decimal(source.get("STARK_USDC_RATE_MIN") or rate.RATE_MIN),
            ceiling=Decimal(source.get("STARK_USDC_RATE_MAX") or rate.RATE_MAX),
            max_move=Decimal(source.get("STARK_USDC_RATE_MAX_MOVE") or rate.MAX_MOVE),
        )
        float_low_ngn = int(source.get("STARK_FLOAT_LOW_NGN") or 100_000)
        return cls(
            funding=FundingSettings(
                app_url=(source.get("STARK_APP_URL") or "").strip() or None,
                treasury_account=(source.get("STARK_TREASURY_NEAR_ACCOUNT") or "").strip()
                or None,
                usdc_rate=usdc_rate,
                card_hold_hours=int(source.get("STARK_CARD_HOLD_HOURS") or 72),
            ),
            float_settings=FloatSettings(low_water_ngn=float_low_ngn),
            watch=WatchSettings(
                float_low_ngn=float_low_ngn,
                treasury_low_usdc=Decimal(source.get("STARK_TREASURY_LOW_USDC") or "100"),
                summary_hour=int(source.get("STARK_SUMMARY_HOUR") or 8),
            ),
            withdrawals=WithdrawalSettings(
                daily_ngn=int(source.get("STARK_WITHDRAW_DAILY_NGN") or 200_000),
                lookups_per_day=int(source.get("STARK_BANK_LOOKUPS_PER_DAY") or 20),
            ),
            crypto_payouts=CryptoPayoutSettings(
                usdc_rate=usdc_rate,
                max_ngn=int(source.get("STARK_CRYPTO_WITHDRAW_MAX_NGN") or 200_000),
                max_usdc=Decimal(source.get("STARK_CRYPTO_WITHDRAW_MAX_USDC") or "200"),
                daily_ngn=int(source.get("STARK_CRYPTO_WITHDRAW_DAILY_NGN") or 1_000_000),
                user_daily_ngn=int(source.get("STARK_CRYPTO_WITHDRAW_USER_DAILY_NGN")
                                   or 200_000),
            ),
            flutterwave_secret_hash=(source.get("FLW_SECRET_HASH") or "").strip() or None,
            money_tick_seconds=int(source.get("STARK_MONEY_TICK") or 30),
        )
