"""The language model behind the agent: NEAR AI's OpenAI-compatible chat endpoint.

`NearAiModel` is the only backend. Tests drive the agent loop with scripted models
that implement the same `Model` protocol.
"""

from __future__ import annotations

import http.client
import json
import os
import select
import ssl
import threading
import time
import urllib.error
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

NEAR_AI_BASE = os.environ.get("NEAR_AI_BASE_URL") or "https://cloud-api.near.ai"
# Tool-capable and on NEAR's own fleet. `openai/gpt-5-nano` is Incognito (no
# end-to-end TEE) and was `is_ready: false` when checked 2026-10-22.
#
# Measured 2026-11-13 on the real agent loop, three turns each, same prompt:
# Qwen/Qwen3.8-27B took 17.9s a turn and single turns reached 81s, which is the
# wait the wall phone was showing. Qwen/Qwen3.6-35B-A3B-FP8 is a 3B-active
# mixture of experts and took 1.4s. On six probe utterances (a question, a
# payment, an over-cap payment, a deposit, a greeting) the two made the same
# tool calls; the 3.6 model also told the user the meter token instead of the
# reference number. Set STARK_MODEL to pin another one.
#
# STARK_MODEL wins over NEAR_AI_MODEL because the production machine identity
# reads Infisical and cannot write it, so a deploy is the only way to change the
# model without someone editing the secret by hand. The secret stays as the
# fallback for a host that sets neither.
NEAR_AI_MODEL = (os.environ.get("STARK_MODEL")
                 or os.environ.get("NEAR_AI_MODEL")
                 or "Qwen/Qwen3.6-35B-A3B-FP8")


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }

    @staticmethod
    def parse_arguments(value: Any) -> dict:
        """The model's `arguments`: a JSON string by the protocol, an object from
        some providers. Anything unreadable is no arguments, and the tool then
        refuses on its own required fields."""
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


@dataclass
class ModelTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def assistant_message(self) -> dict:
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [call.as_dict() for call in self.tool_calls],
        }


class Model(Protocol):
    name: str

    def turn(self, messages: list[dict], tools: list[dict]) -> ModelTurn: ...


