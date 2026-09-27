import base from './authenticated.vite.mjs';
export default { ...base,  server: { ...base.server, host: '127.0.0.1', port: 5288, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8163' } } };
