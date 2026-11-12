from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.common.api_error import ApiError
from app.decorators.api_responses import ApiResponses
from app.decorators.auth_user import AuthUser
from app.decorators.inject_module import Module
from app.modules.liquidity.usdc_rate import RateUnavailable
from app.modules.wallet.dtos.deposit_dto import (
    CryptoAssetDto,
    DepositDto,
    DepositPreviewDto,
    DepositPreviewResultDto,
    DepositTxDto,
    FundingMethodsDto,
    StartDepositDto,
    UsdcRatesDto,
)
from app.modules.wallet.dtos.top_up_dto import TopUpDto
from app.modules.wallet.dtos.wallet_dto import WalletDto
from app.modules.wallet.dtos.wallet_entry_dto import WalletEntryDto
from app.modules.wallet.dtos.withdrawal_dto import (
    BankAccountDto,
    CryptoWithdrawDto,
    BankDto,
    ResolvedAccountDto,
    WithdrawalDto,
    WithdrawDto,
)

router = APIRouter(prefix="/v1/wallet", tags=["Wallet"],
                   responses=ApiResponses.errors("unauthorized"))


@router.get("", response_model=WalletDto, summary="Balance and this month's spend")
def wallet(account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse(module.wallet.summary(account.id))


@router.get("/methods", response_model=FundingMethodsDto,
            summary="Which ways of adding money are switched on")
def methods(_account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse({
        **module.deposits.methods(),
        "test_money": module.wallet.test_money,
        "withdraw": {"bank": module.flutterwave is not None,
                     "crypto": module.crypto_withdrawals.available()},
    })


@router.get("/rates", response_model=UsdcRatesDto,
            summary="Stark's naira/USDC rates for crypto deposits and withdrawals",
            responses=ApiResponses.errors("provider_failed"))
def rates(_account: AuthUser, module: Module) -> JSONResponse:
    """Paycrest's live rate with Stark's spread taken each way. A quote can still land
    on a slightly different rate if the market moves before it is made."""
    try:
        return JSONResponse({"deposit": str(module.usdc_rate.buying()),
                             "withdraw": str(module.usdc_rate.selling())})
    except RateUnavailable as err:
        raise ApiError(502, "provider_failed",
                       "Couldn't get a price right now. Try again in a minute.") from err


@router.post("/topup", status_code=201, response_model=WalletEntryDto,
             summary="Add test money", responses=ApiResponses.errors("bad_amount",
                                                                     "not_available"))
def top_up(dto: TopUpDto, account: AuthUser, module: Module) -> JSONResponse:
    """Nothing is collected. Refused with **501** once a payment rail is configured.
    A repeated `request_id` returns **200** with the original entry and credits nothing."""
    status, payload = module.wallet.top_up(account.id, dto)
    return JSONResponse(payload, status_code=status)


# --- adding money ----------------------------------------------------------------


@router.get("/crypto-assets", response_model=list[CryptoAssetDto],
            summary="What a crypto deposit can be paid with",
            responses=ApiResponses.errors("provider_failed"))
def crypto_assets(_account: AuthUser, module: Module) -> JSONResponse:
    """Empty while crypto deposits are not configured."""
    return JSONResponse(module.deposits.crypto_assets())


@router.post("/deposits", status_code=201, response_model=DepositDto,
             summary="Start adding money",
             responses=ApiResponses.errors("bad_amount", "below_minimum", "bad_method",
                                           "bad_asset",
                                           "not_available", "provider_failed"))
def start_deposit(dto: StartDepositDto, account: AuthUser, module: Module) -> JSONResponse:
    """`bank`: send the user to `pay.checkout_url` in the same tab; Flutterwave brings
    them back to `/wallet/add?deposit=<id>`, and reading the deposit then verifies it.
    `crypto`: show `pay.amount` of `pay.asset` on `pay.chain` to `pay.address` (with
    `pay.memo` when set); the user can leave, and Stark checks the deposit on its own.
    Read GET /v1/wallet/deposits/{id} when they come back. The balance moves when the
    deposit reads `credited`."""
    return JSONResponse(
        module.deposits.start(account.id, dto.amount_ngn, dto.method, dto.asset_id),
        status_code=201,
    )


@router.post("/deposits/preview", response_model=DepositPreviewResultDto,
             summary="Price a crypto deposit from either side, reserving nothing",
             responses=ApiResponses.errors("bad_amount", "below_minimum", "bad_asset",
                                           "not_available", "provider_failed"))
def preview_deposit(dto: DepositPreviewDto, _account: AuthUser, module: Module) -> JSONResponse:
    """For the Add money card as the user types. Give `amount_ngn` to see what to send,
    or `amount_in` to see what it credits. Starting the deposit still locks its own
    quote, so `amount_in` can differ by a hair from a preview made from the naira side.
    `below_minimum` names 1Click's current floor, in naira, when it refuses a small swap."""
    return JSONResponse(module.deposits.preview(dto.asset_id, dto.amount_ngn, dto.amount_in))


@router.get("/deposits", response_model=list[DepositDto], summary="Recent deposits")
def deposits(account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse(module.deposits.recent(account.id))


@router.get("/deposits/{deposit_id}", response_model=DepositDto,
            summary="One deposit, checked with its rail if still open",
            responses=ApiResponses.errors("unknown_deposit"))
def deposit(deposit_id: str, account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse(module.deposits.get(account.id, deposit_id))


@router.post("/deposits/{deposit_id}/tx", response_model=DepositDto,
             summary="Tell Stark the transaction that paid a crypto deposit",
             responses=ApiResponses.errors("unknown_deposit", "bad_method", "bad_tx"))
def deposit_tx(deposit_id: str, dto: DepositTxDto, account: AuthUser,
               module: Module) -> JSONResponse:
    """Optional: it only makes the deposit get noticed sooner."""
    return JSONResponse(module.deposits.submit_tx(account.id, deposit_id, dto.tx_hash))


# --- taking money out ---------------------------------------------------------------


@router.get("/banks", response_model=list[BankDto], summary="Banks a withdrawal can go to",
            responses=ApiResponses.errors("not_available"))
def banks(_account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse(module.withdrawals.banks())


@router.post("/bank-accounts/resolve", response_model=ResolvedAccountDto,
             summary="The name on a bank account, before sending to it",
             responses=ApiResponses.errors("bad_account", "too_many_lookups",
                                           "not_available", "provider_failed"))
def resolve(dto: BankAccountDto, account: AuthUser, module: Module) -> JSONResponse:
    """Limited per account per day (`too_many_lookups`, 429): the name is someone's
    personal data."""
    return JSONResponse(module.withdrawals.lookup(account.id, dto.bank_code,
                                                  dto.account_number))


@router.post("/withdraw", status_code=201, response_model=WithdrawalDto,
             summary="Send money to a bank account",
             responses=ApiResponses.errors("bad_amount", "bad_account", "paused",
                                           "daily_limit", "funds_on_hold",
                                           "insufficient_balance", "not_available",
                                           "provider_failed"))
def withdraw(dto: WithdrawDto, account: AuthUser, module: Module) -> JSONResponse:
    """The money leaves the balance at once. `sending` until Flutterwave takes the
    transfer, then `processing`, then `paid` — or `returned`, and the money comes
    back to the balance. Refused while paused, over the account's daily bank total,
    and for money a card added until its hold passes (`funds_on_hold`)."""
    return JSONResponse(
        module.withdrawals.request(account.id, dto.amount_ngn, dto.bank_code,
                                   dto.account_number),
        status_code=201,
    )


@router.post("/withdraw/crypto", status_code=201, response_model=WithdrawalDto,
             summary="Send money out as crypto",
             responses=ApiResponses.errors("bad_amount", "bad_asset", "bad_address",
                                           "over_limit", "daily_limit", "paused",
                                           "funds_on_hold",
                                           "insufficient_balance", "not_available",
                                           "provider_failed"))
def withdraw_crypto(dto: CryptoWithdrawDto, account: AuthUser, module: Module) -> JSONResponse:
    """The naira leaves the balance at once and becomes USDC at Stark's rate, which
    NEAR Intents swaps into `asset_id` and delivers to `address`. `crypto.amount` is
    what arrives. `sending` → `processing` (the swap is running) → `paid`, or
    `returned` with the money back in the balance."""
    return JSONResponse(
        module.crypto_withdrawals.request(account.id, dto.amount_ngn, dto.asset_id,
                                          dto.address),
        status_code=201,
    )


@router.get("/withdrawals", response_model=list[WithdrawalDto],
            summary="Recent withdrawals")
def withdrawals(account: AuthUser, module: Module) -> JSONResponse:
    return JSONResponse(module.withdrawals.recent(account.id))
