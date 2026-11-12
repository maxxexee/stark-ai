"""Live-path tests: real HTTP over loopback sockets.

The rest of the suite mocks `_http` and `urlopen`, so the wire is never
exercised — auth headers, JSON bodies, multipart encoding and JSON-RPC framing
are only proven against fakes. These tests start a real `http.server` on
127.0.0.1 and point each client at it, so the code that will run with
credentials is tested without any credentials and without leaving the machine.

Covered:
  * Flutterwave POST /payments, /billers/{b}/items/{i}/payment, /transfers;
                GET /bills/{ref}, /transactions/verify_by_reference, /balances/NGN
  * NEAR AI     POST /v1/chat/completions (tool calls) and /v1/audio/transcriptions
  * NEAR RPC    block, view_access_key, broadcast_tx_commit, plus a borsh
                round-trip of the signed `pay()` envelope

Hermetic: every server binds 127.0.0.1 on port 0 and is stopped in tearDown.
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import unittest
import wave
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from app.modules.voice import audio
from app.modules.chain import near_tx
from app.modules.voice import stt
from app.modules.agent.agent import NEAR_AI_MODEL, NearAiModel
from app.modules.chain.vault_chain import VaultChain
from app.modules.flutterwave.flutterwave import FlutterwaveClient, FlutterwaveError

# --- harness ----------------------------------------------------------------


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    @property
    def json(self) -> dict:
        return json.loads(self.body.decode())

    def header(self, name: str) -> str | None:
        """Case-insensitive lookup: HTTP header names are not case sensitive."""
        target = name.lower()
        for key, value in self.headers.items():
            if key.lower() == target:
                return value
        return None

    @property
    def boundary(self) -> str | None:
        value = self.header("Content-Type") or ""
        if "boundary=" not in value:
            return None
        return value.split("boundary=", 1)[1]


def json_response(payload: object, status: int = 200) -> tuple[int, dict, bytes]:
    return status, {"Content-Type": "application/json"}, json.dumps(payload).encode()


def raw_response(body: bytes, status: int = 200) -> tuple[int, dict, bytes]:
    return status, {"Content-Type": "application/json"}, body


class FakeServer:
    """A real HTTP server that records requests and replays one responder."""

    def __init__(self, responder):
        self.requests: list[Recorded] = []
        self.responder = responder

        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                record = Recorded(
                    method=self.command,
                    path=self.path,
                    headers={k: v for k, v in self.headers.items()},
                    body=body,
                )
                outer.requests.append(record)
                status, headers, payload = outer.responder(record)
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _handle
            do_POST = _handle

            def log_message(self, *_args):  # keep the test output clean
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.stop()


class ServerTest(unittest.TestCase):
    responder = None

    def setUp(self):
        self.server = FakeServer(self._responder())

    def tearDown(self):
        self.server.stop()

    def _responder(self):
        """The class-level responder, or a 404 for tests that set their own."""
        make = self.responder
        if make is None:
            return lambda req: raw_response(b"{}", 404)
        return make()

    def restart(self, responder):
        """Replace the running server so a test can change its behaviour."""
        self.server.stop()
        self.server = FakeServer(responder)


# --- Flutterwave live transport ---------------------------------------------


def flutterwave_responder():
    """Routes on path, answering in Flutterwave's v3 envelope."""

    def respond(req: Recorded):
        path = req.path
        if path == "/payments":
            return json_response({"status": "success", "message": "Hosted Link",
                                  "data": {"link": "https://checkout.flutterwave.com/pay/x"}})
        if path.startswith("/transactions/verify_by_reference"):
            return json_response({"status": "error",
                                  "message": "No transaction was found for this id",
                                  "data": None}, 400)
        if path.startswith("/billers/"):
            return json_response({"status": "success", "message": "Bill payment successful",
                                  "data": {"tx_ref": "CF-FLYAPI-1", "reference": "2478",
                                           "amount": 5000, "code": "200"}})
        if path.startswith("/bills/"):
            return json_response({"status": "success", "data": {
                "status": "successful", "code": "200", "extra": "TOKEN1147"}})
        if path.startswith("/transfers?"):
            return json_response({"status": "success", "data": [
                {"id": 1, "reference": "someone-else"}, {"id": 2, "reference": "wd_1"}]})
        if path == "/balances/NGN":
            return json_response({"status": "success", "data": {
                "currency": "NGN", "available_balance": 2168880.75,
                "ledger_balance": 253125.82}})
        if path == "/broken":
            return raw_response(b"<html>gateway</html>", 502)
        return json_response({"status": "error", "message": "Url not found", "data": None},
                             400)

    return respond


