/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the BatchWatch API. Empty in dev: Vite proxies to serve_local.py. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
