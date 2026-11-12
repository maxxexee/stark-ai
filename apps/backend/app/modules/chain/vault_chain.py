"""One vault per user, on NEAR: create it, credit it, pay from it.

Each account's vault is a sub-account of Stark's funder account
(`u-<hex>.stark-vault.testnet`), created in a single transaction the funder signs:

    CreateAccount → Transfer (storage) → code (global or deployed)
    → AddKey (agent key, may only call `pay` on this account) → new(...)

Two keys, two jobs — that split is the security argument:

| Key | Lives on | Can |
|---|---|---|
| funder (`STARK_FUNDER_KEY`) | the parent account, which is also the USDC treasury | create vaults; deposit and refund USDC; `debit`, `set_rate`; set policy and pause while Stark is still the owner |
| agent (`STARK_AGENT_KEY`) | every vault, as a function-call key | `pay` on that one vault, inside its caps. Nothing else |

The agent's calls are signed *as the vault itself* with that function-call key, so
the contract sees `predecessor == current_account_id`. A leaked agent key can spend
inside a user's caps and do nothing more.

Dry by default: with `STARK_BROADCAST` unset, transactions are
signed offline (nonce 0, zero block hash) and never sent, so the money paths run
without a network. A dry signature proves the encoding, not that the chain agreed.

Configuration (env only, never commit any of it):

| Variable | Meaning |
|---|---|
| `STARK_FUNDER_ACCOUNT` | parent of every vault, e.g. `stark-vault.testnet` |
| `STARK_FUNDER_KEY` | its full-access key, `ed25519:<base58>` |
| `STARK_AGENT_KEY` | the key added to each vault for `pay` |
| `STARK_USDC_TOKEN` | the USDC token (default: Circle's USDC on `STARK_NETWORK`) |
| `STARK_VAULT_CODE` | `global:<account>` (default `global:<funder>`) or a path to the wasm |
| `STARK_VAULT_STORAGE_NEAR` | NEAR sent to each new vault for storage (default 0.2 global, 3 deployed) |
| `STARK_NETWORK` | `testnet` (default) or `mainnet` |
| `STARK_BROADCAST` | `1` to send transactions |
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Optional

from app.modules.chain import near_tx

YOCTO_PER_NEAR = 10 ** 24
CREATE_GAS = 100_000_000_000_000
# `ft_transfer_call` runs the vault's `ft_on_transfer` and the token's resolve step.
TRANSFER_CALL_GAS = 100_000_000_000_000
# NEP-145 registration on the USDC token, so the vault can hold it.
TOKEN_STORAGE_YOCTO = 1_250_000_000_000_000_000_000
ONE_YOCTO = 1
# The agent key's lifetime gas budget per vault: 1 NEAR of gas is thousands of pays.
AGENT_ALLOWANCE_YOCTO = YOCTO_PER_NEAR


# Mintable test USDC on testnet (Circle's testnet faucet needs a captcha); Circle's USDC on mainnet.
USDC_TOKENS = {
    "testnet": "usdc.fakes.testnet",
    "mainnet": "17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1",
}


@dataclass(frozen=True)
class ChainResult:
    tx_hash: str
    value: object
    broadcast: bool


@dataclass
class _Nonces:
    """The next nonce per (signer, key), so concurrent payments don't collide.

    A nonce must strictly increase per access key. Fetching it before every
    transaction races when two payments sign at once, so the last one used is
    kept here and the chain is only asked again after a restart or an
    `InvalidNonce` refusal.
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    next: dict = field(default_factory=dict)