class TestFlutterwaveLiveTransport(ServerTest):
    responder = staticmethod(flutterwave_responder)

    def client(self) -> FlutterwaveClient:
        return FlutterwaveClient("FLWSECK_TEST-abc-X", base_url=self.server.base)

    def test_checkout_sends_the_documented_body_and_bearer_key(self):
        link = self.client().create_checkout(
            tx_ref="dep_1", amount_ngn=20_000, email="ada@example.com", name="Ada",
            redirect_url="http://localhost:5174/wallet/add?deposit=dep_1",
            meta={"deposit_id": "dep_1"})
        self.assertEqual(link, "https://checkout.flutterwave.com/pay/x")
        req = self.server.requests[0]
        self.assertEqual((req.method, req.path), ("POST", "/payments"))
        self.assertEqual(req.header("Authorization"), "Bearer FLWSECK_TEST-abc-X")
        self.assertEqual(req.json["tx_ref"], "dep_1")
        self.assertEqual(req.json["amount"], 20_000)  # an integer, never a string
        self.assertEqual(req.json["currency"], "NGN")
        self.assertEqual(req.json["customer"], {"email": "ada@example.com", "name": "Ada"})

    def test_verify_by_reference_is_a_query_string(self):
        with self.assertRaises(FlutterwaveError) as caught:
            self.client().verify_by_reference("dep_1")
        self.assertEqual(self.server.requests[0].path,
                         "/transactions/verify_by_reference?tx_ref=dep_1")
        self.assertEqual(caught.exception.status, 400)
        self.assertFalse(caught.exception.transient)

    def test_a_bill_posts_to_its_biller_and_item(self):
        placed = self.client().pay_bill(biller_code="BIL113", item_code="UB159",
                                        customer_id="0101170026583", amount_ngn=5_000,
                                        reference="bill_1")
        self.assertEqual(placed["tx_ref"], "CF-FLYAPI-1")
        req = self.server.requests[0]
        self.assertEqual(req.path, "/billers/BIL113/items/UB159/payment")
        self.assertEqual(req.json, {"country": "NG", "customer_id": "0101170026583",
                                    "amount": 5_000, "reference": "bill_1"})

    def test_bill_status_is_verbose(self):
        self.assertEqual(self.client().bill_status("CF-FLYAPI-1")["extra"], "TOKEN1147")
        self.assertEqual(self.server.requests[0].path, "/bills/CF-FLYAPI-1?verbose=1")

    def test_a_transfer_is_found_only_by_its_exact_reference(self):
        client = self.client()
        self.assertEqual(client.find_transfer("wd_1")["id"], 2)
        self.assertEqual(self.server.requests[0].path, "/transfers?reference=wd_1")
        self.assertIsNone(client.find_transfer("wd_9"))

    def test_the_balance_is_whole_naira(self):
        self.assertEqual(self.client().ngn_balance(), 2_168_880)

    def test_a_non_json_gateway_error_is_transient(self):
        with self.assertRaises(FlutterwaveError) as caught:
            self.client()._request("GET", "/broken")
        self.assertEqual(caught.exception.status, 502)
        self.assertTrue(caught.exception.transient)

    def test_an_unreachable_host_is_transient(self):
        client = FlutterwaveClient("FLWSECK_TEST-abc-X", base_url="http://127.0.0.1:9")
        with self.assertRaises(FlutterwaveError) as caught:
            client.ngn_balance()
        self.assertEqual(caught.exception.status, 0)
        self.assertTrue(caught.exception.transient)


