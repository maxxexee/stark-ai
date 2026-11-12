"""The money settings that are deployment config, parsed once at boot. See
`.env.example` for each variable.

The caps, thresholds and rate settings are not here: the owner sets them on the
admin page (`OperatorLimits`), and their variables are only the defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from app.modules.wallet.deposit_service import FundingSettings


@dataclass(frozen=True)
class MoneyConfig:
    funding: FundingSettings
    flutterwave_secret_hash: Optional[str]
    money_tick_seconds: int

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "MoneyConfig":
        source = os.environ if env is None else env
        return cls(
            funding=FundingSettings(
                app_url=(source.get("STARK_APP_URL") or "").strip() or None,
                treasury_account=(source.get("STARK_TREASURY_NEAR_ACCOUNT") or "").strip()
                or None,
            ),
            flutterwave_secret_hash=(source.get("FLW_SECRET_HASH") or "").strip() or None,
            money_tick_seconds=int(source.get("STARK_MONEY_TICK") or 30),
        )
