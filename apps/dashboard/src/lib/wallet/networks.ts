import type { CryptoAsset } from "@stark/api/types";

// 1Click names chains by short code. A network it adds later shows its code until named here.
const NAMES: Partial<Record<string, string>> = {
  abs: "Abstract",
  aleo: "Aleo",
  aptos: "Aptos",
  arb: "Arbitrum",
  avax: "Avalanche",
  base: "Base",
  bch: "Bitcoin Cash",
  bera: "Berachain",
  bsc: "BNB Chain",
  btc: "Bitcoin",
  cardano: "Cardano",
  dash: "Dash",
  doge: "Dogecoin",
  eth: "Ethereum",
  gnosis: "Gnosis",
  hypercore: "Hyperliquid",
  ltc: "Litecoin",
  miden: "Miden",
  monad: "Monad",
  movement: "Movement",
  near: "NEAR",
  op: "Optimism",
  plasma: "Plasma",
  pol: "Polygon",
  scroll: "Scroll",
  sol: "Solana",
  starknet: "Starknet",
  stellar: "Stellar",
  sui: "Sui",
  ton: "TON",
  tron: "Tron",
  xlayer: "X Layer",
  xrp: "XRP Ledger",
  zec: "Zcash",
};

export type NetworkGroup = { value: string; items: CryptoAsset[] };

export class Networks {
  static name(chain: string): string {
    return NAMES[chain] ?? chain.toUpperCase();
  }

  static assetLabel(asset: CryptoAsset): string {
    return `${asset.symbol} on ${Networks.name(asset.chain)}`;
  }

  /** Assets grouped under their network's name, networks in alphabetical order. */
  static group(assets: CryptoAsset[]): NetworkGroup[] {
    const groups = new Map<string, CryptoAsset[]>();
    for (const asset of assets) {
      const network = Networks.name(asset.chain);
      groups.set(network, [...(groups.get(network) ?? []), asset]);
    }
    return [...groups]
      .map(([value, items]) => ({ value, items }))
      .sort((a, b) => a.value.localeCompare(b.value));
  }
}