class TestNearAiModelLive(ServerTest):
    def model(self) -> NearAiModel:
        return NearAiModel(api_key="test-key", base_url=self.server.base)

    def test_turn_posts_openai_shaped_request_and_parses_tool_calls(self):
        self.restart(
            lambda req: json_response(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_abc",
                                        "type": "function",
                                        "function": {
                                            "name": "pay_bill",
                                            "arguments": json.dumps(
                                                {
                                                    "bill_id": "bill_home_meter",
                                                    "amount_ngn": 5000,
                                                }
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )
        )

        turn = self.model().turn([{"role": "user", "content": "top up"}], [{"type": "function"}])

        self.assertIsNone(turn.content)
        self.assertEqual(len(turn.tool_calls), 1)
        call = turn.tool_calls[0]
        self.assertEqual(call.name, "pay_bill")
        self.assertEqual(call.id, "call_abc")
        self.assertEqual(call.arguments, {"bill_id": "bill_home_meter", "amount_ngn": 5000})

        req = self.server.requests[0]
        self.assertEqual(req.path, "/v1/chat/completions")
        self.assertEqual(req.header("Authorization"), "Bearer test-key")
        self.assertEqual(
            req.json,
            {
                "model": NEAR_AI_MODEL,
                "messages": [{"role": "user", "content": "top up"}],
                "tools": [{"type": "function"}],
                "tool_choice": "auto",
                "temperature": 0,
            },
        )

    def test_plain_text_reply_has_no_tool_calls(self):
        self.restart(
            lambda req: json_response(
                {"choices": [{"message": {"content": "You have 64,200 naira."}}]}
            )
        )

        turn = self.model().turn([{"role": "user", "content": "balance"}], [])
        self.assertEqual(turn.content, "You have 64,200 naira.")
        self.assertEqual(turn.tool_calls, [])

    def test_tool_arguments_that_are_not_json_do_not_crash(self):
        self.restart(
            lambda req: json_response(
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {"function": {"name": "x", "arguments": "not json"}}
                                ]
                            }
                        }
                    ]
                }
            )
        )

        turn = self.model().turn([{"role": "user", "content": "?"}], [])
        self.assertEqual(turn.tool_calls[0].arguments, {})
        self.assertTrue(turn.tool_calls[0].id.startswith("call_"))

    def test_no_choices_raises(self):
        self.restart(lambda req: json_response({"choices": []}))
        with self.assertRaises(RuntimeError):
            self.model().turn([{"role": "user", "content": "?"}], [])

    def test_http_error_includes_status_and_body(self):
        self.restart(lambda req: raw_response(b'{"error":"rate limited"}', 429))
        with self.assertRaises(RuntimeError) as caught:
            self.model().turn([{"role": "user", "content": "?"}], [])
        self.assertIn("429", str(caught.exception))

    def test_missing_key_refuses_before_any_request(self):
        with mock.patch.dict(os.environ, {"NEAR_AI_API_KEY": ""}, clear=False):
            with self.assertRaises(RuntimeError):
                NearAiModel(api_key=None).turn([{"role": "user", "content": "?"}], [])
        self.assertEqual(self.server.requests, [])


# --- Whisper STT ------------------------------------------------------------


