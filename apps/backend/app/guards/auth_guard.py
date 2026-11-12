"""Every `/v1` route is somebody's data, so it needs a live Neon Auth session.

The token comes from `Authorization: Bearer` and nowhere else. A token in a query
string lands in access logs and browser history, so the one route an `<audio>`
element plays takes a short-lived ticket instead (`POST /v1/speak/ticket`). An
unauthenticated request never falls through to anyone's account.
"""

from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.decorators.inject_module import Module
from app.modules.account.account import Account

# Declared so Swagger offers "Authorize"; the guard does its own refusal, in the
# contract's shape, rather than FastAPI's 403.
bearer_scheme = HTTPBearer(auto_error=False, description="Neon Auth session token")


class AuthGuard:
    # No `from __future__ import annotations` in this file: FastAPI resolves string
    # annotations through the callable's globals, and an instance has none.

    def __call__(
        self,
        module: Module,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ) -> Account:
        token = credentials.credentials.strip() if credentials else ""
        # One query, not three: session, account and opening travel together.
        row = module.auth.session_account(token, now=Clock.now_iso()) if token else None
        if row is None:
            raise ApiError(401, "unauthorized", "Sign in to use Stark.")
        account = Account(
            id=row["id"], email=row["email"], name=row.get("name"), token=token
        )
        state = module.accounts.state(account.id, opened=row["seeded_at"] is not None)
        state.first_name = account.first_name
        return account
