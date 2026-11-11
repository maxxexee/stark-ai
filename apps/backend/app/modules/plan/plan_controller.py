from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.decorators.api_responses import ApiResponses
from app.decorators.auth_user import AuthUser
from app.decorators.inject_module import Module
from app.modules.plan.dtos.plan_dto import PlanDto

router = APIRouter(prefix="/v1/plans", tags=["Plans"],
                   responses=ApiResponses.errors("unauthorized"))


@router.get("", response_model=list[PlanDto], summary="Priced data and TV plans",
            responses=ApiResponses.errors("bad_kind"))
def list_plans(
    _account: AuthUser,
    module: Module,
    kind: str = Query("", description="data or tv; omit for both", examples=["data"]),
    provider: str = Query("", description="Loosely matches a service id or name",
                          examples=["mtn"]),
) -> JSONResponse:
    """Read from Flutterwave's live catalogue. Never hardcode prices in the app."""
    return JSONResponse(module.plans.plans(kind, provider))
