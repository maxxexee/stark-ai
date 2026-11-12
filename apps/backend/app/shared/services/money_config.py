"""The money settings, parsed once at boot. See `.env.example` for each variable."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Optional

from app.modules.liquidity.float_service import FloatSettings
from app.modules.liquidity.usdc_rate import UsdcRate
from app.modules.treasury.treasury_watch import WatchSettings
from app.modules.wallet.crypto_withdrawal_service import CryptoPayoutSettings
from app.modules.wallet.deposit_service import FundingSettings


@dataclass(frozen=True)
class MoneyConfig:
    funding: FundingSettings
    float_settings: FloatSettings
    watch: WatchSettings
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
        )
        float_low_ngn = int(source.get("STARK_FLOAT_LOW_NGN") or 100_000)
        return cls(
            funding=FundingSettings(
                app_url=(source.get("STARK_APP_URL") or "").strip() or None,
                treasury_account=(source.get("STARK_TREASURY_NEAR_ACCOUNT") or "").strip()
                or None,
                usdc_rate=usdc_rate,
            ),
            float_settings=FloatSettings(low_water_ngn=float_low_ngn),
            watch=WatchSettings(
                float_low_ngn=float_low_ngn,
                treasury_low_usdc=Decimal(source.get("STARK_TREASURY_LOW_USDC") or "100"),
                summary_hour=int(source.get("STARK_SUMMARY_HOUR") or 8),
            ),
            crypto_payouts=CryptoPayoutSettings(
                usdc_rate=usdc_rate,
                max_ngn=int(source.get("STARK_CRYPTO_WITHDRAW_MAX_NGN") or 200_000),
                daily_ngn=int(source.get("STARK_CRYPTO_WITHDRAW_DAILY_NGN") or 1_000_000),
            ),
            flutterwave_secret_hash=(source.get("FLW_SECRET_HASH") or "").strip() or None,
            money_tick_seconds=int(source.get("STARK_MONEY_TICK") or 30),
        )
