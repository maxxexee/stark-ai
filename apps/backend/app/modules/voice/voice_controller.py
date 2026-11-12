from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from app.common.api_error import ApiError
from app.decorators.api_responses import ApiResponses
from app.decorators.auth_user import AuthUser
from app.decorators.inject_module import Module
from app.modules.voice.dtos.speak_dto import SpeakDto
from app.modules.voice.dtos.speak_ticket_dto import SpeakTicketDto
from app.modules.voice.dtos.speech_dto import SpeechDto
from app.modules.voice.dtos.voice_dto import VoiceDto
from app.modules.voice.dtos.voice_reply_dto import VoiceReplyDto
from app.modules.voice.speak_ticket import SpeakTickets
from app.modules.voice.voice_request import VoiceRequest

router = APIRouter(tags=["Voice"], responses=ApiResponses.errors("unauthorized"))

# The body is read raw (a multipart clip's bytes do not survive form decoding), so
# FastAPI cannot infer it; it is documented here instead.
_VOICE_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": VoiceDto.model_json_schema()},
            "multipart/form-data": {"schema": {
                "type": "object",
                "properties": {
                    "audio": {"type": "string", "format": "binary"},
                    "audio_type": {"type": "string"},
                    "speak": {"type": "boolean"},
                },
            }},
        },
    },
}


@router.post("/v1/voice", response_model=VoiceReplyDto, openapi_extra=_VOICE_BODY,
             summary="One spoken or typed turn",
             responses=ApiResponses.errors("bad_audio", "audio_too_large"))
async def voice(request: Request, account: AuthUser, module: Module) -> JSONResponse:
    """The wake gate is server-side: no "stark", `ignored: true`. A clip that is not
    understood comes back `stt: failed` with an empty transcript, never a guess.
    Send `speak: false` to get the words first and speak them with `POST /v1/speak`."""
    parsed = VoiceRequest.parse(await VoiceRequest.read_body(request.stream()),
                                request.headers.get("content-type", ""))
    return JSONResponse(await run_in_threadpool(module.voice.respond, account.id, parsed))


@router.post("/v1/speak", response_model=SpeechDto, summary="Speak text you already have",
             responses=ApiResponses.errors("bad_text", "rate_limited"))
def speak(dto: SpeakDto, account: AuthUser, module: Module) -> JSONResponse:
    module.speak_limit.hit(account.id)
    return JSONResponse(module.voice.speak(dto.text))


@router.post("/v1/speak/ticket", response_model=SpeakTicketDto,
             summary="A short-lived link that streams this text",
             responses=ApiResponses.errors("bad_text", "rate_limited"))
def speak_ticket(dto: SpeakDto, account: AuthUser, module: Module) -> JSONResponse:
    """For an `<audio>` element, which cannot send `Authorization`. The ticket opens
    only `GET /v1/speak/stream` for this text, for two minutes; the text stays on
    the server, so neither it nor the session token lands in a URL."""
    text = dto.text.strip()
    if not text:
        raise ApiError(400, "bad_text", "`text` is required.")
    module.speak_limit.hit(account.id)
    ticket = module.speak_tickets.issue(account.id, text)
    return JSONResponse({"url": f"/v1/speak/stream?ticket={ticket}",
                         "expires_in_seconds": SpeakTickets.TTL_SECONDS})


@router.get("/v1/speak/stream", summary="Speak, streamed as it is produced",
            response_class=StreamingResponse,
            responses={200: {"content": {"audio/mpeg": {}, "audio/wav": {}}},
                       **ApiResponses.errors("no_voice", "rate_limited")})
def speak_stream(
    module: Module,
    ticket: str = Query("", description="From `POST /v1/speak/ticket`. The only "
                                        "credential this route accepts."),
) -> StreamingResponse:
    """No `Content-Length`: the body is deliberately not buffered."""
    issued = module.speak_tickets.redeem(ticket)
    module.speak_limit.hit(issued.account_id)
    content_type, chunks = module.voice.stream(issued.text)
    return StreamingResponse(chunks, media_type=content_type,
                             headers={"Cache-Control": "no-store"})
