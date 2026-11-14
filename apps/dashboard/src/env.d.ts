/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_STARK_API_URL?: string;
  readonly VITE_STARK_LIVE_PAYMENTS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
