import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';
const origin = 'http://127.0.0.1:5184', KEY = 'video-analyzer.active-company-id';
let backend, vite, browser, directory, session, companies;
async function wait(url, child) {
  for (let i = 0; i < 200; i++) {
    if (child.exitCode !== null) throw Error(`Server exited ${child.exitCode}`);
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise(r => setTimeout(r, 100));
  }
  throw Error(`Server unavailable: ${url}`);
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Server did not stop')), 20000);
    child.once('exit', () => { clearTimeout(timer); resolve(); }); child.kill('SIGTERM');
  });
}
before(async () => {
  assert.ok(process.env.TEST_DATABASE_URL, 'TEST_DATABASE_URL must point to disposable PostgreSQL');
  directory = await mkdtemp(join(tmpdir(), 'company-browser-'));
  backend = spawn('.venv/bin/python', ['tests/company_browser_server.py'], { cwd: '../backend', env: { ...process.env, COMPANY_E2E_DIRECTORY: directory }, stdio: 'inherit' });
  await wait('http://127.0.0.1:8062/health', backend);
  vite = spawn('./node_modules/.bin/vite', ['--config', 'tests/company-integration.vite.mjs'], { stdio: 'inherit' });
  await wait(origin, vite);
  session = JSON.parse(await readFile(join(directory, 'session.json'), 'utf8'));
  browser = await chromium.launch({ headless: true });
  const c = await context();
  companies = (await (await c.request.get(`${origin}/api/companies`)).json()).companies;
  await c.close();
});
after(async () => {
  await browser?.close(); await stop(vite); await stop(backend);
  if (directory) await rm(directory, { recursive: true, force: true });
});
async function context(persisted) {
  const c = await browser.newContext({ extraHTTPHeaders: { Cookie: `${session.name}=${session.value}` } });
  await c.addCookies([{ ...session, domain: '127.0.0.1', path: '/api', httpOnly: true, secure: true, sameSite: 'Lax' }]);
  if (persisted !== undefined) await c.addInitScript(({ KEY, persisted }) => { if (!sessionStorage.initialized) { localStorage.setItem(KEY, persisted); sessionStorage.initialized = 'true'; } }, { KEY, persisted });
  return c;
}
async function pageFor(c) { const p = await c.newPage(); p.setDefaultTimeout(10000); await p.goto(origin); return p; }
const nav = p => p.getByRole('navigation', { name: 'Company', exact: true });
async function manage(p) { await nav(p).getByRole('button').first().click(); await nav(p).getByRole('button', { name: 'Manage companies', exact: true }).click(); await p.getByRole('heading', { name: 'Manage companies', exact: true }).waitFor(); }
async function select(p, name) { await nav(p).getByRole('button').first().click(); await nav(p).getByRole('button', { name, exact: true }).click(); }
async function selected(p, name) { await nav(p).getByRole('button', { name, exact: true }).waitFor(); }
async function stored(p, id) { await p.waitForFunction(({KEY,id}) => localStorage.getItem(KEY) === id, {KEY,id}); }
async function check(p, name, checked) {
  const input = p.getByRole('checkbox', { name, exact: true });
  assert.notEqual(await input.isChecked(), checked);
  await Promise.all([p.waitForResponse(r => r.request().method() === (checked ? 'PUT' : 'DELETE') && r.url().includes('/api/companies/')), input.click()]);
  await p.waitForFunction(() => !document.body.textContent.includes('Saving company changes…') && !document.body.textContent.includes('Loading available accounts and ads…'));
  assert.equal(await input.isChecked(), checked);
}
for (const mode of ['none', 'valid', 'invalid', 'inaccessible', 'archived']) test(`real startup: ${mode} selection has no fallback`, async () => {
  let id = companies[0].company_id;
  if (mode === 'archived') {
    const temp = await context();
    const created = await (await temp.request.post(`${origin}/api/companies`, { data: { name: 'Archived startup' } })).json(); id = created.company_id;
    await temp.request.post(`${origin}/api/companies/${id}/archive`); await temp.close();
  }
  const persisted = mode === 'none' ? undefined : mode === 'invalid' ? 'provider-123' : mode === 'inaccessible' ? '00000000-0000-4000-8000-000000000099' : id;
  const c = await context(persisted);
  try {
    const p = await pageFor(c);
    if (mode === 'valid') { await selected(p, companies[0].name); await stored(p, id); }
    else { await p.getByRole('heading', { name: 'No company selected' }).waitFor(); await stored(p, null); }
  } finally { await c.close(); }
});

