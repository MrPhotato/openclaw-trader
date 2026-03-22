/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_DISABLE_STREAM?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