class VaultChain:
    def __init__(self, *, rpc: near_tx.NearRpc, funder_id: str, funder_key: near_tx.KeyPair,
                 agent_key: near_tx.KeyPair, treasury_id: str, usdc_id: str, code: str,
                 storage_yocto: int, broadcast: bool) -> None:
        self.rpc = rpc
        self.funder_id = funder_id
        self.funder_key = funder_key
        self.agent_key = agent_key
        self.treasury_id = treasury_id
        self.usdc_id = usdc_id
        self.code = code
        self.storage_yocto = storage_yocto
        self.broadcast = broadcast
        self._nonces = _Nonces()

    def vault_id(self, account_id: str) -> str:
        """`acct_0123abcd…` → `u-0123abcd….<funder>`. Stable, lowercase, short."""
        suffix = account_id.split("_", 1)[-1].lower()
        if not suffix.isalnum() or len(suffix) > 24:
            suffix = hashlib.sha256(account_id.encode()).hexdigest()[:16]
        return f"u-{suffix}.{self.funder_id}"

    # --- writes ---------------------------------------------------------------

    def create(self, vault_id: str, *, usdc_per_kngn: int, monthly_cap_ngn: int,
               per_payment_cap_ngn: int, meters: list[str]) -> ChainResult:
        """Create, deploy and initialise the vault, then register it on the USDC token."""
        init = near_tx.function_call_action("new", near_tx.json_args({
            "owner": self.funder_id,
            "funder": self.funder_id,
            "treasury": self.treasury_id,
            "usdc": self.usdc_id,
            "usdc_per_kngn": str(usdc_per_kngn),
            "monthly_cap_ngn": str(monthly_cap_ngn),
            "per_payment_cap_ngn": str(per_payment_cap_ngn),
            "allowed_meters": meters,
        }), gas=CREATE_GAS)
        actions = [
            near_tx.create_account_action(),
            near_tx.transfer_action(self.storage_yocto),
            self._code_action(),
            near_tx.add_function_call_key_action(
                self.agent_key.public, receiver_id=vault_id, method_names=["pay"],
                allowance=AGENT_ALLOWANCE_YOCTO,
            ),
            init,
        ]
        created = self._send(self.funder_id, self.funder_key, vault_id, actions)
        register = near_tx.function_call_action(
            "storage_deposit",
            near_tx.json_args({"account_id": vault_id, "registration_only": True}),
            deposit=TOKEN_STORAGE_YOCTO,
        )
        self._send(self.funder_id, self.funder_key, self.usdc_id, [register])
        return created

    def deposit(self, vault_id: str, amount_usdc: int, msg: str) -> ChainResult:
        """Send the treasury's USDC into a vault. `msg` is the deposit's reference, or
        `refund:<payment_id>` to return a failed bill's USDC.

        A treasury short of USDC raises `NearRpcError`, so the deposit stays queued and
        lands once the treasury is topped up, instead of failing for good.
        """
        if self.broadcast:
            held = int(self.rpc.view(self.usdc_id, "ft_balance_of",  # type: ignore[arg-type]
                                     {"account_id": self.funder_id}))
            if held < amount_usdc:
                raise near_tx.NearRpcError(
                    f"treasury holds {held} USDC units, a deposit needs {amount_usdc}")
        action = near_tx.function_call_action(
            "ft_transfer_call",
            near_tx.json_args({"receiver_id": vault_id, "amount": str(amount_usdc),
                               "msg": msg}),
            gas=TRANSFER_CALL_GAS, deposit=ONE_YOCTO,
        )
        return self._send(self.funder_id, self.funder_key, self.usdc_id, [action])

    def pay(self, vault_id: str, meter: str, amount_ngn: int) -> ChainResult:
        """Signed as the vault, with the agent's function-call key."""
        action = near_tx.function_call_action("pay", near_tx.pay_args(meter, amount_ngn))
        return self._send(vault_id, self.agent_key, vault_id, [action])

    def pay_approved(self, vault_id: str, meter: str, amount_ngn: int) -> ChainResult:
        """An over-the-cap payment the owner approved. Owner-signed, so it only works
        while Stark's funder is still the vault's owner — after `set_owner`, the
        user's own key would have to approve it."""
        action = near_tx.function_call_action("pay_approved",
                                              near_tx.pay_args(meter, amount_ngn))
        return self._send(self.funder_id, self.funder_key, vault_id, [action])

    def call(self, vault_id: str, method: str, args: dict) -> ChainResult:
        """A funder-signed method: debit, set_rate, set_policy, pause, unpause."""
        action = near_tx.function_call_action(method, near_tx.json_args(args))
        return self._send(self.funder_id, self.funder_key, vault_id, [action])

    def publish_code(self, wasm: bytes) -> ChainResult:
        """Publish the vault code once as a global contract under the funder's id."""
        return self._send(self.funder_id, self.funder_key, self.funder_id,
                          [near_tx.deploy_global_contract_action(wasm)])

    # --- reads ----------------------------------------------------------------

    def state(self, vault_id: str) -> dict:
        return self.rpc.view(vault_id, "get_state", {})  # type: ignore[return-value]

    def payment(self, vault_id: str, payment_id: int) -> dict:
        return self.rpc.view(vault_id, "get_payment",  # type: ignore[return-value]
                             {"payment_id": payment_id})

    # --- plumbing -------------------------------------------------------------

    def _code_action(self) -> bytes:
        if self.code.startswith("global:"):
            return near_tx.use_global_contract_action(self.code[len("global:"):])
        return near_tx.deploy_contract_action(Path(self.code).read_bytes())

    def _send(self, signer_id: str, key: near_tx.KeyPair, receiver_id: str,
              actions: list[bytes]) -> ChainResult:
        if not self.broadcast:
            signed = near_tx.sign_transaction(
                key=key, signer_id=signer_id, receiver_id=receiver_id, nonce=0,
                block_hash=bytes(32), actions=actions,
            )
            return ChainResult(signed.hash_b58, None, False)

        for attempt in (0, 1):
            signed = self._sign_live(signer_id, key, receiver_id, actions, fresh=attempt == 1)
            try:
                outcome = self.rpc.broadcast(signed)
            except near_tx.NearRpcError as err:
                if attempt == 0 and "InvalidNonce" in str(err.detail or err):
                    continue
                raise
            return ChainResult(signed.hash_b58, near_tx.success_value(outcome), True)
        raise near_tx.NearRpcError("nonce kept colliding")  # pragma: no cover

    def _sign_live(self, signer_id: str, key: near_tx.KeyPair, receiver_id: str,
                   actions: list[bytes], *, fresh: bool) -> near_tx.SignedTransaction:
        slot = (signer_id, key.public_b58)
        with self._nonces.lock:
            context = near_tx.fetch_signing_context(
                self.rpc, signer_id=signer_id, receiver_id=receiver_id, key=key
            )
            cached = None if fresh else self._nonces.next.get(slot)
            nonce = max(context.nonce, cached or 0)
            self._nonces.next[slot] = nonce + 1
        return near_tx.sign_transaction(
            key=key, signer_id=signer_id, receiver_id=receiver_id, nonce=nonce,
            block_hash=context.block_hash, actions=actions,
        )


