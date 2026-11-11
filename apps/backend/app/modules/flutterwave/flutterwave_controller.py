from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.decorators.api_responses import ApiResponses
from app.decorators.inject_module import Module

router = APIRouter(tags=["Flutterwave"])


@router.post(
    "/v1/flutterwave/webhook",
    summary="Flutterwave's event push (Flutterwave calls this, not the app)",
    responses=ApiResponses.errors(
        "webhook_unconfigured", "webhook_unverified", "bad_update"
    ),
)
async def webhook(request: Request, module: Module) -> JSONResponse:
    """No bearer token: the `verif-hash` header must equal `FLW_SECRET_HASH`. Every
    event is refused while it is unset.
    """
    raw = await request.body()
    return JSONResponse(
        await run_in_threadpool(module.flutterwave_webhooks.handle, raw, request.headers)
    )
