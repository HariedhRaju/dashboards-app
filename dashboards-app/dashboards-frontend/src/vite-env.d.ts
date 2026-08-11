/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DASHBOARDS_API?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
