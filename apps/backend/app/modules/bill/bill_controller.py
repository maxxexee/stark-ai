from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.decorators.api_responses import ApiResponses
from app.decorators.auth_user import AuthUser
from app.decorators.inject_module import Module
from app.modules.bill.dtos.bill_dto import BillDto
from app.modules.bill.dtos.create_bill_dto import CreateBillDto
from app.modules.bill.dtos.deleted_bill_dto import DeletedBillDto
from app.modules.bill.dtos.update_bill_dto import UpdateBillDto

router = APIRouter(prefix="/v1/bills", tags=["Bills"],
                   responses=ApiResponses.errors("unauthorized"))


@router.get("", response_model=list[BillDto], summary="List saved bills")
def list_bills(account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse(module.bills.public(account.id))


@router.post("", status_code=201, response_model=BillDto, summary="Add a bill",
             responses=ApiResponses.errors(
                 "bad_kind", "bad_bill", "bad_reference", "bad_renews_on",
                 "unsupported_product", "plan_required", "unknown_plan", "duplicate_bill",
             ))
def add_bill(dto: CreateBillDto, account: AuthUser, module: Module) -> JSONResponse:
    """Adding a bill updates the agent's meter allowlist immediately."""
    return JSONResponse(module.bills.add(account.id, dto), status_code=201)


@router.get("/{bill_id}", response_model=BillDto, summary="One bill",
            responses=ApiResponses.errors("unknown_bill"))
def get_bill(bill_id: str, account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse(module.bills.public_bill(account.id, bill_id))


@router.patch("/{bill_id}", response_model=BillDto,
              summary="Rename a bill, change its plan or renewal date",
              responses=ApiResponses.errors(
                  "unknown_bill", "bad_bill", "unsupported_product", "unknown_plan",
                  "bad_renews_on",
              ))
def update_bill(bill_id: str, dto: UpdateBillDto, account: AuthUser,
                module: Module) -> JSONResponse:
    """`renews_on: ""` or `null` removes the date; leaving it out keeps it."""
    return JSONResponse(module.bills.update(account.id, bill_id, dto))


@router.post("/{bill_id}/confirm", response_model=BillDto,
             summary="Confirm a bill Stark saved from a chat",
             responses=ApiResponses.errors("unknown_bill"))
def confirm_bill(bill_id: str, account: AuthUser, module: Module) -> JSONResponse:
    """A bill saved by the agent cannot be paid until its owner confirms it here,
    signed in. Confirming an already confirmed bill changes nothing."""
    return JSONResponse(module.bills.confirm(account.id, bill_id))


@router.delete("/{bill_id}", response_model=DeletedBillDto, summary="Remove a bill",
               responses=ApiResponses.errors("unknown_bill", "bill_in_flight"))
def delete_bill(bill_id: str, account: AuthUser, module: Module) -> JSONResponse:
    """The bill's history stays in `/v1/activity`."""
    return JSONResponse(module.bills.delete(account.id, bill_id))
