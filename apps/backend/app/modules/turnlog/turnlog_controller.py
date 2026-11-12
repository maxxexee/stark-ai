from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.common.api_error import ApiError
from app.decorators.api_responses import ApiResponses
from app.guards.admin_guard import admin_guard
from app.modules.turnlog import turnlog
from app.modules.turnlog.dtos.turn_log_dto import TurnLogDto

# Operator-only. The log is one file for every account — transcripts, replies,
# vending tokens and each account snapshot the model saw — so a user session must
# never open it: it once did, and any sign-up could read everyone's turns.
router = APIRouter(tags=["Debug"], dependencies=[Depends(admin_guard)],
                   responses=ApiResponses.errors("admin_disabled", "unauthorized"))


@router.get("/v1/turnlog", response_model=TurnLogDto, summary="Read the conversation log",
            responses=ApiResponses.errors("turnlog_off"))
def read(
    limit: str = Query("100", description="Newest N entries; 0 for the whole file. "
                                          "Not a number falls back to 100."),
    account: str = Query("", description="Only this account's turns. Synthesis "
                                         "entries and turns logged before accounts "
                                         "were recorded carry no account and drop out."),
) -> JSONResponse:
    """Debug route, not part of the product contract. Needs `X-Stark-Admin-Key`, like
    the admin routes. 404 while `STARK_TURN_LOG` is off, so a box that was not asked
    to log does not claim to have a log."""
    if not turnlog.enabled():
        raise ApiError(404, "turnlog_off", "The turn log is off. Set STARK_TURN_LOG.")
    try:
        newest = int(limit.strip())
    except ValueError:
        newest = 100
    entries = turnlog.lines()
    if account:
        entries = [e for e in entries if e.get("account_id") == account]
    if newest > 0:
        entries = entries[-newest:]
    return JSONResponse({"enabled": True, "count": len(entries), "entries": entries})
