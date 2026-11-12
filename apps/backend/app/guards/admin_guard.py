"""The admin routes answer only to `X-Stark-Admin-Key`, compared in constant time
against `STARK_ADMIN_KEY`. With no key configured every request is refused (fail
closed), the same way the Telegram and Flutterwave webhooks treat a missing secret.
"""

import hmac
from typing import Optional

from fastapi import Security
from fastapi.security import APIKeyHeader

from app.common.api_error import ApiError
from app.decorators.inject_module import Module

ADMIN_HEADER = "X-Stark-Admin-Key"

# Declared so Swagger offers "Authorize"; the guard does its own refusal.
admin_key_scheme = APIKeyHeader(name=ADMIN_HEADER, auto_error=False,
                                description="STARK_ADMIN_KEY")


class AdminGuard:
    # No `from __future__ import annotations`: see auth_guard.py.

    def __call__(self, module: Module,
                 key: Optional[str] = Security(admin_key_scheme)) -> None:
        expected = module.config.admin_key
        if expected is None:
            raise ApiError(403, "admin_disabled", "Admin access is not configured.")
        if not key or not hmac.compare_digest(key.encode(), expected.encode()):
            raise ApiError(401, "unauthorized", "Wrong or missing admin key.")


admin_guard = AdminGuard()
