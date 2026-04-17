/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_DISABLE_STREAM?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Global function defined in index.html — called by React once the
// first real data payload has arrived, tells the splash to fly out.
interface Window {
  releaseSplash?: () => void;
}