def chain_from_env(env: Optional[Mapping[str, str]] = None) -> Optional[VaultChain]:
    """The chain, or None when no funder is configured (payments then book off-chain).

    Reads config only — no network, so importing the server stays offline-safe.
    Half a configuration is an error, not a silent off switch.
    """
    source = os.environ if env is None else env
    funder_id = (source.get("STARK_FUNDER_ACCOUNT") or "").strip()
    funder_key = (source.get("STARK_FUNDER_KEY") or "").strip()
    agent_key = (source.get("STARK_AGENT_KEY") or "").strip()
    if not (funder_id or funder_key or agent_key):
        return None
    if not (funder_id and funder_key and agent_key):
        raise ValueError(
            "STARK_FUNDER_ACCOUNT, STARK_FUNDER_KEY and STARK_AGENT_KEY go together"
        )

    network = (source.get("STARK_NETWORK") or "testnet").strip().lower()
    if network not in ("testnet", "mainnet"):
        raise ValueError("STARK_NETWORK must be testnet or mainnet")

    code = (source.get("STARK_VAULT_CODE") or f"global:{funder_id}").strip()
    default_storage = "0.2" if code.startswith("global:") else "3"
    storage = Decimal(source.get("STARK_VAULT_STORAGE_NEAR") or default_storage)

    return VaultChain(
        rpc=near_tx.NearRpc(near_tx.MAINNET_RPC if network == "mainnet"
                            else near_tx.TESTNET_RPC),
        funder_id=funder_id,
        funder_key=near_tx.KeyPair.from_string(funder_key),
        agent_key=near_tx.KeyPair.from_string(agent_key),
        treasury_id=funder_id,
        usdc_id=(source.get("STARK_USDC_TOKEN") or USDC_TOKENS[network]).strip(),
        code=code,
        storage_yocto=int(storage * YOCTO_PER_NEAR),
        broadcast=(source.get("STARK_BROADCAST") or "").strip().lower()
        in ("1", "true", "yes"),
    )


def _main() -> None:  # pragma: no cover - operator CLI
    """`python -m app.modules.chain.vault_chain publish <wasm>` — once per code change."""
    import sys

    chain = chain_from_env()
    if chain is None or len(sys.argv) != 3 or sys.argv[1] != "publish":
        raise SystemExit("usage: STARK_FUNDER_*=... python -m app.modules.chain.vault_chain"
                         " publish path/to/stark_vault.wasm")
    result = chain.publish_code(Path(sys.argv[2]).read_bytes())
    print({"tx_hash": result.tx_hash, "broadcast": result.broadcast})


if __name__ == "__main__":  # pragma: no cover
    _main()
