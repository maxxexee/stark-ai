from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.decorators.api_responses import ApiResponses
from app.decorators.auth_user import AuthUser
from app.decorators.inject_module import Module
from app.modules.telemetry.dtos.reading_accepted_dto import ReadingAcceptedDto
from app.modules.telemetry.dtos.reading_dto import ReadingDto

router = APIRouter(tags=["Telemetry"], responses=ApiResponses.errors("unauthorized"))


@router.post("/v1/telemetry", status_code=202, response_model=ReadingAcceptedDto,
             summary="Record an appliance reading",
             responses=ApiResponses.errors("bad_watts", "rate_limited"))
def record(dto: ReadingDto, account: AuthUser, module: Module) -> JSONResponse:
    """Stamped with the server's clock. Feeds units left, days left and the
    `load_imbalance` suggestion. Limited per account per minute, since every
    reading is a stored row."""
    module.telemetry_limit.hit(account.id)
    return JSONResponse(module.telemetry.record(account.id, dto), status_code=202)