test('real browser → FastAPI → PostgreSQL lifecycle, ownership, Ads, guards and privacy', { timeout: 90000 }, async () => {
  const c = await context();
  const p = await c.newPage(); p.setDefaultTimeout(10000);
  const calls = [], responseChecks = [], errors = [];
  p.on('pageerror', e => errors.push(e.message));
  p.on('request', r => { if (new URL(r.url()).pathname.startsWith('/api/')) calls.push(new URL(r.url()).pathname); });
  p.on('requestfinished', request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/companies') || path === '/api/meta/accounts') responseChecks.push(request.response().then(response => response.text()).then(text => {
      for (const forbidden of ['external_id', 'connection_id', 'encrypted', 'access_token', 'provider.invalid', 'a-secret', 'b-secret', 'foreign-ads']) assert.equal(text.includes(forbidden), false, forbidden);
    }));
  });
  try {
    await p.goto(origin); await p.getByRole('heading', { name: 'No company selected' }).waitFor();
    await manage(p);
    assert.equal(await p.getByRole('button', { name: 'Create company', exact: true }).isDisabled(), true);
    await p.getByLabel('New company name').fill('New studio'); await p.getByRole('button', { name: 'Create company', exact: true }).click();
    await p.getByRole('heading', { name: 'New studio is ready' }).waitFor(); await selected(p, 'New studio');
    const id = await p.evaluate(KEY => localStorage.getItem(KEY), KEY); assert.match(id, /^[0-9a-f-]{36}$/);
    await p.getByRole('button', { name: 'Skip for now' }).click();
    await manage(p); await p.getByLabel('Company name', { exact: true }).fill('Renamed studio'); await p.getByRole('button', { name: 'Save name' }).click(); await selected(p, 'Renamed studio');
    for (const name of ['Facebook Page', 'Instagram Business', 'Ads Business']) await check(p, name, true);
    assert.equal(await p.getByRole('checkbox', { name: 'Summer ad', exact: true }).isChecked(), false);
    assert.equal(await p.locator('.video-card').count(), 0);
    await check(p, 'Summer ad', true);
    await p.setViewportSize({ width: 320, height: 900 });
    assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await p.screenshot({ path: '/tmp/wave1-ads-320.png', fullPage: true });
    await p.setViewportSize({ width: 1280, height: 900 });
    await p.getByRole('checkbox', { name: 'Ads Business', exact: true }).click();
    await p.getByRole('alert').filter({ hasText: 'still has assigned ads' }).waitFor();
    assert.equal(await p.getByRole('checkbox', { name: 'Ads Business', exact: true }).isChecked(), true);
    // Inspect B without changing the active workspace. Conflicts must not transfer ownership.
    await p.getByRole('button', { name: 'B', exact: true }).click();
    await p.getByRole('checkbox', { name: 'Facebook Page', exact: true }).click();
    await p.getByRole('alert').filter({ hasText: 'already belongs to another company' }).waitFor();
    assert.equal(await p.getByRole('checkbox', { name: 'Facebook Page', exact: true }).isChecked(), false);
    await check(p, 'Ads Business', true);
    assert.equal(await p.getByRole('checkbox', { name: 'Summer ad', exact: true }).count(), 0);
    await p.getByRole('button', { name: 'Renamed studio — Active', exact: true }).click();
    await p.getByRole('combobox', { name: /Move Summer ad to/ }).selectOption({ label: 'B' });
    await p.getByRole('button', { name: 'Reassign Summer ad', exact: true }).click();
    await p.getByRole('checkbox', { name: 'Summer ad', exact: true }).waitFor({ state: 'detached' });
    await check(p, 'Ads Business', false);
    await p.getByRole('button', { name: 'B', exact: true }).click();
    await check(p, 'Summer ad', false); await check(p, 'Ads Business', false);
    await p.getByRole('button', { name: 'Renamed studio — Active', exact: true }).click();
    await check(p, 'Facebook Page', false); await check(p, 'Instagram Business', false);
    // Existing dirty rename guard blocks a switch; ordinary switching does not prompt.
    await p.getByLabel('Company name', { exact: true }).fill('Unsaved name'); await select(p, 'B');
    await p.getByRole('dialog').waitFor(); await stored(p, id);
    await p.getByRole('button', { name: 'Stay here' }).click(); await selected(p, 'Renamed studio');
    await select(p, 'B'); await p.getByRole('button', { name: 'Continue and switch' }).click(); await selected(p, 'B');
    await stored(p, companies.find(c => c.name === 'B').company_id);
    await select(p, 'Renamed studio'); await selected(p, 'Renamed studio'); assert.equal(await p.getByRole('dialog').count(), 0); await stored(p, id);
    await p.reload(); await selected(p, 'Renamed studio'); await stored(p, id);
    await manage(p); await p.getByRole('button', { name: 'Archive company', exact: true }).click();
    await p.getByRole('button', { name: 'Restore company', exact: true }).waitFor(); await stored(p, null);
    await p.getByRole('button', { name: 'Restore company', exact: true }).click(); await p.getByRole('button', { name: 'Archive company', exact: true }).waitFor(); await stored(p, null);
    await select(p, 'Renamed studio'); await selected(p, 'Renamed studio'); await stored(p, id);
    // Keyboard and smallest existing responsive sizes use the real application.
    await nav(p).getByRole('button').first().focus(); await p.keyboard.press('Enter'); await p.keyboard.press('Escape');
    await manage(p);
    for (const width of [320, 600, 1280]) {
      await p.setViewportSize({ width, height: 900 });
      assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await p.screenshot({ path: `/tmp/wave1-company-${width}.png`, fullPage: true });
    }
    assert.equal(calls.some(path => /^\/api\/meta\/(library|jobs|sync|recommendations)/.test(path)), false);
    await Promise.all(responseChecks); assert.deepEqual(errors, []);
    const saved = await (await c.request.get(`${origin}/api/companies/${id}`)).json();
    assert.equal(saved.name, 'Renamed studio'); assert.equal(saved.archived, false); assert.deepEqual(saved.accounts, []);
    const text = await p.locator('body').innerText();
    for (const secret of ['a-secret', 'b-secret', 'foreign-ads', 'provider.invalid']) assert.equal(text.includes(secret), false);
  } finally { await c.close(); }
});

