import { legacyIdentity } from './authenticated.vite.mjs';
import base from './authenticated.vite.mjs';
export default { ...base, plugins: [...base.plugins, legacyIdentity('http://127.0.0.1:8162')], server: { ...base.server, host: '127.0.0.1', port: 5284, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8162' } } };
