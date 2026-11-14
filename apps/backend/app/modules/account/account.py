from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.modules.agent.toolbox import Limits


@dataclass(frozen=True)
class Account:
    """The signed-in caller, as the auth guard resolved it for this request."""

    id: str
    email: str
    name: Optional[str]
    # The bearer token the request arrived with, so sign-out deletes exactly the
    # session that was used. None for accounts acted on by the server itself
    # (the Telegram bot's owner, the reminder loop).
    token: Optional[str] = None

    @property
    def first_name(self) -> str:
        """What to greet someone by. The provider stores a display name, not a split one."""
        parts = (self.name or "").strip().split()
        return parts[0] if parts else "there"


@dataclass
class AccountState:
    """What the server keeps warm for one account between requests.

    Bills and limits are the stored rows, loaded once and written through on every
    change (`AccountRepository`). The agent is per account because its caps and its
    toolbox are.
    """

    bills: dict[str, dict[str, Any]]
    limits: Limits
    # When the owner paused Stark, or None while it may pay. Written through by
    # `ControlService`; every payment path refuses while it is set.
    paused_at: Optional[str] = None
    agent: Any = None
    # Refreshed from the session on every web request; the Telegram bot and the
    # reminder loop have no session of their own, so they greet with the last one.
    first_name: str = "there"
