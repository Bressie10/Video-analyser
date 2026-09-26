import base from "../vite.config.ts";

// Test-only proxy override; the normal development configuration is unchanged.
export default {
  ...base,
  server: {
    ...base.server,
    host: "127.0.0.1",
    port: 5178,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8061" },
  },
};
