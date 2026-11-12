"""One voice turn for any door, and speaking text the client already has.

The wake gate sits here, in front of the agent, so Telegram and the phone share
one implementation. Audio is checked before `transcript_hint`, so a client that can
record never has to pretend; a transcript is never invented, and the agent is never
called on a guess.
"""

from __future__ import annotations

import base64
import itertools
import time
from typing import Any, Iterator, Optional

from app.common.api_error import ApiError
from app.modules.account.account_service import AccountService
from app.modules.turnlog import turnlog
from app.modules.turnlog.turn_logger import TurnLogger
from app.modules.voice import stt, tts, wake
from app.modules.voice.voice_request import VoiceRequest

# Why a clip came back unheard. Both are honest: one says what is missing, one asks
# for the words again. Neither pretends the speech was understood.
VOICE_UNHEARD = {
    stt.NO_KEY: "I can't hear voice yet, this server has no speech key. Type instead.",
    stt.FAILED: "I didn't catch that. Say it again?",
}
DEFAULT_HINT = "hello stark what's my light bill"


class VoiceService:
    def __init__(self, accounts: AccountService) -> None:
        self.accounts = accounts

    def respond(self, account_id: str, request: VoiceRequest) -> dict[str, Any]:
        agent = self.accounts.state(account_id).agent
        clip, mime = request.clip, request.mime
        started = time.perf_counter()
        wants_speak = request.wants_speech
        transcript: Optional[str] = None
        stt_reason: Optional[str] = None
        ms_stt = 0
        if clip is not None:
            # `hear`, not `transcribe`: a browser records WebM/MP4, which the
            # provider refuses as a container, so stt decodes those to WAV first.
            since = time.perf_counter()
            transcript, stt_reason = stt.hear(clip, mime=mime)
            ms_stt = TurnLogger.ms(since)
            if transcript is None:
                unheard = VOICE_UNHEARD.get(stt_reason, VOICE_UNHEARD[stt.FAILED])
                TurnLogger.turn(account_id=account_id, agent=agent, outcome="unheard",
                                clip=clip, mime=mime,
                                stt=stt_reason, payload={"reply": unheard},
                                speak=wants_speak,
                                ms=TurnLogger.timings(started, has_clip=True, stt_ms=ms_stt))
                return {"transcript": "", "ignored": False, "reply": unheard,
                        "token": None, "receipt_id": None, "audio": None,
                        "stt": stt_reason}
        if transcript is None:
            transcript = str(request.fields.get("transcript_hint") or DEFAULT_HINT)

        # One wake rule for every door (wake.py): a recognizer's "start" or "stock"
        # for a spoken "stark" is still an address.
        said = wake.wake_attempt(transcript)
        if said is None:
            TurnLogger.turn(account_id=account_id, agent=agent, outcome="asleep",
                            clip=clip, mime=mime,
                            heard=transcript, stt=stt_reason, speak=wants_speak,
                            ms=TurnLogger.timings(started, has_clip=clip is not None,
                                                  stt_ms=ms_stt))
            return {"transcript": transcript, "ignored": True, "reply": None,
                    "token": None, "receipt_id": None, "audio": None,
                    **({"stt": stt_reason} if stt_reason else {})}

        since = time.perf_counter()
        reply = agent.respond(said)
        payload = reply.as_voice_payload(transcript)
        ms_agent = TurnLogger.ms(since)
        if stt_reason:
            payload["stt"] = stt_reason
        ms_tts = 0
        wav = None
        if wants_speak:
            since_tts = time.perf_counter()
            wav, _why = tts.synthesize(payload["reply"])
            ms_tts = TurnLogger.ms(since_tts)
        payload["audio"] = self._data_url(wav)
        timings = TurnLogger.timings(started, has_clip=clip is not None, stt_ms=ms_stt)
        timings["agent"] = ms_agent
        if wants_speak:
            timings["tts"] = ms_tts
        TurnLogger.turn(account_id=account_id, agent=agent, outcome="answered",
                        clip=clip, mime=mime,
                        heard=transcript, said=said, stt=stt_reason, payload=payload,
                        speak=wants_speak, ms=timings, conversation=reply.conversation)
        return payload

    def speak(self, text: str) -> dict[str, Optional[str]]:
        """Always `audio: null` rather than an error when voice is off."""
        text = text.strip()
        if not text:
            raise ApiError(400, "bad_text", "`text` is required.")
        since = time.perf_counter()
        wav, why = tts.synthesize(text)
        turnlog.record(turnlog.speak(text=text, ms=TurnLogger.ms(since), reason=why,
                                     stream=False, provider=self._provider(why)))
        return {"audio": self._data_url(wav)}

    @staticmethod
    def stream(text: str) -> tuple[str, Iterator[bytes]]:
        """`(content_type, chunks)` for a player that starts on partial data.

        Peeks at the first chunk: a key that cannot pay for the call, or one that is
        not there, must not reach the client as a 200 of nothing. Falls back to a
        whole buffered clip, and refuses with 503 when no voice exists at all, so
        the client keeps the text it already shows.
        """
        text = text.strip()
        if not text:
            raise ApiError(400, "bad_text", "`text` is required.")
        since = time.perf_counter()
        chunks = tts.stream_elevenlabs(text)
        first = next(chunks, None)
        if first is not None:
            turnlog.record(turnlog.speak(text=text, ms=TurnLogger.ms(since), reason=tts.OK,
                                         stream=True, provider="elevenlabs"))
            return "audio/mpeg", itertools.chain([first], chunks)
        wav, why = tts.synthesize(text)
        turnlog.record(turnlog.speak(text=text, ms=TurnLogger.ms(since), reason=why,
                                     stream=True, provider="elevenlabs" if wav else None))
        if wav:
            return "audio/wav", iter([wav])
        raise ApiError(503, "no_voice", "No voice provider is available.")

    @staticmethod
    def _data_url(wav: Optional[bytes]) -> Optional[str]:
        return "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii") if wav else None

    @staticmethod
    def _provider(why: str) -> str:
        """The voice that spoke, or `why` when nothing did."""
        return "elevenlabs" if why == tts.OK else why
