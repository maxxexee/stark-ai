"""Every error leaves the API in the contract's `{code, message, detail}` shape.

FastAPI's own defaults (`{"detail": "Not Found"}`, 422 validation lists) would leak
past the frozen contract, so each kind of failure is mapped here:

- `ApiError`: raised on purpose by a service; already carries its code.
- Request validation: a DTO's `ContractField` validator carries the contract code;
  anything else (a JSON body that does not parse) is `400 bad_request`.
- Unknown path or method: `404 no_route`, as the API has always answered, including
  for a known path with the wrong method.
- Anything unexpected: logged and answered `500 stub_error`, so the operator sees it
  and the client still gets the shape it parses.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.api_error import ApiError
from app.common.cors import ALLOWED_ORIGIN
from app.common.dto.contract_field import CONTRACT

log = logging.getLogger("stark.http")


class HttpExceptionFilter:
    @staticmethod
    def register(app: FastAPI) -> None:
        app.add_exception_handler(ApiError, HttpExceptionFilter.api_error)
        app.add_exception_handler(RequestValidationError, HttpExceptionFilter.validation)
        app.add_exception_handler(StarletteHTTPException, HttpExceptionFilter.http)
        app.add_exception_handler(Exception, HttpExceptionFilter.unexpected)

    @staticmethod
    async def api_error(_request: Request, err: ApiError) -> JSONResponse:
        return JSONResponse(err.body, status_code=err.status)

    @staticmethod
    async def validation(_request: Request, err: RequestValidationError) -> JSONResponse:
        first = err.errors()[0]
        if (first.get("ctx") or {}).get(CONTRACT):
            return JSONResponse(
                ApiError(400, first["type"], first["msg"]).body, status_code=400
            )
        where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = f"{where}: {first['msg']}" if where else first["msg"]
        return JSONResponse(ApiError(400, "bad_request", message).body, status_code=400)

    @staticmethod
    async def http(request: Request, err: StarletteHTTPException) -> JSONResponse:
        if err.status_code in (404, 405):
            return JSONResponse(
                ApiError(404, "no_route",
                         f"No route {request.method} {request.url.path}").body,
                status_code=404,
            )
        return JSONResponse(
            ApiError(err.status_code, "http_error", str(err.detail)).body,
            status_code=err.status_code,
        )

    @staticmethod
    async def unexpected(request: Request, err: Exception) -> JSONResponse:
        # Logged in full, with its traceback, under an id the client is given: the
        # operator can find it in the platform's logs, while the client never sees
        # a database message or a provider's error body.
        ref = uuid.uuid4().hex[:12]
        log.error("unhandled error ref=%s %s %s", ref, request.method, request.url.path,
                  exc_info=err)
        # Starlette answers this from outside CORSMiddleware, so without the header
        # the browser hides the 500 behind a CORS error.
        headers = {"Vary": "Origin"}
        origin = request.headers.get("origin")
        if origin is not None and ALLOWED_ORIGIN.fullmatch(origin):
            headers["Access-Control-Allow-Origin"] = origin
        return JSONResponse(
            ApiError(500, "stub_error",
                     f"Something went wrong on our side. Reference {ref}.").body,
            status_code=500, headers=headers)