class _Connection:
    """One keep-alive HTTPS connection to the model host, and its lock."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.conn = http.client.HTTPSConnection(
            host, port, timeout=timeout, context=ssl.create_default_context()
        )
        self.lock = threading.Lock()
        # Set by `NearAiModel._acquire`; carried into the retry note.
        self.reused = False


class NearAiModel:
    """NEAR AI's OpenAI-compatible chat endpoint.

    The only model backend. The request/response handling is deliberately narrow:
    one POST, tool calls only. Without a key it is still built, so an account's
    routes work, and every turn fails before any request — the agent turns that
    into a spoken "lost connection" and pays nothing.

    Connections are kept alive and reused. A TLS handshake to the model costs
    0.68s from Lagos (measured 2026-11-13) and a call on an open connection 0.40s,
    so a fresh connection per turn paid that handshake again for every model
    round — twice on any turn that calls a tool. The pool is the same borrow and
    return the database layer uses, for the same reason: the server handles each
    request on a new thread, so a thread-local connection would be a new
    handshake every time.
    """

    name = "near-ai"
    MAX_IDLE = 8

    # The builder's egress drops TLS mid-response: measured 2026-10-24 on
    # geddon.hellostark.xyz, [SSL: UNEXPECTED_EOF_WHILE_READING] arrived on about
    # one turn in 18 and the server handed the client a 500 with nothing to say.
    # A retry costs nothing when the network is healthy and turns a dropped
    # reply into the answer that was asked for.
    ATTEMPTS = 3
    RETRY_DELAYS = (0.3, 0.9)
    # One call's ceiling, in seconds. Three attempts on a 10s socket timeout could
    # hold a turn for 31.2s (measured 2026-11-13, `agent: 31890` in the turn log).
    # Each attempt borrows what is left of the budget, so a socket that never
    # answers cannot stack three full timeouts. It must leave a whole timeout for
    # the retry: at 12s, one stall left the retry 2s, which cannot carry a real
    # answer, and a slow round became "lost connection" instead of a second try.
    RETRY_BUDGET_SECONDS = 25.0
    # Below this an attempt would time out before the request could finish.
    MIN_ATTEMPT_SECONDS = 1.0

    def __init__(
        self,
        api_key: str | None = None,
        model: str = NEAR_AI_MODEL,
        base_url: str = NEAR_AI_BASE,
        # One stalled round used to sit on the 30s socket timeout before the
        # retry answered, and the turn was 31.9s of silence (measured 2026-11-13,
        # turn log, `agent: 31890`). A reply that is coming takes 1 to 4s and
        # the slowest measured round was 7.6s, so 10s is generous and turns a
        # stall into a retry the user can wait out.
        timeout: int = 10,
    ):
        self.api_key = api_key or os.environ.get("NEAR_AI_API_KEY")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        endpoint = urlsplit(self.base_url)
        self._host = endpoint.hostname or "cloud-api.near.ai"
        self._port = endpoint.port or 443
        self._path = (endpoint.path.rstrip("/") or "") + "/v1/chat/completions"
        self._idle: list[_Connection] = []
        self._mutex = threading.Lock()
        # The server answers each request on its own thread, so the retry record
        # for the turn in flight is per thread, like the connection pool is not.
        self._local = threading.local()

    def begin_turn(self) -> None:
        """Start a fresh retry record for the turn about to run."""
        self._local.events = []

    def retries(self) -> list[dict]:
        """Attempts that failed and went to a retry, in the order they happened."""
        return list(getattr(self._local, "events", []))

    def _note_retry(self, attempt: int, started: float, error: BaseException,
                    reused: bool | None) -> None:
        """Keep the reason, not just the count: a stall and a reset look the same
        in the timing and completely different in the sentence.

        `reused` is the deciding datum for a read timeout: a pooled connection
        that the far end has already forgotten looks exactly like a provider
        that took too long, and only the pool state tells them apart.
        """
        events = getattr(self._local, "events", None)
        if events is None:
            self._local.events = events = []
        events.append({
            "attempt": attempt + 1,
            "ms": int((time.perf_counter() - started) * 1000),
            "reused": reused,
            "why": str(error)[:120],
        })

    # --- connection ----------------------------------------------------------

    def _acquire(self, timeout: float | None = None) -> _Connection:
        """A pooled connection only after it proves it is still there.

        The model host reaps idle keep-alive sockets before its own advertised
        timeout, and a POST written into one of those is never answered: the
        read sat for the whole timeout and the turn cost 12.5s (measured
        2026-11-13, `reused: true`, `The read operation timed out`). A closed
        socket is readable with nothing to read, so `_alive` sees the FIN and
        the pool drops it instead of lending it out.

        `timeout` is this attempt's share of the retry budget; the default is
        the timeout the model was built with.
        """
        limit = self.timeout if timeout is None else timeout
        while True:
            with self._mutex:
                if not self._idle:
                    break
                wire = self._idle.pop()
            if self._alive(wire):
                wire.reused = True
                self._retime(wire, limit)
                return wire
            self._close(wire)
        wire = _Connection(self._host, self._port, limit)
        wire.reused = False
        return wire

    @staticmethod
    def _alive(wire: _Connection) -> bool:
        """Whether an idle connection can still carry a request.

        An idle keep-alive socket is readable only when the far end has said
        something unasked for, which in practice means it closed. So silence is
        the healthy answer, and it is the only test that works the same on the
        TLS socket `http.client` holds (a peek would raise there). Zero timeout,
        non-destructive, and anything that cannot answer counts as dead.
        """
        sock = getattr(getattr(wire, "conn", None), "sock", None)
        if sock is None:
            return False
        try:
            readable, _, _ = select.select([sock], [], [], 0)
        except (OSError, ValueError):
            return False
        return not readable

    @staticmethod
    def _retime(wire: _Connection, timeout: float) -> None:
        """Apply this attempt's timeout to a socket that is already open."""
        sock = getattr(getattr(wire, "conn", None), "sock", None)
        if sock is None:
            return
        try:
            if sock.gettimeout() != timeout:
                sock.settimeout(timeout)
        except (OSError, ValueError):
            pass

    def _release(self, wire: _Connection) -> None:
        with self._mutex:
            if len(self._idle) < self.MAX_IDLE:
                self._idle.append(wire)
                return
        self._close(wire)

    @staticmethod
    def _close(wire: _Connection) -> None:
        try:
            wire.conn.close()
        except Exception:
            pass

    def turn(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        if not self.api_key:
            raise RuntimeError("NEAR_AI_API_KEY is not set")
        payload = {"model": self.model, "messages": messages, "temperature": 0}
        # A question is offered no tools. Some providers (DeepSeek on NEAR AI) reject
        # `tools: []` with a 400, so the field is left out rather than sent empty.
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        body = self._post(payload)

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("NEAR AI returned no choices")
        message = choices[0].get("message") or {}

        calls = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            calls.append(
                ToolCall(
                    name=function.get("name", ""),
                    arguments=ToolCall.parse_arguments(function.get("arguments")),
                    id=raw.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                )
            )
        return ModelTurn(content=message.get("content"), tool_calls=calls)

    def _post(self, payload: dict) -> dict:
        """One completion, retried only where the failure is the network's.

        A 4xx means the request itself is wrong (bad key, bad shape): retrying
        is just a slower failure, so it raises at once. Everything else — a
        dropped TLS handshake, a reset socket, a body cut in half, 429, 5xx —
        gets `ATTEMPTS` goes before it becomes a real error.

        A pooled connection can be reaped while it sits idle; the retry then
        runs on a fresh one, which is why the borrow happens inside the loop.
        """
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        last: RuntimeError | None = None
        began = time.perf_counter()
        for attempt in range(self.ATTEMPTS):
            left = self.RETRY_BUDGET_SECONDS - (time.perf_counter() - began)
            if left < self.MIN_ATTEMPT_SECONDS:
                break
            started = time.perf_counter()
            wire: _Connection | None = None
            retryable = False
            reused: bool | None = None
            try:
                wire = self._acquire(min(self.timeout, left))
                reused = getattr(wire, "reused", None)
                with wire.lock:
                    wire.conn.request("POST", self._path, body, headers)
                    response = wire.conn.getresponse()
                    status = response.status
                    raw = response.read()
                self._release(wire)
                wire = None
            except (http.client.HTTPException, OSError, urllib.error.URLError) as err:
                # ssl.SSLEOFError, a reset connection, a truncated body.
                if wire is not None:
                    self._close(wire)
                    wire = None
                last, retryable = RuntimeError(f"Could not reach NEAR AI: {err}"), True
            else:
                detail = raw.decode("utf-8", "replace")[:300]
                if status == 429 or status >= 500:
                    last, retryable = RuntimeError(
                        f"NEAR AI returned HTTP {status}: {detail}"), True
                elif status >= 400:
                    raise RuntimeError(f"NEAR AI returned HTTP {status}: {detail}")
                else:
                    try:
                        return json.loads(raw or b"{}")
                    except json.JSONDecodeError as err:
                        last, retryable = RuntimeError(
                            f"Could not reach NEAR AI: {err}"), True
            if not retryable:
                break
            if last is not None:
                self._note_retry(attempt, started, last, reused)
            if attempt < self.ATTEMPTS - 1:
                time.sleep(self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)])
        raise last if last else RuntimeError("NEAR AI failed without a reason")

