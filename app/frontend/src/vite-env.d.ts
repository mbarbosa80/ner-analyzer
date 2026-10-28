/// <reference types="vite/client" />

declare module "*?url" {
  const src: string;
  export default src;
}

/** The version this bundle was built from — `package.json`, injected by Vite. */
declare const __APP_VERSION__: string;
