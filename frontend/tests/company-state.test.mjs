import { authAlias } from './authenticated.vite.mjs';
import assert from "node:assert/strict";
import { test, before, after } from "node:test";
import { createServer } from "vite";
import { chromium } from "playwright";

let server, CompanyStore, KEY, ServiceError, createCompanyApi;
const A = { id: "00000000-0000-4000-8000-000000000001", name: "A", archived: false, accounts: [] };
const B = { id: "00000000-0000-4000-8000-000000000002", name: "B", archived: false, accounts: [] };
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function fixture(id = null, list = async () => [A, B]) {
  const values = new Map(id === null ? [] : [[KEY, id]]), writes = [];
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); writes.push([key, value]); }, removeItem: (key) => values.delete(key) };
  return { store: new CompanyStore({ listCompanies: list }, storage), values, writes };
}
before(async () => {
  server = await createServer({ resolve: { alias: authAlias }, server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  ({ CompanyStore, ACTIVE_COMPANY_KEY: KEY } = await server.ssrLoadModule("/src/company/companyStore.ts"));
  ({ ServiceError } = await server.ssrLoadModule("/src/metaLibrary.ts"));
  ({ createCompanyApi } = await server.ssrLoadModule("/src/company/companyApi.ts"));
});
after(async () => { await server?.close(); });

test("valid persisted UUID restored only after companies load", async () => {
  const pending = deferred(), { store } = fixture(A.id, () => pending.promise);
  const loading = store.refreshCompanies();
  assert.equal(store.getSnapshot().status, "loading");
  assert.equal(store.getSnapshot().activeCompanyId, null);
  assert.equal(store.captureScope(), null);
  pending.resolve([A, B]); await loading;
  assert.equal(store.getSnapshot().activeCompanyId, A.id);
});
for (const [name, id, companies] of [["invalid UUID", "meta-123", [A]], ["inaccessible company", B.id, [A]], ["archived company", A.id, [{ ...A, archived: true }, B]], ["empty companies", A.id, []]]) {
  test(`${name} cleared without fallback`, async () => {
    const { store, values } = fixture(id, async () => companies);
    await store.refreshCompanies();
    assert.equal(store.getSnapshot().activeCompanyId, null);
    assert.equal(values.has(KEY), false);
  });
}
test("no persisted company means no automatic selection", async () => {
  const { store } = fixture(); await store.refreshCompanies();
  assert.equal(store.getSnapshot().activeCompanyId, null);
});
test("switch writes UUID only and fires synchronous reset; same selection is a no-op", async () => {
  const { store, values, writes } = fixture(A.id); await store.refreshCompanies();
  let resets = 0; const unsubscribe = store.subscribeScope(() => resets++);
  const scope = store.captureScope();
  store.setActiveCompany(B.id); store.setActiveCompany(B.id);
  assert.equal(resets, 1); assert.equal(scope.signal.aborted, true); assert.equal(scope.isCurrent(), false);
  assert.deepEqual([...values], [[KEY, B.id]]);
  assert.deepEqual(writes, [[KEY, A.id], [KEY, B.id]]);
  assert.throws(() => store.setActiveCompany("provider-id"));
  store.setActiveCompany(null); assert.equal(values.size, 0); unsubscribe();
});
test("create selection immediate; archive clears active; restore does not select", async () => {
  const { store, values } = fixture(null, async () => []); await store.refreshCompanies();
  store.acceptCompany({ ...A, token: "never-persist" }, true);
  assert.equal(values.get(KEY), A.id);
  assert.deepEqual(store.getSnapshot().companies, [A]);
  store.acceptCompany({ ...A, archived: true });
  assert.equal(values.size, 0); assert.equal(store.captureScope(), null);
  store.acceptCompany(A); assert.equal(store.getSnapshot().activeCompanyId, null);
});
test("late A success/failure cannot commit after A to B to A", async () => {
  const { store } = fixture(A.id); await store.refreshCompanies();
  const scope = store.captureScope(); store.setActiveCompany(B.id); store.setActiveCompany(A.id);
  assert.equal(scope.isCurrent(), false);
  await store.handleScopeError(scope, new ServiceError(401, "expired"));
  assert.equal(store.getSnapshot().activeCompanyId, A.id);
});
test("latest company-list response wins", async () => {
  const first = deferred(), second = deferred(); let count = 0;
  const { store } = fixture(B.id, () => (++count === 1 ? first : second).promise);
  const p1 = store.refreshCompanies(), p2 = store.refreshCompanies();
  second.resolve([B]); await p2; first.resolve([A]); await p1;
  assert.equal(store.getSnapshot().activeCompanyId, B.id);
});
for (const status of [401, 403, 404]) {
  test(`startup ${status} clears persisted UUID`, async () => {
    const { store, values } = fixture(A.id, async () => { throw new ServiceError(status, "denied"); });
    await store.refreshCompanies(); assert.equal(values.size, 0);
    assert.equal(store.getSnapshot().status, "error"); assert.equal(store.captureScope(), null);
  });
  test(`current scope ${status} clears selection and data access`, async () => {
    const { store, values } = fixture(A.id); await store.refreshCompanies();
    await store.handleScopeError(store.captureScope(), new ServiceError(status, "denied"));
    assert.equal(values.size, 0); assert.equal(store.captureScope(), null);
  });
}
test("network error hides scope, retains UUID for explicit retry", async () => {
  let fail = true;
  const { store, values } = fixture(A.id, async () => { if (fail) throw new TypeError("offline"); return [A]; });
  await store.refreshCompanies(); assert.equal(store.getSnapshot().status, "error");
  assert.equal(store.captureScope(), null); assert.equal(values.get(KEY), A.id);
  fail = false; await store.refreshCompanies(); assert.equal(store.getSnapshot().activeCompanyId, A.id);
});
test("refresh detects revoked access without selecting another company", async () => {
  let companies = [A, B]; const { store, values } = fixture(A.id, async () => companies);
  await store.refreshCompanies(); companies = [B]; await store.refreshCompanies();
  assert.equal(store.getSnapshot().activeCompanyId, null); assert.equal(values.size, 0);
});
test("blocked storage keeps session state usable", async () => {
  const store = new CompanyStore({ listCompanies: async () => [A] }, { getItem() { throw Error(); }, setItem() { throw Error(); }, removeItem() { throw Error(); } });
  await store.refreshCompanies(); store.setActiveCompany(A.id);
  assert.equal(store.getSnapshot().activeCompanyId, A.id); assert.ok(store.getSnapshot().persistenceError);
});
test("adapter uses exact backend routes, envelopes, and bodyless ownership mutations", async () => {
  const calls = [], wire = { company_id: A.id, name: A.name, archived: false, accounts: [] };
  const api = createCompanyApi(async (url, options) => {
    calls.push({ url, ...options });
    let result = wire;
    if (options.method === 'GET') result = url.includes('/ads') ? { ads: [{ ad_item_id: B.id, display_name: 'Ad', assigned: true }] }
      : url === '/api/meta/accounts' ? { accounts: [{ account_id: B.id, display_name: 'Account', platform: 'meta_ads', organic_owner: null }] }
      : url.includes('?') ? { companies: [wire] } : wire;
    else if (url.includes('/ads/')) result = { ok: true };
    return new Response(JSON.stringify(result));
  });
  const signal = new AbortController().signal;
  assert.deepEqual(await api.listCompanies(signal), [A]);
  assert.deepEqual(await api.getCompany(A.id, signal), A);
  await api.createCompany('A', signal); await api.renameCompany(A.id, 'Renamed', signal);
  await api.archiveCompany(A.id, signal); await api.restoreCompany(A.id, signal);
  assert.equal((await api.listAvailableMetaAccounts(signal))[0].id, B.id);
  await api.linkAccount(A.id, B.id, signal); await api.unlinkAccount(A.id, B.id, signal);
  assert.deepEqual(await api.listAssignableAdsContent(A.id, B.id, signal), [{ id: B.id, label: 'Ad', assigned: true }]);
  await api.assignAdsContent(B.id, A.id, signal); await api.unassignAdsContent(B.id, A.id, signal);
  await api.reassignAdsContent(B.id, A.id, B.id, signal);
  const base = `/api/companies/${A.id}`;
  assert.deepEqual(calls.map(c => [c.method, c.url, c.body ? JSON.parse(c.body) : null]), [
    ['GET', '/api/companies?include_archived=true', null], ['GET', base, null],
    ['POST', '/api/companies', {name:'A'}], ['PATCH', base, {name:'Renamed'}],
    ['POST', `${base}/archive`, null], ['POST', `${base}/restore`, null], ['GET', '/api/meta/accounts', null],
    ['PUT', `${base}/accounts/${B.id}`, null], ['DELETE', `${base}/accounts/${B.id}`, null],
    ['GET', `${base}/accounts/${B.id}/ads`, null], ['PUT', `${base}/ads/${B.id}`, null], ['DELETE', `${base}/ads/${B.id}`, null],
    ['POST', `${base}/ads/${B.id}/reassign`, {target_company_id:B.id}]
  ]);
  for (const call of calls) { assert.equal(call.credentials, 'same-origin'); assert.equal(call.cache, 'no-store'); assert.ok(call.signal); }
});
test("adapter rejects malformed records and exposes HTTP status", async () => {
  const signal = new AbortController().signal;
  const malformed = createCompanyApi(async () => new Response(JSON.stringify({ items: [{ ...A, id: "meta-123" }], next_cursor: null })));
  await assert.rejects(malformed.listCompanies(signal), { status: 502 });
  const denied = createCompanyApi(async () => new Response(null, { status: 401 }));
  await assert.rejects(denied.listCompanies(signal), { status: 401 });
});

test("React boundary gates startup, resets selections, and query rejects a late A response", async () => {
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.route("**/api/**", route => route.fulfill({ json: { items: [], next_cursor: null, connected: false } }));
    await page.goto(server.resolvedUrls.local[0]);
    await page.evaluate(async ({ A, B, KEY }) => {
      const reactModule = await import('/node_modules/.vite/deps/react.js');
      const React = reactModule.default ?? reactModule;
      const domModule = await import('/node_modules/.vite/deps/react-dom_client.js');
      const { createRoot } = domModule.default ?? domModule;
      const { CompanyStore } = await import('/src/company/companyStore.ts');
      const { CompanyProvider, CompanyScopeBoundary, useCompanyQuery } = await import('/src/company/CompanyProvider.tsx');
      localStorage.setItem(KEY, A.id);
      let ready; const list = new Promise(resolve => { ready = resolve; });
      const store = new CompanyStore({ listCompanies: () => list }, localStorage);
      window.companyTest = { store, ready, pending: {}, renders: [] };
      const load = (id) => new Promise(resolve => { window.companyTest.pending[id] = resolve; });
      const outsideLoad = (id) => new Promise(resolve => { window.companyTest.pending[`outside:${id}`] = resolve; });
      function Observer() {
        const query = useCompanyQuery('outside-boundary', outsideLoad);
        window.companyTest.renders.push({ id: store.getSnapshot().activeCompanyId, data: query.data });
        return React.createElement('span', { id: 'company-observer' }, query.data ?? query.status);
      }
      function Child() {
        const query = useCompanyQuery('content', load);
        const [selected, setSelected] = React.useState(false);
        window.companyTest.renders.push({ id: store.getSnapshot().activeCompanyId, data: query.data });
        return React.createElement('button', { id: 'company-test', onClick: () => setSelected(true) }, `${selected}:${query.data ?? query.status}`);
      }
      const host = document.createElement('div'); document.body.append(host);
      createRoot(host).render(React.createElement(React.StrictMode, null, React.createElement(CompanyProvider, { store }, React.createElement(CompanyScopeBoundary, null, React.createElement(Child)), React.createElement(Observer))));
    }, { A, B, KEY });
    await page.waitForTimeout(50);
    assert.equal(await page.locator('#company-test').count(), 0);
    await page.evaluate(({ A, B }) => window.companyTest.ready([A, B]), { A, B });
    await page.locator('#company-test').waitFor(); await page.locator('#company-test').click();
    await page.waitForFunction(id => !!window.companyTest.pending[id], A.id);
    await page.waitForFunction(id => !!window.companyTest.pending[`outside:${id}`], A.id);
    await page.evaluate(id => window.companyTest.store.setActiveCompany(id), B.id);
    await page.waitForFunction(id => !!window.companyTest.pending[id], B.id);
    await page.waitForFunction(id => !!window.companyTest.pending[`outside:${id}`], B.id);
    await page.evaluate(id => { window.companyTest.pending[id]('B content'); window.companyTest.pending[`outside:${id}`]('B content'); }, B.id);
    await page.waitForFunction(() => document.querySelector('#company-test').textContent === 'false:B content');
    await page.waitForFunction(() => document.querySelector('#company-observer').textContent === 'B content');
    await page.evaluate(id => { window.companyTest.pending[id]('A late content'); window.companyTest.pending[`outside:${id}`]('A late content'); }, A.id);
    await page.waitForTimeout(50);
    assert.equal(await page.locator('#company-test').textContent(), 'false:B content');
    assert.equal(await page.locator('#company-observer').textContent(), 'B content');
    assert.equal(await page.evaluate(id => window.companyTest.renders.some(r => r.id === id && r.data?.startsWith('A')), B.id), false);
    assert.equal(await page.evaluate(key => localStorage.getItem(key), KEY), B.id);
  } finally { await browser.close(); }
});
