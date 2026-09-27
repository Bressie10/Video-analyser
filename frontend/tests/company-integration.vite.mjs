import base from '../vite.config.ts';
export default { ...base, server: { ...base.server, host: '127.0.0.1', port: 5184, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8062' } } };
