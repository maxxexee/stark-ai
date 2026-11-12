/** Links into nearblocks for the network the backend's vaults are on (`STARK_NETWORK`). */
export class NearExplorer {
  private static readonly origin =
    import.meta.env.VITE_STARK_NEAR_NETWORK === "mainnet"
      ? "https://nearblocks.io"
      : "https://testnet.nearblocks.io";

  static transaction(txHash: string): string {
    return `${NearExplorer.origin}/txns/${txHash}`;
  }
}