class TestSttLive(ServerTest):
    WAV = b"RIFF$\x00\x00\x00WAVEfmt " + b"\x00" * 16

    @staticmethod
    def real_wav(seconds: float = 0.2) -> bytes:
        """A decodable clip for the paths that must actually go through ffmpeg."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(b"\x00\x00" * int(16000 * seconds))
        return buf.getvalue()

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(stt, "NEAR_AI_BASE", self.server.base)
        patcher.start()
        self.addCleanup(patcher.stop)

    def restart(self, responder):
        super().restart(responder)
        # `transcribe` reads the module global at call time, so follow the server.
        stt.NEAR_AI_BASE = self.server.base

    def test_transcribe_posts_multipart_and_reads_text(self):
        self.restart(lambda req: json_response({"text": "  top up the house  "}))

        text, reason = stt.transcribe(self.WAV, api_key="test-key")

        self.assertEqual((text, reason), ("top up the house", stt.OK))
        req = self.server.requests[0]
        self.assertEqual(req.path, "/v1/audio/transcriptions")
        self.assertEqual(req.header("Authorization"), "Bearer test-key")
        self.assertIsNotNone(req.boundary)
        self.assertTrue(req.body.startswith(f"--{req.boundary}\r\n".encode()))
        self.assertIn(b'name="model"', req.body)
        self.assertIn(stt.NEAR_AI_STT_MODEL.encode(), req.body)
        self.assertIn(b'filename="audio.wav"', req.body)
        self.assertIn(b"Content-Type: audio/wav", req.body)
        self.assertIn(self.WAV, req.body)

    def test_transcribe_names_what_the_clip_really_is(self):
        self.restart(lambda req: json_response({"text": "top up the house"}))

        text, reason = stt.transcribe(self.WAV, api_key="k", mime="audio/webm")

        self.assertEqual((text, reason), ("top up the house", stt.OK))
        req = self.server.requests[0]
        self.assertIn(b'filename="audio.webm"', req.body)
        self.assertIn(b"Content-Type: audio/webm", req.body)

    def test_a_messy_mime_header_still_names_the_clip(self):
        self.restart(lambda req: json_response({"text": "hello"}))

        stt.transcribe(self.WAV, api_key="k", mime="audio/ogg; codecs=opus")

        req = self.server.requests[0]
        self.assertIn(b'filename="audio.ogg"', req.body)
        self.assertIn(b"Content-Type: audio/ogg\r\n", req.body)

    @unittest.skipUnless(audio.ffmpeg_available(), "ffmpeg not installed")
    def test_a_browser_webm_is_decoded_before_it_is_sent(self):
        # Measured 2026-10-24: the provider refuses WebM as a container (400
        # "Audio could not be processed"), whatever the filename says. The
        # dashboard records WebM, so `hear` must decode it to WAV — and what
        # goes on the wire must be named WAV, or Whisper refuses it again.
        self.restart(lambda req: json_response({"text": "top up the house"}))

        text, reason = stt.hear(self.real_wav(), api_key="k", mime="audio/webm")

        self.assertEqual((text, reason), ("top up the house", stt.OK))
        req = self.server.requests[0]
        self.assertIn(b'filename="audio.wav"', req.body)
        self.assertIn(b"Content-Type: audio/wav", req.body)
        self.assertTrue(req.body.split(b"\r\n\r\n")[-1].startswith(b"RIFF"))

    @unittest.skipUnless(audio.ffmpeg_available(), "ffmpeg not installed")
    def test_a_clip_ffmpeg_cannot_read_still_goes_to_whisper_unchanged(self):
        # Decoding failure must not fabricate words *or* silently drop the clip:
        # the provider sees exactly what the client sent and says it cannot hear
        # it, which is the honest answer.
        self.restart(lambda req: raw_response(b"not audio", 400))

        text, reason = stt.hear(b"this is not audio at all", api_key="k",
                                mime="audio/webm")

        self.assertEqual((text, reason), (None, stt.FAILED))
        req = self.server.requests[0]
        self.assertIn(b'filename="audio.webm"', req.body)

    def test_wav_is_sent_as_it_arrived(self):
        # The common path pays no ffmpeg cost at all.
        self.restart(lambda req: json_response({"text": "hello"}))

        stt.hear(self.WAV, api_key="k", mime="audio/wav")

        self.assertIn(b'filename="audio.wav"', self.server.requests[0].body)

    def test_empty_transcript_is_a_failure_not_a_guess(self):
        self.restart(lambda req: json_response({"text": "   "}))
        self.assertEqual(stt.transcribe(self.WAV, api_key="k"), (None, stt.FAILED))

    def test_unreachable_or_malformed_returns_failed(self):
        self.restart(lambda req: raw_response(b"not json", 500))
        self.assertEqual(stt.transcribe(self.WAV, api_key="k"), (None, stt.FAILED))

    def test_no_key_makes_no_network_call(self):
        with mock.patch.dict(os.environ, {"NEAR_AI_API_KEY": ""}, clear=False):
            self.assertEqual(stt.transcribe(self.WAV), (None, stt.NO_KEY))
        self.assertEqual(self.server.requests, [])


# --- NEAR RPC and the signed pay() round trip -------------------------------

BLOCK_HASH = bytes(range(32))
SIGNER = "agent.testnet"
VAULT = "vault.testnet"
SECRET = bytes(range(32))
KEY = near_tx.KeyPair.from_secret(SECRET)


class Reader:
    """A tiny borsh reader, so the encoder is checked against its own bytes."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.i = 0

    def take(self, n: int) -> bytes:
        if self.i + n > len(self.raw):
            raise AssertionError(f"truncated at {self.i}, wanted {n} more bytes")
        out = self.raw[self.i : self.i + n]
        self.i += n
        return out

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def u64(self) -> int:
        return int.from_bytes(self.take(8), "little")

    def u128(self) -> int:
        return int.from_bytes(self.take(16), "little")

    def string(self) -> str:
        return self.take(self.u32()).decode()

    def byte_vec(self) -> bytes:
        return self.take(self.u32())


