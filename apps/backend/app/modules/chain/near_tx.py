"""Build and sign a NEAR `pay()` transaction — zero dependencies.

The agent has to authorise a payment without holding the account's full-access
key. It signs a single `pay(meter, amount_ngn)` function call with a
**function-call access key** that the owner scoped to the vault contract. The
chain enforces the caps; the key can do nothing else.

That is why this module exists at all: `near-cli` and `cargo-near` are not
installed on the server, and the signing path needs no SDK. So the
whole path is here in plain Python:

    borsh transaction -> ed25519 signature -> base64 -> JSON-RPC broadcast

Nothing in this module touches the network unless you call `NearRpc`.

**Layout confidence.** The borsh layout below is transcribed from
`near-primitives` (`TransactionV0`, `Action::FunctionCall`) and is covered by
tests that pin byte offsets, the U128-as-string argument encoding, and
`tx_hash == sha256(borsh(transaction))`. A `pay()` signed here was accepted on
chain on 2026-11-03; the global-contract actions are still unverified (HANDOFF §6).
"""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

# --- base58 (Bitcoin alphabet, as NEAR keys use) ----------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {ch: i for i, ch in enumerate(_B58_ALPHABET)}


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + out


def b58decode(text: str) -> bytes:
    n = 0
    for ch in text:
        if ch not in _B58_INDEX:
            raise ValueError(f"not base58: {ch!r}")
        n = n * 58 + _B58_INDEX[ch]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(text) - len(text.lstrip("1"))
    return b"\x00" * pad + body


# --- ed25519 (RFC 8032), pure Python ----------------------------------------
#
# Reference arithmetic, mirroring RFC 8032 §6. Affine coordinates with a modular
# inverse per step: slow (~10 ms per signature) and deliberately simple. A payment
# happens a few times a day, so clarity beats speed here.

_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _Q - 2, _Q) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)


def _inv(x: int) -> int:
    return pow(x, _Q - 2, _Q)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _Q:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _Q
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_Q + 3) // 8, _Q)
    if (x * x - x2) % _Q:
        x = x * _I % _Q
    if (x * x - x2) % _Q:
        return None
    if (x & 1) != sign:
        x = _Q - x
    return x


_BY = 4 * _inv(5) % _Q
_BX = _recover_x(_BY, 0)
_BASE = (_BX, _BY)


def _add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = q
    t = _D * x1 * x2 * y1 * y2 % _Q
    return (
        (x1 * y2 + x2 * y1) * _inv(1 + t) % _Q,
        (y1 * y2 + x1 * x2) * _inv(1 - t) % _Q,
    )


def _mul(p: tuple[int, int], e: int) -> tuple[int, int]:
    if e == 0:
        return (0, 1)
    half = _mul(p, e >> 1)
    out = _add(half, half)
    return _add(out, p) if e & 1 else out


def _compress(p: tuple[int, int]) -> bytes:
    x, y = p
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(raw: bytes) -> tuple[int, int] | None:
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y)


