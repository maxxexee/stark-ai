"""Reading a `/v1/voice` upload: JSON with base64 `audio`, or a multipart file.

Two shapes on purpose — base64 JSON for `packages/api`, a multipart file for
anything that streams one — so one broken encoding cannot mute a whole door. The
route reads the raw body itself, because a multipart clip's bytes cannot survive
being decoded as form text.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional
from urllib.parse import parse_qs

from app.common.api_error import ApiError

MAX_AUDIO_BYTES = 8 * 1024 * 1024   # a minute of clipped speech, generously
# The largest clip as base64 (4/3 of it) plus the JSON or multipart around it.
MAX_BODY_BYTES = 12 * 1024 * 1024
_TOO_LARGE = "That clip is too long. Keep it under a minute."


@dataclass(frozen=True)
class VoiceRequest:
    fields: dict[str, Any]
    clip: Optional[bytes]
    mime: Optional[str]

    @property
    def wants_speech(self) -> bool:
        """`speak` defaults to true; any false-y spelling a client sends turns it off."""
        return str(self.fields.get("speak", "true")).strip().lower() not in (
            "false", "0", "no", "off"
        )

    @staticmethod
    async def read_body(chunks: AsyncIterator[bytes]) -> bytes:
        """The request body, refused as soon as it passes `MAX_BODY_BYTES`.

        Read as a stream rather than `request.body()`, which would hold a body of
        any size in memory before the clip's own limit could look at it.
        """
        body = bytearray()
        async for chunk in chunks:
            body += chunk
            if len(body) > MAX_BODY_BYTES:
                raise ApiError(413, "audio_too_large", _TOO_LARGE)
        return bytes(body)

    @classmethod
    def parse(cls, raw: bytes, content_type: str) -> "VoiceRequest":
        fields = cls._fields(raw, content_type)
        clip, mime = cls._audio(fields, raw, content_type)
        return cls(fields=fields, clip=clip, mime=mime)

    @staticmethod
    def _fields(raw: bytes, content_type: str) -> dict[str, Any]:
        ctype = content_type.lower()
        if "application/json" in ctype:
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
        if "multipart/form-data" in ctype:
            return {
                m.group(1).decode(): m.group(2).decode("utf-8", "replace")
                for m in re.finditer(
                    rb'name="([^"]+)"(?:;\s*filename="[^"]*")?\r\n\r\n(.*?)\r\n--', raw, re.S
                )
            }
        return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}

    @staticmethod
    def _audio(fields: dict[str, Any], raw: bytes,
               content_type: str) -> tuple[Optional[bytes], Optional[str]]:
        field = str(fields.get("audio") or "")
        if field:
            b64 = field.split(",", 1)[1] if field.startswith("data:") else field
            try:
                data = base64.b64decode(b64, validate=True)
            except (ValueError, binascii.Error) as err:
                raise ApiError(400, "bad_audio", "`audio` must be base64 audio data.") from err
            if len(data) > MAX_AUDIO_BYTES:
                raise ApiError(413, "audio_too_large", _TOO_LARGE)
            return data, (str(fields.get("audio_type") or "").strip() or None)
        if "multipart/form-data" in content_type.lower():
            match = re.search(
                rb'name="audio"[^>]*?\r\n(?:Content-Type:\s*([^\r\n]+)\r\n)?\r\n(.*?)\r\n--',
                raw, re.S,
            )
            if match:
                data = match.group(2)
                if len(data) > MAX_AUDIO_BYTES:
                    raise ApiError(413, "audio_too_large", _TOO_LARGE)
                return data, ((match.group(1) or b"").decode() or None)
        return None, None
