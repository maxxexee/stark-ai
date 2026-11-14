"""Keep-alive HTTP connections to the two hosts a voice turn talks to.

A TLS handshake from Lagos costs 0.43s to `cloud-api.near.ai` and 0.39s to
`api.elevenlabs.io` (measured 2026-11-13); a call on an open connection costs a
fraction of that. A voice turn pays both, once to hear the user and once to
answer, so the two handshakes were around 0.8s of a 4.8s turn — the same waste
`database.neon.Database` and `agent.model.NearAiModel` already pool away.

Borrow and return rather than thread-local: `ThreadingHTTPServer` runs every
request on a new thread, so a connection held per thread would be a handshake
every time.

`send` is for one request and its whole body. `hold` is for a response that is
read as it arrives: the connection stays out of the pool until the caller hands
it back, and is dropped instead when the server closes it or the read fails.
"""

from __future__ import annotations

import http.client
import ssl
import threading
from urllib.parse import urlsplit


class _Wire:
    """One connection to one host, and the lock that lends it to a thread."""

    def __init__(self, scheme: str, host: str, port: int | None, timeout: float) -> None:
        if scheme == "http":
            self.conn = http.client.HTTPConnection(host, port, timeout=timeout)
        else:
            self.conn = http.client.HTTPSConnection(
                host, port, timeout=timeout, context=ssl.create_default_context()
            )
        self.lock = threading.Lock()


class KeepAlive:
    """A small pool of keep-alive connections for one base URL."""

    MAX_IDLE = 8
    _pools: dict[tuple[str, str, int | None], "KeepAlive"] = {}
    _pools_mutex = threading.Lock()

    def __init__(self, base: str, *, timeout: float = 30.0) -> None:
        endpoint = urlsplit(base)
        self.scheme = endpoint.scheme or "https"
        self.host = endpoint.hostname or ""
        self.port = endpoint.port
        self.prefix = endpoint.path.rstrip("/")
        self.timeout = timeout
        self._idle: list[_Wire] = []
        self._mutex = threading.Lock()

    @classmethod
    def for_base(cls, base: str, *, timeout: float = 30.0) -> "KeepAlive":
        """The pool for this base. A different host, or port, is a different pool."""
        endpoint = urlsplit(base)
        key = (endpoint.scheme or "https", endpoint.hostname or "", endpoint.port)
        with cls._pools_mutex:
            pool = cls._pools.get(key)
            if pool is None:
                pool = cls._pools[key] = cls(base, timeout=timeout)
            return pool

    # --- connection ----------------------------------------------------------

    def borrow(self) -> _Wire:
        with self._mutex:
            if self._idle:
                return self._idle.pop()
        return _Wire(self.scheme, self.host, self.port, self.timeout)

    def release(self, wire: _Wire) -> None:
        with self._mutex:
            if len(self._idle) < self.MAX_IDLE:
                self._idle.append(wire)
                return
        self.drop(wire)

    @staticmethod
    def drop(wire: _Wire) -> None:
        try:
            wire.conn.close()
        except Exception:
            pass

    # --- requests ------------------------------------------------------------

    def send(self, method: str, path: str, body: bytes | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        """One request, the whole body back. Returns `(status, body)`.

        A pooled connection can be reaped while it sits idle, so a stale one is
        retried once on a fresh connection; a second failure is real.
        """
        target = self.prefix + path
        error: Exception | None = None
        for attempt in (0, 1):
            wire = self.borrow()
            try:
                with wire.lock:
                    wire.conn.request(method, target, body, headers or {})
                    response = wire.conn.getresponse()
                    status = response.status
                    raw = response.read()
                    reusable = not response.will_close
                if reusable:
                    self.release(wire)
                else:
                    self.drop(wire)
                return status, raw
            except (http.client.HTTPException, OSError) as err:
                self.drop(wire)
                error = err
        raise error if error else RuntimeError("request failed without a reason")

    def hold(self, method: str, path: str, body: bytes | None = None,
             headers: dict[str, str] | None = None
             ) -> tuple[_Wire, http.client.HTTPResponse]:
        """One request whose response is read as it arrives.

        The caller owns the connection until it calls `release` or `drop`.
        """
        target = self.prefix + path
        error: Exception | None = None
        for attempt in (0, 1):
            wire = self.borrow()
            try:
                wire.conn.request(method, target, body, headers or {})
                return wire, wire.conn.getresponse()
            except (http.client.HTTPException, OSError) as err:
                self.drop(wire)
                error = err
        raise error if error else RuntimeError("request failed without a reason")
