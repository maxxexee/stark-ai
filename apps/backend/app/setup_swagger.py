"""Swagger UI at `/docs`, ReDoc at `/redoc`, the spec at `/docs/openapi.json`.

`docs/API.md` remains the written contract; this is the same surface, generated
from the DTOs the routes actually use, with "Authorize" for a Neon Auth token.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

DESCRIPTION = """
The Stark API: bills, payments, wallet, limits, voice and the Telegram bot.

**Auth.** Every `/v1` route except the Telegram webhook needs a Neon Auth session:
`Authorization: Bearer <token>`. Use **Authorize** above to try routes from here.

**Errors.** Every non-2xx body is `{code, message, detail}`. Branch on `code`.

**Money** is integer naira (`_ngn`), **times** are ISO 8601 UTC with `Z`. The
contract is frozen: additive changes only. See `docs/API.md` for the full rules.
"""


class SwaggerSetup:
    DOCS_URL = "/docs"
    OPENAPI_URL = "/docs/openapi.json"

    @staticmethod
    def options(version: str) -> dict:
        return {
            "title": "Stark API",
            "description": DESCRIPTION,
            "version": version,
            "docs_url": SwaggerSetup.DOCS_URL,
            "redoc_url": "/redoc",
            "openapi_url": SwaggerSetup.OPENAPI_URL,
            "swagger_ui_parameters": {"persistAuthorization": True},
        }

    @staticmethod
    def install(app: FastAPI) -> None:
        """Generate the spec once, without FastAPI's automatic 422 responses.

        This API never answers 422: bad input is a 400 in the contract's shape
        (`filters/http_exception_filter.py`), so documenting 422 would be a lie.
        """

        def openapi() -> dict:
            if app.openapi_schema is None:
                spec = get_openapi(
                    title=app.title,
                    version=app.version,
                    description=app.description,
                    routes=app.routes,
                )
                for operations in spec["paths"].values():
                    for operation in operations.values():
                        operation.get("responses", {}).pop("422", None)
                schemas = spec.get("components", {}).get("schemas", {})
                schemas.pop("HTTPValidationError", None)
                schemas.pop("ValidationError", None)
                app.openapi_schema = spec
            return app.openapi_schema

        app.openapi = openapi

    @staticmethod
    def announce(app: FastAPI, host: str, port: int) -> None:
        logging.getLogger("stark").info("Documentation: http://%s:%s%s",
                                        host, port, app.docs_url)
