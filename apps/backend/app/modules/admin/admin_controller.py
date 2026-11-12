from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.decorators.api_responses import ApiResponses
from app.decorators.inject_module import Module
from app.guards.admin_guard import admin_guard

router = APIRouter(tags=["Admin"], dependencies=[Depends(admin_guard)])


@router.get(
    "/v1/admin/overview",
    summary="Balances, coverage, and deposits and withdrawals by status",
    responses=ApiResponses.errors("admin_disabled", "unauthorized"),
)
async def overview(module: Module) -> JSONResponse:
    """No session: the `X-Stark-Admin-Key` header must equal `STARK_ADMIN_KEY`."""
    return JSONResponse(await run_in_threadpool(module.admin.overview))
