import { fileURLToPath } from 'node:url';
import base from '../vite.config.ts';
export const authAlias = [{ find: /^.*\/authClient$/, replacement: fileURLToPath(new URL('./authMock.ts', import.meta.url)) }];
// Existing V5 integration fixtures have cookie identity. Adapt their accessible list
// at the test boundary only; these are not claims of V6 backend authorization QA.
export function legacyIdentity(backend) {
  return { name: 'legacy-test-identity', configureServer(server) {
    server.middlewares.use('/api/me/companies', async (req, res) => {
      try {
        const response = await fetch(`${backend}/api/companies?include_archived=true`, { headers: { cookie: req.headers.cookie ?? '' } });
        res.setHeader('Content-Type', 'application/json');
        if (!response.ok) { res.statusCode = response.status; res.end('{}'); return; }
        const body = await response.json();
        res.end(JSON.stringify({ companies: body.companies.map(c => ({ id: c.company_id, archived_at: c.archived ? '2026-01-01' : null })) }));
      } catch { res.statusCode = 503; res.end('{}'); }
    });
  } };
}
export default { ...base, resolve: { alias: authAlias } };
