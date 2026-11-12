from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.decorators.api_responses import ApiResponses
from app.decorators.auth_user import AuthUser
from app.decorators.inject_module import Module
from app.modules.telegram.dtos.link_code_dto import LinkCodeDto
from app.modules.telegram.dtos.linked_chat_dto import LinkedChatDto
from app.modules.telegram.dtos.unlinked_chat_dto import UnlinkedChatDto
from app.modules.telegram.dtos.webhook_result_dto import WebhookResultDto

router = APIRouter(tags=["Telegram"])


@router.post("/v1/link/code", response_model=LinkCodeDto,
             summary="Mint a code that links a chat to this account",
             responses=ApiResponses.errors("unauthorized", "not_configured"))
def link_code(account: AuthUser, module: Module) -> JSONResponse:
    """Single-use, ten minutes. The server keeps only a hash, so this response is
    the one time the code is readable. `deep_link` is null without a bot token."""
    return JSONResponse(module.telegram.link_code(account.id))


@router.get("/v1/link/identities", response_model=list[LinkedChatDto],
            summary="The chats linked to this account",
            responses=ApiResponses.errors("unauthorized"))
def linked_chats(account: AuthUser, module: Module) -> JSONResponse:
    """Oldest first. A chat the owner does not recognise is removed with `DELETE`."""
    return JSONResponse(module.telegram.linked_chats(account.id))


@router.delete("/v1/link/identities/{channel}/{channel_user_id}",
               response_model=UnlinkedChatDto, summary="Remove a linked chat",
               responses=ApiResponses.errors("unauthorized", "unknown_identity"))
def unlink_chat(channel: str, channel_user_id: str, account: AuthUser,
                module: Module) -> JSONResponse:
    """Only this account's own chats: any other id is `unknown_identity`. The chat
    can no longer see or move money from the next message on."""
    return JSONResponse(module.telegram.unlink_chat(account.id, channel, channel_user_id))


@router.post("/v1/tg/webhook", response_model=WebhookResultDto,
             summary="Telegram's update push (Telegram calls this, not the app)",
             responses=ApiResponses.errors("webhook_unconfigured", "webhook_unverified",
                                           "bad_update"))
async def webhook(
    request: Request,
    module: Module,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> JSONResponse:
    """No bearer token: Telegram cannot carry one. The secret header is checked in
    constant time **before** the body is parsed, and every update is refused while
    the bot is unconfigured."""
    raw = await request.body()
    return JSONResponse(await run_in_threadpool(
        module.telegram.webhook, raw, x_telegram_bot_api_secret_token
    ))