def _expand(secret: bytes) -> tuple[int, bytes]:
    if len(secret) != 32:
        raise ValueError("ed25519 secret must be 32 bytes")
    digest = hashlib.sha512(secret).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def ed25519_public(secret: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte secret seed."""
    a, _ = _expand(secret)
    return _compress(_mul(_BASE, a))


def ed25519_sign(secret: bytes, message: bytes) -> bytes:
    """Sign `message`. Returns the 64-byte signature."""
    a, prefix = _expand(secret)
    public = _compress(_mul(_BASE, a))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _L
    r_compressed = _compress(_mul(_BASE, r))
    k = int.from_bytes(
        hashlib.sha512(r_compressed + public + message).digest(), "little"
    ) % _L
    s = (r + k * a) % _L
    return r_compressed + s.to_bytes(32, "little")


def ed25519_verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """Check a signature. Used by the tests; not on the payment path."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a_point = _decompress(public)
    r_point = _decompress(signature[:32])
    if a_point is None or r_point is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(
        hashlib.sha512(signature[:32] + public + message).digest(), "little"
    ) % _L
    return _compress(_mul(_BASE, s)) == _compress(_add(r_point, _mul(a_point, k)))


# --- keys -------------------------------------------------------------------


@dataclass(frozen=True)
class KeyPair:
    """A NEAR ed25519 key. Accepts the formats the CLI and docs actually use."""

    secret: bytes
    public: bytes

    @classmethod
    def from_secret(cls, raw: bytes) -> "KeyPair":
        # NEAR stores 64 bytes (seed + public); the seed alone is also common.
        seed = raw[:32]
        if len(raw) == 64 and raw[32:] != ed25519_public(seed):
            raise ValueError("key file's public half does not match its secret half")
        if len(raw) not in (32, 64):
            raise ValueError("ed25519 secret must be 32 or 64 bytes")
        return cls(secret=seed, public=ed25519_public(seed))

    @classmethod
    def from_string(cls, text: str) -> "KeyPair":
        text = text.strip()
        if text.startswith("ed25519:"):
            return cls.from_secret(b58decode(text.removeprefix("ed25519:")))
        if len(text) == 64:
            try:
                return cls.from_secret(bytes.fromhex(text))
            except ValueError:
                pass
        return cls.from_secret(b58decode(text))

    @property
    def public_b58(self) -> str:
        return f"ed25519:{b58encode(self.public)}"

    def sign(self, message: bytes) -> bytes:
        return ed25519_sign(self.secret, message)


# --- borsh encoding ---------------------------------------------------------


def _u32(n: int) -> bytes:
    return n.to_bytes(4, "little")


def _u64(n: int) -> bytes:
    return n.to_bytes(8, "little")


def _u128(n: int) -> bytes:
    if n < 0:
        raise ValueError("u128 cannot be negative")
    return n.to_bytes(16, "little")


def _string(text: str) -> bytes:
    raw = text.encode()
    return _u32(len(raw)) + raw


def _byte_vec(raw: bytes) -> bytes:
    return _u32(len(raw)) + raw


def _public_key(raw: bytes) -> bytes:
    # PublicKey is an enum; 0 is ED25519, followed by the 32 raw bytes.
    if len(raw) != 32:
        raise ValueError("public key must be 32 bytes")
    return b"\x00" + raw


def pay_args(meter: str, amount_ngn: int) -> bytes:
    """The JSON the contract's `pay` expects.

    `amount_ngn` is a `U128`, and near-sdk serialises U128 as a **string** over
    JSON — a bare number is rejected onchain.
    """
    return json.dumps(
        {"meter": meter, "amount_ngn": str(amount_ngn)},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


# --- actions ----------------------------------------------------------------
#
# `Action` variants in `near-primitives`, in borsh order. Each helper returns the
# variant tag followed by its payload, so a transaction is just a list of these.
#
#   0 CreateAccount  1 DeployContract  2 FunctionCall  3 Transfer  4 Stake
#   5 AddKey  6 DeleteKey  7 DeleteAccount  8 Delegate
#   9 DeployGlobalContract  10 UseGlobalContract
#
# 0-3 and 5 are long-standing. 9 and 10 (NEP-591 global contracts) are newer and,
# like everything here, are pinned by tests but have not been round-tripped live.

DEFAULT_GAS = 100_000_000_000_000  # 100 Tgas


def json_args(args: dict) -> bytes:
    """Compact JSON, as a contract method receives it.

    U128 values must already be strings: near-sdk rejects a bare JSON number.
    """
    return json.dumps(args, separators=(",", ":"), ensure_ascii=False).encode()


def create_account_action() -> bytes:
    return b"\x00"


def deploy_contract_action(code: bytes) -> bytes:
    return b"\x01" + _byte_vec(code)


def function_call_action(method: str, args: bytes, *, gas: int = DEFAULT_GAS,
                         deposit: int = 0) -> bytes:
    return b"\x02" + _string(method) + _byte_vec(args) + _u64(gas) + _u128(deposit)


def transfer_action(yocto: int) -> bytes:
    return b"\x03" + _u128(yocto)


def add_function_call_key_action(public_key: bytes, *, receiver_id: str,
                                 method_names: list[str],
                                 allowance: int | None = None) -> bytes:
    """`AddKey` with a `FunctionCall` permission: the key can call only these methods
    on `receiver_id`, and burn at most `allowance` yocto of gas (None = unlimited).

    AccessKey is `{ nonce: u64, permission }`; `AccessKeyPermission::FunctionCall` is
    variant 0 and holds `{ allowance: Option<u128>, receiver_id, method_names }`.
    """
    allowance_bytes = b"\x00" if allowance is None else b"\x01" + _u128(allowance)
    names = _u32(len(method_names)) + b"".join(_string(name) for name in method_names)
    permission = b"\x00" + allowance_bytes + _string(receiver_id) + names
    return b"\x05" + _public_key(public_key) + _u64(0) + permission


def deploy_global_contract_action(code: bytes) -> bytes:
    """Publish `code` as a global contract addressed by the signer's account id
    (`GlobalContractDeployMode::AccountId` is variant 1), so later uploads replace it."""
    return b"\x09" + _byte_vec(code) + b"\x01"


def use_global_contract_action(code_account_id: str) -> bytes:
    """Point an account at code another account published as a global contract.

    `GlobalContractIdentifier::AccountId` is variant 1. This is what keeps a vault
    per user affordable: the 277 KB wasm is stored once, not once per user.
    """
    return b"\x0a" + b"\x01" + _string(code_account_id)


def encode_transaction(*, signer_id: str, public_key: bytes, nonce: int,
                       receiver_id: str, block_hash: bytes,
                       actions: list[bytes]) -> bytes:
    """Borsh-encode the inner `TransactionV0`.

    Field order is `TransactionV0` in `near-primitives`:
    signer_id, public_key, nonce, receiver_id, block_hash, actions.

    There is **no version tag**. A node tells V0 from V1 by peeking the first two
    bytes: V0 starts with the signer id's 4-byte length, whose second byte is 0 for
    any account id (they are at most 64 bytes), while V1 starts with a `1` tag
    followed by a nonzero length byte. Prefixing `0x00` here makes the node read it
    as a version tag and refuse the transaction with `invalid transaction version
    tag: 0` — which is what happened before the first live broadcast.
    """
    if len(block_hash) != 32:
        raise ValueError("block hash must be 32 bytes")
    if not actions:
        raise ValueError("a transaction needs at least one action")
    return (
        _string(signer_id)
        + _public_key(public_key)
        + _u64(nonce)
        + _string(receiver_id)
        + block_hash
        + _u32(len(actions))
        + b"".join(actions)
    )


def encode_pay_transaction(
    *,
    signer_id: str,
    public_key: bytes,
    nonce: int,
    receiver_id: str,
    block_hash: bytes,
    meter: str,
    amount_ngn: int,
    function_name: str = "pay",
    gas: int = DEFAULT_GAS,
    deposit: int = 0,  # ledger-only vault: no attached NEAR
) -> bytes:
    """`pay(meter, amount_ngn)` as a one-action transaction."""
    return encode_transaction(
        signer_id=signer_id,
        public_key=public_key,
        nonce=nonce,
        receiver_id=receiver_id,
        block_hash=block_hash,
        actions=[function_call_action(function_name, pay_args(meter, amount_ngn),
                                      gas=gas, deposit=deposit)],
    )


def transaction_hash(tx: bytes) -> bytes:
    """NEAR hashes the *unsigned* transaction bytes."""
    return hashlib.sha256(tx).digest()


@dataclass(frozen=True)
class SignedTransaction:
    tx_bytes: bytes
    signature: bytes
    tx_hash: bytes

    @property
    def base64(self) -> str:
        """What `broadcast_tx_commit` wants: borsh(signed tx) in base64.

        `Signature` is `{ key_type: KeyType, signature: [u8; 64] }`, so the key type
        byte (0 for ED25519) goes in front of the 64 signature bytes. Omitting it
        shifts the parse and the node rejects the transaction with `unknown key
        type`, with the byte it complains about changing every time.
        """
        return base64.b64encode(self.tx_bytes + b"\x00" + self.signature).decode()

    @property
    def hash_hex(self) -> str:
        return self.tx_hash.hex()

    @property
    def hash_b58(self) -> str:
        """The hash as RPC, wallets and explorers spell it."""
        return b58encode(self.tx_hash)

    def summary(self) -> dict:
        return {"tx_hash": self.hash_hex, "encoded_len": len(self.tx_bytes) + 65}


def sign_pay(
    *,
    key: KeyPair,
    signer_id: str,
    receiver_id: str,
    nonce: int,
    block_hash: bytes,
    meter: str,
    amount_ngn: int,
    gas: int = 100_000_000_000_000,
    deposit: int = 0,
) -> SignedTransaction:
    """Build and sign `pay(meter, amount_ngn)` on `receiver_id`."""
    tx = encode_pay_transaction(
        signer_id=signer_id,
        public_key=key.public,
        nonce=nonce,
        receiver_id=receiver_id,
        block_hash=block_hash,
        meter=meter,
        amount_ngn=amount_ngn,
        gas=gas,
        deposit=deposit,
    )
    return SignedTransaction(
        tx_bytes=tx,
        signature=key.sign(transaction_hash(tx)),
        tx_hash=transaction_hash(tx),
    )


def sign_transaction(*, key: KeyPair, signer_id: str, receiver_id: str, nonce: int,
                     block_hash: bytes, actions: list[bytes]) -> SignedTransaction:
    tx = encode_transaction(
        signer_id=signer_id,
        public_key=key.public,
        nonce=nonce,
        receiver_id=receiver_id,
        block_hash=block_hash,
        actions=actions,
    )
    return SignedTransaction(
        tx_bytes=tx,
        signature=key.sign(transaction_hash(tx)),
        tx_hash=transaction_hash(tx),
    )


# --- JSON-RPC ---------------------------------------------------------------

# FastNEAR answers in about 0.5s from Lagos; NEAR's own public endpoints took 3.5s.
TESTNET_RPC = "https://test.rpc.fastnear.com"
MAINNET_RPC = "https://free.rpc.fastnear.com"


class NearRpcError(Exception):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


class NearRpc:
    """The three RPC calls signing needs. Nothing else."""

    def __init__(self, base_url: str = TESTNET_RPC, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, params: dict | list) -> dict:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": "stark", "method": method, "params": params}
        ).encode()
        request = urllib.request.Request(
            self.base_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                payload = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as err:
            try:
                detail = err.read().decode("utf-8", "replace")[:300]
            finally:
                err.close()
            raise NearRpcError(f"RPC returned HTTP {err.code}: {detail}") from err
        except urllib.error.URLError as err:
            raise NearRpcError(f"Could not reach {self.base_url}: {err}") from err
        except json.JSONDecodeError as err:
            raise NearRpcError("RPC returned non-JSON") from err

        if "error" in payload:
            raise NearRpcError(
                payload["error"].get("message", "RPC error"), payload["error"]
            )
        return payload.get("result") or {}

    def latest_block_hash(self) -> bytes:
        result = self._call("block", {"finality": "final"})
        encoded = (result.get("header") or {}).get("hash")
        if not encoded:
            raise NearRpcError("block response had no hash")
        return b58decode(encoded)

    def access_key(self, account_id: str, public_key_b58: str) -> dict:
        """Nonce plus block hash, from one call — enough to sign."""
        result = self._call(
            "query",
            {
                "request_type": "view_access_key",
                "finality": "final",
                "account_id": account_id,
                "public_key": public_key_b58,
            },
        )
        if "nonce" not in result:
            raise NearRpcError(
                f"{public_key_b58} is not a key on {account_id}",
                {"account_id": account_id},
            )
        return {"nonce": int(result["nonce"]), "block_hash": result.get("block_hash")}

    def broadcast(self, signed: SignedTransaction) -> dict:
        return self.broadcast_base64(signed.base64)

    def broadcast_base64(self, encoded: str) -> dict:
        """Send a transaction signed earlier. The same bytes can only land once."""
        return self._call("broadcast_tx_commit", [encoded])

    def tx_status(self, tx_hash_b58: str, sender_id: str) -> dict | None:
        """The outcome of a sent transaction, or None if the chain has never seen it."""
        try:
            return self._call("tx", [tx_hash_b58, sender_id])
        except NearRpcError as err:
            if "UNKNOWN_TRANSACTION" in str(err.detail) or "doesn't exist" in str(err):
                return None
            raise

    def view(self, account_id: str, method: str, args: dict) -> object:
        """Call a view method and decode its JSON result."""
        result = self._call(
            "query",
            {
                "request_type": "call_function",
                "finality": "final",
                "account_id": account_id,
                "method_name": method,
                "args_base64": base64.b64encode(json_args(args)).decode(),
            },
        )
        if "error" in result:
            raise NearRpcError(str(result["error"]), result)
        return json.loads(bytes(result.get("result") or []) or b"null")


class ContractRefused(Exception):
    """The transaction landed and the contract panicked. `message` is its sentence."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


_PANIC_PREFIX = "Smart contract panicked: "


def success_value(outcome: dict) -> object:
    """The decoded return value of a committed transaction, or `ContractRefused`.

    `broadcast_tx_commit` reports `status: {"SuccessValue": "<base64 json>"}` or
    `status: {"Failure": {"ActionError": {"kind": {"FunctionCallError":
    {"ExecutionError": "Smart contract panicked: <sentence>"}}}}}`. The sentence is
    the contract's plain-English refusal, so it is lifted out intact.
    """
    status = outcome.get("status") or {}
    if "SuccessValue" in status:
        raw = base64.b64decode(status["SuccessValue"] or "")
        return json.loads(raw) if raw else None
    failure = status.get("Failure") or {}
    kind = ((failure.get("ActionError") or {}).get("kind") or {})
    execution = (kind.get("FunctionCallError") or {}).get("ExecutionError")
    if isinstance(execution, str):
        message = execution[len(_PANIC_PREFIX):] if execution.startswith(_PANIC_PREFIX) \
            else execution
        raise ContractRefused(message, failure)
    raise ContractRefused("The transaction failed", failure or outcome)


@dataclass(frozen=True)
class SigningContext:
    """What a live signature needs from the chain: a nonce and a recent block."""

    signer_id: str
    receiver_id: str
    nonce: int
    block_hash: bytes


def fetch_signing_context(
    rpc: NearRpc, *, signer_id: str, receiver_id: str, key: KeyPair
) -> SigningContext:
    access = rpc.access_key(signer_id, key.public_b58)
    block_hash = (
        b58decode(access["block_hash"])
        if access.get("block_hash")
        else rpc.latest_block_hash()
    )
    # Every signature must use a strictly higher nonce than the last one.
    return SigningContext(
        signer_id=signer_id,
        receiver_id=receiver_id,
        nonce=access["nonce"] + 1,
        block_hash=block_hash,
    )
