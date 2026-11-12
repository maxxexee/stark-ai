from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.decorators.api_responses import ApiResponses
from app.decorators.auth_user import AuthUser
from app.decorators.inject_module import Module
from app.modules.payment.dtos.create_payment_dto import CreatePaymentDto
from app.modules.receipt.dtos.receipt_dto import ReceiptDto

router = APIRouter(tags=["Payments"], responses=ApiResponses.errors("unauthorized"))


@router.post("/v1/payments", status_code=201, response_model=ReceiptDto,
             summary="Pay a saved bill",
             responses=ApiResponses.errors(
                 "paused", "unknown_bill", "bill_unconfirmed", "bad_amount",
                 "over_per_payment_cap", "over_cap",
                 "insufficient_balance", "vendor_failed", "authorisation_failed", "float_low",
             ))
def pay(dto: CreatePaymentDto, account: AuthUser, module: Module) -> JSONResponse:
    """Refused with `paused` while the owner has paused Stark. Otherwise the
    per-payment cap is checked first, then the monthly cap, then the balance.
    Charging happens only on delivery: a `pending` or `failed` receipt cost nothing."""
    return JSONResponse(module.bill_payments.pay(account.id, dto.bill_id, dto.amount_ngn),
                        status_code=201)


@router.get("/v1/activity", response_model=list[ReceiptDto], tags=["Activity"],
            summary="The latest 20 entries, newest first")
def activity(account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse(module.bill_payments.recent(account.id, 20))