# What `pay` returns, base64 of the contract's JSON, as `broadcast_tx_commit` reports it.
PAY_OUTCOME = base64.b64encode(
    b'{"payment_id":7,"meter":"0101170026583","amount_ngn":"5000","amount_usdc":"3333334",'
    b'"remaining_cap_ngn":"25000","settled":true}'
).decode()


def chain(rpc, *, broadcast: bool) -> VaultChain:
    """The agent key signs `pay` as the vault itself, so the signer is `VAULT`."""
    return VaultChain(rpc=rpc, funder_id=SIGNER, funder_key=KEY, agent_key=KEY,
                      treasury_id=SIGNER, usdc_id="usdc.testnet",
                      code="global:stark-vault.testnet",
                      storage_yocto=0, broadcast=broadcast)


def rpc_responder():
    def respond(req: Recorded):
        method = req.json["method"]
        if method == "block":
            return json_response(
                {
                    "jsonrpc": "2.0",
                    "id": "stark",
                    "result": {"header": {"hash": near_tx.b58encode(BLOCK_HASH)}},
                }
            )
        if method == "query":
            return json_response(
                {
                    "jsonrpc": "2.0",
                    "id": "stark",
                    "result": {"nonce": 41, "block_hash": near_tx.b58encode(BLOCK_HASH)},
                }
            )
        if method == "broadcast_tx_commit":
            return json_response(
                {
                    "jsonrpc": "2.0",
                    "id": "stark",
                    "result": {"status": {"SuccessValue": PAY_OUTCOME}},
                }
            )
        return json_response({"jsonrpc": "2.0", "id": "stark", "error": {"message": "?"}})

    return respond


