"""How a network is named to a person. 1Click lists chains by short code ("sol",
"bsc"), which is what a deposit stores; a chat and a button say "Solana"."""

from __future__ import annotations


class ChainNames:
    NAMES = {
        "sol": "Solana",
        "eth": "Ethereum",
        "base": "Base",
        "tron": "Tron",
        "bsc": "BNB Chain",
        "avax": "Avalanche",
        "pol": "Polygon",
        "arb": "Arbitrum",
        "op": "Optimism",
        "near": "NEAR",
        "aptos": "Aptos",
        "sui": "Sui",
        "stellar": "Stellar",
        "gnosis": "Gnosis",
        "monad": "Monad",
        "xlayer": "X Layer",
        "btc": "Bitcoin",
        "ton": "TON",
        "doge": "Dogecoin",
        "xrp": "XRP Ledger",
        "zec": "Zcash",
        "ltc": "Litecoin",
        "bera": "Berachain",
        "cardano": "Cardano",
    }

    @classmethod
    def display(cls, chain: str) -> str:
        """The name people use; an unlisted code is shown as it is, upper-cased."""
        return cls.NAMES.get(chain.lower(), chain.upper())
