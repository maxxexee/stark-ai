/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin for deployed builds, e.g. https://api.hellostark.xyz. Empty in dev. */
  readonly VITE_STARK_API_URL?: string;
  /** "true" once payments vend for real. Until then tokens are labelled as samples. */
  readonly VITE_STARK_LIVE_PAYMENTS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