for (const failure of [401, 404, 503, 'network']) test(`startup ${failure} exposes error and retry without mounting workspace`, async () => {
  const c = await context(companies[0].company_id);
  try {
    await c.route('**/api/companies?*', route => failure === 'network' ? route.abort('failed') : route.fulfill({ status: failure, json: { detail: 'secret-provider-payload' } }));
    const p = await pageFor(c); await p.getByRole('button', { name: 'Retry companies' }).waitFor();
    assert.equal(await p.getByRole('heading', { name: 'Company workspace', exact: true }).count(), 0);
    assert.equal((await p.locator('body').innerText()).includes('secret-provider-payload'), false);
    if (failure === 401 || failure === 404) await stored(p, null);
    await c.unroute('**/api/companies?*'); await p.getByRole('button', { name: 'Retry companies' }).click();
    if (failure === 401 || failure === 404) await p.getByRole('heading', { name: 'No company selected' }).waitFor();
    else await selected(p, companies[0].name);
  } finally { await c.close(); }
});

test('late Company A Ads response cannot populate Company B management', { timeout: 30000 }, async () => {
  const a = companies.find(c => c.name === 'A'), b = companies.find(c => c.name === 'B');
  const c = await context(a.company_id);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let began;
  const started = new Promise(resolve => { began = resolve; });
  try {
    const accounts = (await (await c.request.get(`${origin}/api/meta/accounts`)).json()).accounts;
    const ads = accounts.find(a => a.platform === 'meta_ads');
    for (const company of [a, b]) assert.equal((await c.request.put(`${origin}/api/companies/${company.company_id}/accounts/${ads.account_id}`)).status(), 200);
    const items = (await (await c.request.get(`${origin}/api/companies/${a.company_id}/accounts/${ads.account_id}/ads`)).json()).ads;
    const summer = items.find(ad => ad.display_name === 'Summer ad');
    assert.equal((await c.request.put(`${origin}/api/companies/${a.company_id}/ads/${summer.ad_item_id}`)).status(), 200);
    await c.route(`**/api/companies/${a.company_id}/accounts/${ads.account_id}/ads`, async route => {
      const response = await route.fetch(); began(); await gate;
      try { await route.fulfill({ response }); } catch { /* A was cancelled by the switch. */ }
    });
    const p = await pageFor(c); await selected(p, 'A'); await manage(p); await started;
    await select(p, 'B'); await selected(p, 'B'); await stored(p, b.company_id);
    await manage(p); await p.getByRole('checkbox', { name: 'Winter ad', exact: true }).waitFor();
    release(); await p.waitForTimeout(100);
    assert.equal(await p.getByRole('checkbox', { name: 'Summer ad', exact: true }).count(), 0);
    assert.equal(await p.getByRole('checkbox', { name: 'Winter ad', exact: true }).count(), 1);
    assert.equal(await p.getByRole('alert').count(), 0);
  } finally { release(); await c.close(); }
});

test('blocked localStorage is visible and company creation remains session-local', async () => {
  const c = await context();
  try {
    await c.addInitScript(() => Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage blocked'); } }));
    const p = await pageFor(c);
    await p.getByRole('heading', { name: 'No company selected' }).waitFor();
    await p.getByRole('alert').filter({ hasText: 'could not be saved' }).waitFor();
    await manage(p); await p.getByLabel('New company name').fill('Session company');
    await p.getByRole('button', { name: 'Create company', exact: true }).click();
    await selected(p, 'Session company'); await p.getByRole('heading', { name: 'Session company is ready' }).waitFor();
    await p.reload(); await p.getByRole('heading', { name: 'No company selected' }).waitFor();
  } finally { await c.close(); }
});
