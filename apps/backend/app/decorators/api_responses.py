"""The contract's error codes, as OpenAPI responses a route can list."""

from __future__ import annotations

from typing import Any

from app.common.dto.error_dto import ErrorDto


class ApiResponses:
    STATUS = {
        "unauthorized": 401,
        "admin_disabled": 403,
        "bad_fee": 400,
        "unknown_fee": 400,
        "unknown_bill": 404,
        "bill_unconfirmed": 409,
        "no_route": 404,
        "bad_amount": 400,
        "bad_watts": 400,
        "bad_kind": 400,
        "bad_reference": 400,
        "bad_bill": 400,
        "bad_renews_on": 400,
        "bad_audio": 400,
        "bad_text": 400,
        "bad_limits": 400,
        "bad_update": 400,
        "unsupported_product": 400,
        "plan_required": 400,
        "unknown_plan": 400,
        "audio_too_large": 413,
        "paused": 423,
        "unknown_request": 404,
        "request_closed": 409,
        "over_per_payment_cap": 409,
        "over_cap": 409,
        "insufficient_balance": 409,
        "duplicate_bill": 409,
        "bill_in_flight": 409,
        "not_configured": 409,
        "unknown_identity": 404,
        "webhook_unconfigured": 401,
        "webhook_unverified": 401,
        "not_available": 501,
        "vendor_failed": 502,
        "no_voice": 503,
        "turnlog_off": 404,
        "unknown_deposit": 404,
        "bad_method": 400,
        "bad_asset": 400,
        "bad_tx": 400,
        "bad_account": 400,
        "bad_address": 400,
        "over_limit": 400,
        "below_minimum": 400,
        "daily_limit": 409,
        "authorisation_failed": 502,
        "provider_failed": 502,
        "float_low": 503,
    }

    @staticmethod
    def errors(*codes: str) -> dict[int | str, dict[str, Any]]:
        by_status: dict[int, list[str]] = {}
        for code in codes:
            by_status.setdefault(ApiResponses.STATUS[code], []).append(code)
        return {
            status: {"model": ErrorDto, "description": ", ".join(f"`{c}`" for c in listed)}
            for status, listed in sorted(by_status.items())
        }
