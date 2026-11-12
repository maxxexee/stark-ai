from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.decorators.api_responses import ApiResponses
from app.modules.admin.dtos.update_fees_dto import UpdateFeesDto
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


@router.patch(
    "/v1/admin/fees",
    summary="Set the service fee Stark adds to each kind of bill",
    responses=ApiResponses.errors("admin_disabled", "unauthorized", "bad_fee"),
)
async def update_fees(dto: UpdateFeesDto, module: Module) -> JSONResponse:
    """Applies to the next payment. Kinds left out keep their fee."""
    fees = await run_in_threadpool(module.settings_service.set_fees,
                                   dto.model_dump(exclude_none=True))
    return JSONResponse({"fees_ngn": fees})