class TestNearRpcLive(ServerTest):
    responder = staticmethod(rpc_responder)

    def rpc(self) -> near_tx.NearRpc:
        return near_tx.NearRpc(base_url=self.server.base)

    def test_signing_context_uses_the_access_key_nonce_plus_one(self):
        context = near_tx.fetch_signing_context(
            self.rpc(), signer_id=SIGNER, receiver_id=VAULT, key=KEY
        )

        self.assertEqual(context.nonce, 42)
        self.assertEqual(context.block_hash, BLOCK_HASH)
        query = self.server.requests[0]
        self.assertEqual(query.path, "/")
        self.assertEqual(query.json["jsonrpc"], "2.0")
        self.assertEqual(query.json["id"], "stark")
        self.assertEqual(query.json["method"], "query")
        self.assertEqual(
            query.json["params"],
            {
                "request_type": "view_access_key",
                "finality": "final",
                "account_id": SIGNER,
                "public_key": KEY.public_b58,
            },
        )

    def test_broadcast_sends_base64_of_signed_transaction(self):
        result = chain(self.rpc(), broadcast=True).pay(VAULT, "0101170026583", 5000)

        self.assertTrue(result.broadcast)
        self.assertIn(len(result.tx_hash), (43, 44), "base58, as explorers spell it")
        self.assertEqual(result.value["payment_id"], 7, "the contract's return is decoded")

        broadcast = [r for r in self.server.requests if r.json["method"] == "broadcast_tx_commit"]
        self.assertEqual(len(broadcast), 1)
        signed = base64.b64decode(broadcast[0].json["params"][0])

        # Signature is { key_type: KeyType, signature: [u8; 64] }, so the envelope is
        # tx + one key-type byte + 64 signature bytes.
        tx_bytes, signature = signed[:-65], signed[-64:]
        self.assertEqual(signed[-65], 0, "Signature::ED25519 key type")
        self.assertEqual(len(signature), 64)
        self.assertTrue(
            near_tx.ed25519_verify(KEY.public, near_tx.transaction_hash(tx_bytes), signature)
        )

        # Decode the exact envelope `near-primitives` expects and pin every field.
        # There is no version tag: V0 starts straight at the signer id length.
        r = Reader(tx_bytes)
        self.assertEqual(r.u32(), len(VAULT), "signer id length is the first field")
        r.i -= 4
        self.assertEqual(r.string(), VAULT, "the agent key signs as the vault")
        self.assertEqual(r.u8(), 0, "PublicKey::ED25519 variant")
        self.assertEqual(r.take(32), KEY.public)
        self.assertEqual(r.u64(), 42)
        self.assertEqual(r.string(), VAULT)
        self.assertEqual(r.take(32), BLOCK_HASH)
        self.assertEqual(r.u32(), 1, "one action")
        self.assertEqual(r.u8(), 2, "Action::FunctionCall variant")
        self.assertEqual(r.string(), "pay")
        args = json.loads(r.byte_vec())
        self.assertEqual(args, {"meter": "0101170026583", "amount_ngn": "5000"})
        self.assertEqual(r.u64(), 100_000_000_000_000, "100 Tgas")
        self.assertEqual(r.u128(), 0, "no attached deposit")
        self.assertEqual(r.i, len(tx_bytes), "no trailing bytes before the signature")

    def test_dry_chain_never_touches_the_network(self):
        result = chain(self.rpc(), broadcast=False).pay(VAULT, "0101170026583", 5000)

        self.assertFalse(result.broadcast)
        self.assertIsNone(result.value)
        self.assertEqual(self.server.requests, [], "dry signing is offline")

    def test_rpc_error_is_raised_with_detail(self):
        self.restart(
            lambda req: json_response(
                {"jsonrpc": "2.0", "id": "stark", "error": {"message": "Unknown access key"}}
            )
        )
        with self.assertRaises(near_tx.NearRpcError) as caught:
            self.rpc().access_key(SIGNER, KEY.public_b58)
        self.assertIn("Unknown access key", str(caught.exception))

    def test_access_key_without_nonce_is_an_error(self):
        self.restart(lambda req: json_response({"result": {}}))
        with self.assertRaises(near_tx.NearRpcError):
            self.rpc().access_key(SIGNER, KEY.public_b58)


if __name__ == "__main__":
    unittest.main()
