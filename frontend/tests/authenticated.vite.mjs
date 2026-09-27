import { fileURLToPath } from 'node:url';
import base from '../vite.config.ts';
export const authAlias = [{ find: /^.*\/authClient$/, replacement: fileURLToPath(new URL('./authMock.ts', import.meta.url)) }];
export default { ...base, resolve: { alias: authAlias } };
