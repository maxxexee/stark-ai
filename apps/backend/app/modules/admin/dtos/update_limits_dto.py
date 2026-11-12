from __future__ import annotations

from typing import Optional

from pydantic import RootModel, StrictInt


class UpdateLimitsDto(RootModel[dict[str, Optional[StrictInt]]]):
    """`{"<limit key>": <whole number>}` for each limit to change; `null` puts that
    limit back on its default. Keys left out keep their value.

    The keys and ranges are checked by `OperatorLimits`, which owns them, so the
    answer is `unknown_limit` or `bad_limit` rather than a generic validation error.
    """

    model_config = {"json_schema_extra": {"examples": [
        {"withdraw_daily_ngn": 300_000, "card_hold_hours": None},
    ]}}
