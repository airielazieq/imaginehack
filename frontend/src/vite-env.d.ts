/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Override the REST API base URL (defaults to `/api` via the Vite proxy). */
  readonly VITE_API_BASE?: string
  /** Override the WebSocket endpoint (defaults to `/ws/events`). */
  readonly VITE_WS_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
