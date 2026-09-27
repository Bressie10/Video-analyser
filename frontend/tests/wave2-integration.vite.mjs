import { legacyIdentity } from './authenticated.vite.mjs';
import base from './authenticated.vite.mjs';
export default { ...base, plugins: [...base.plugins, legacyIdentity('http://127.0.0.1:8163')], server: { ...base.server, host: '127.0.0.1', port: 5288, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8163' } } };
