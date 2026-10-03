import base, { authOnlyAlias } from './authenticated.vite.mjs';
export default { ...base, resolve: { alias: authOnlyAlias }, server: { ...base.server,
  host: '127.0.0.1', port: 5289, strictPort: true, proxy: {
    '/api': 'http://127.0.0.1:8165', '/__v7_fixture': 'http://127.0.0.1:8165',
  } } };
