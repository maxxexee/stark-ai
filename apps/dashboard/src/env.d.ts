/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin for deployed builds, e.g. https://api.hellostark.xyz. Empty in dev. */
  readonly VITE_STARK_API_URL?: string;
  /** "true" once payments vend for real. Until then tokens are labelled as samples. */
  readonly VITE_STARK_LIVE_PAYMENTS?: string;
  /** The backend's `STARK_NETWORK`, so "View on NEAR" opens the right explorer. Testnet when unset. */
  readonly VITE_STARK_NEAR_NETWORK?: "testnet" | "mainnet";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
