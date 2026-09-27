import base from "./authenticated.vite.mjs";

// Test-only proxy override; the normal development configuration is unchanged.
export default {
  ...base,
  server: {
    ...base.server,
    host: "127.0.0.1",
    port: 5278,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8161" },
  },
};
