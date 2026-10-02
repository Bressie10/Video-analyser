import { fileURLToPath } from 'node:url';
import base from '../vite.config.ts';
export const authOnlyAlias = [{ find: /^.*\/authClient$/, replacement: fileURLToPath(new URL('./authMock.ts', import.meta.url)) }];
export const authAlias = [...authOnlyAlias, { find: /^.*\/onboardingApi$/, replacement: fileURLToPath(new URL('./onboardingCompleteMock.ts', import.meta.url)) }];
export default { ...base, resolve: { alias: authAlias } };
