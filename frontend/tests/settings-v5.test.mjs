import { authAlias } from './authenticated.vite.mjs';
import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { mkdir } from 'node:fs/promises';
import { createServer } from 'vite';
import { chromium } from 'playwright';
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const A = id(1), B = id(2), ADS = id(5), AD = id(6);
let server, browser, origin;
before(async () => { server = await createServer({ resolve: { alias: authAlias }, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); await server.listen(); origin = server.resolvedUrls.local[0]; browser = await chromium.launch(); if (process.env.V5_SCREENSHOT_DIR) await mkdir(process.env.V5_SCREENSHOT_DIR, { recursive: true }); });
after(async () => { await browser?.close(); await server?.close(); });
async function fixture({ width = 1440, connected = true, empty = false, conflict = false, accounts = true } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  if (!empty) await context.addInitScript(A => localStorage.setItem('video-analyzer.active-company-id', A), A);
  const accountList = accounts ? [
    { account_id: id(3), display_name: 'Northline Facebook', platform: 'facebook', organic_owner: { company_id: B, name: 'Other studio', role: "owner", archived: false } },
    { account_id: id(4), display_name: 'Northline Instagram', platform: 'instagram', organic_owner: null },
    { account_id: ADS, display_name: 'Northline Ads', platform: 'meta_ads', organic_owner: null },
  ] : [];
  const companies = empty ? [] : [{ company_id: A, name: 'Northline Studio', role: "owner", archived: false, accounts: accountList.filter(a => a.platform === 'meta_ads') }, { company_id: B, name: 'Other studio', role: "owner", archived: false, accounts: accountList.filter(a => a.platform !== 'instagram') }];
  let assigned = false; const mutations = [], errors = [];
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname, method = route.request().method();
    if (method !== 'GET') mutations.push({ path, method });
    if (path === '/api/meta/test') return route.fulfill({ json: { connected } });
    if (path === '/api/meta/accounts') return route.fulfill({ json: { accounts: accountList } });
    if (new URL(route.request().url()).pathname === '/api/me/companies') return route.fulfill({ json: { companies: [A, B].map(value => ({ id: typeof value === 'string' ? value : value.id, archived_at: null })) } });
    if (path === '/api/companies') return route.fulfill({ json: { companies } });
    if (path.endsWith(`/ads/${AD}`)) { if (conflict) return route.fulfill({ status: 409, json: { detail: 'PRIVATE_PROVIDER_SECRET' } }); assigned = method === 'PUT'; return route.fulfill({ json: { ok: true } }); }
    if (path.endsWith('/reassign')) { assigned = false; return route.fulfill({ json: { ok: true } }); }
    if (path.endsWith('/ads')) return route.fulfill({ json: { ads: [{ ad_item_id: AD, display_name: 'Summer launch video', assigned }] } });
    if (path.endsWith('/content') || path.endsWith('/ideas')) return route.fulfill({ json: { items: [], next_cursor: null, next_offset: null } });
    return route.fulfill({ json: {} });
  });
  const page = await context.newPage(); page.setDefaultTimeout(5000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (['error', 'warning'].includes(message.type()) && !conflict) errors.push(message.text()); });
  await page.goto(`${origin}settings/connections`);
  await page.getByRole('heading', { name: 'Settings', exact: true }).waitFor();
  await page.getByText(connected ? 'Meta connected successfully.' : 'Meta is not connected.', { exact: true }).waitFor();
  return { page, mutations, close: async () => { await context.close(); assert.deepEqual(errors, []); } };
}
for (const width of [1440, 1280, 1024, 768, 390, 320]) test(`Settings navigation and ad picker fit ${width}px`, async () => {
  const f = await fixture({ width }); const p = f.page;
  try {
    assert.equal(await p.title(), 'ContentMetric'); await p.getByText('Linked to Other studio', { exact: true }).waitFor(); await p.getByRole('checkbox', { name: 'Summer launch video' }).waitFor();
    assert.equal(await p.locator('vite-error-overlay').count(), 0); assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const nav = p.getByRole('navigation', { name: 'Settings sections' }); if (width > 700) assert.equal(await nav.getByRole('link', { name: 'Connections', exact: true }).getAttribute('aria-current'), 'page'); else await p.getByRole('link', { name: 'All settings' }).waitFor();
    await p.getByLabel('Search ads').fill('missing'); await p.getByText('No ads match your filters.').waitFor(); await p.getByLabel('Search ads').fill('');
    if (process.env.V5_SCREENSHOT_DIR) { await p.evaluate(() => window.scrollTo(0, 0)); await p.screenshot({ path: `${process.env.V5_SCREENSHOT_DIR}/settings-${width}.png`, fullPage: true }); }
    assert.equal((await p.locator('main').innerText()).includes(ADS), false);
  } finally { await f.close(); }
});
test('no company offers name-only onboarding and no ownership controls', async () => {
  const f = await fixture({ empty: true, connected: false });
  try { await f.page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Workspace' }).click(); await f.page.getByRole('heading', { name: 'Create your company workspace' }).waitFor(); await f.page.getByLabel('New company name').fill('New studio'); assert.equal(await f.page.getByRole('button', { name: 'Create company', exact: true }).isEnabled(), true); assert.equal(await f.page.getByRole('checkbox', { name: 'Northline Facebook' }).count(), 0); } finally { await f.close(); }
});
test('disconnected and no eligible account states remain readable', async () => {
  for (const connected of [false, true]) { const f = await fixture({ connected, accounts: false }); try { if (connected) await f.page.getByText('No eligible accounts available.').first().waitFor(); else await f.page.getByText('Connect Meta above to discover accounts for your companies.').waitFor(); } finally { await f.close(); } }
});
test('ad assignment filters, unassignment and explicit move preserve endpoints', async () => {
  const f = await fixture(); const p = f.page;
  try {
    const checkbox = p.getByRole('checkbox', { name: 'Summer launch video', exact: true });
    await checkbox.click(); await p.getByText('Assigned here', { exact: true }).waitFor(); await p.getByRole('combobox', { name: 'Assignment', exact: true }).selectOption('available'); await p.getByText('No ads match your filters.').waitFor();
    await p.getByRole('combobox', { name: 'Assignment', exact: true }).selectOption('assigned'); await checkbox.click(); await p.getByText('No ads match your filters.').waitFor();
    await p.getByRole('combobox', { name: 'Assignment', exact: true }).selectOption('all'); await checkbox.click(); await p.getByText('Assigned here', { exact: true }).waitFor();
    await p.getByText('Move to another company', { exact: true }).click(); await p.getByLabel('Move Summer launch video to').selectOption(B); await p.getByRole('button', { name: 'Reassign Summer launch video' }).click(); await p.locator('.settings-ad .ui-badge').filter({ hasText: 'Available' }).waitFor();
    assert.deepEqual(f.mutations.map(m => m.method), ['PUT', 'DELETE', 'PUT', 'POST']); assert.equal(f.mutations.at(-1).path, `/api/companies/${A}/ads/${AD}/reassign`);
  } finally { await f.close(); }
});
test('409 keeps server ownership and safe actionable copy', async () => {
  const f = await fixture({ conflict: true }); const p = f.page;
  try { await p.getByRole('checkbox', { name: 'Summer launch video' }).click(); await p.getByRole('alert').filter({ hasText: 'ownership conflict' }).waitFor(); assert.equal(await p.getByRole('checkbox', { name: 'Summer launch video' }).isChecked(), false); assert.equal((await p.locator('body').innerText()).includes('PRIVATE_PROVIDER_SECRET'), false); } finally { await f.close(); }
});
test('Settings subpages are deep links with active state, history and one visible panel', async () => {
  const f = await fixture(); const p = f.page;
  try {
    const nav = p.getByRole('navigation', { name: 'Settings sections' });
    assert.equal(new URL(p.url()).pathname, '/settings/connections');
    await nav.getByRole('link', { name: 'Billing' }).click();
    assert.equal(new URL(p.url()).pathname, '/settings/billing');
    await p.getByRole('heading', { name: 'Billing', exact: true }).waitFor();
    if (process.env.V5_SCREENSHOT_DIR) await p.screenshot({ path: `${process.env.V5_SCREENSHOT_DIR}/billing-1440.png` });
    assert.equal(await nav.getByRole('link', { name: 'Billing' }).getAttribute('aria-current'), 'page');
    assert.equal(await p.locator('#settings-ownership:visible').count(), 0);
    assert.equal(await p.locator('#settings-meta:visible').count(), 0);
    assert.equal(await p.evaluate(() => scrollY), 0);
    await p.goBack(); await p.getByRole('heading', { name: 'Settings', exact: true }).waitFor();
    assert.equal(new URL(p.url()).pathname, '/settings/connections');
    await p.goForward(); await p.getByRole('heading', { name: 'Settings', exact: true }).waitFor();
    await p.reload(); await p.getByRole('heading', { name: 'Billing', exact: true }).waitFor();
  } finally { await f.close(); }
});
test('account control has one identity home and workspace switching leaves Settings', async () => {
  const f = await fixture(); const p = f.page;
  try {
    await p.locator('summary[aria-label="Account menu"]').click();
    await p.getByRole('link', { name: 'Account settings' }).click();
    assert.equal(new URL(p.url()).pathname, '/settings/account');
    assert.equal(await p.locator('.auth-account:visible').count(), 1);
    await p.getByRole('button', { name: 'Sign out' }).last().waitFor();
    await p.getByRole('navigation', { name: 'Company' }).getByRole('button').first().click();
    await p.getByRole('navigation', { name: 'Company' }).getByRole('button', { name: 'Other studio' }).click();
    await p.getByRole('navigation', { name: 'Company' }).getByRole('button', { name: 'Other studio' }).waitFor();
    assert.equal(new URL(p.url()).hash, '#overview');
  } finally { await f.close(); }
});
test('mobile Settings drills into a subsection and returns to the index', async () => {
  const f = await fixture({ width: 390 }); const p = f.page;
  try {
    await p.getByRole('link', { name: 'All settings' }).click();
    assert.equal(new URL(p.url()).pathname, '/settings/general');
    if (process.env.V5_SCREENSHOT_DIR) await p.screenshot({ path: `${process.env.V5_SCREENSHOT_DIR}/settings-index-390.png` });
    await p.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Workspace' }).click();
    assert.equal(new URL(p.url()).pathname, '/settings/workspace');
    await p.getByRole('heading', { name: 'Manage companies' }).waitFor();
    await p.getByRole('link', { name: 'All settings' }).click();
    await p.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Account' }).click();
    assert.equal(new URL(p.url()).pathname, '/settings/account');
    assert.equal(await p.locator('.settings-nav:visible').count(), 0);
  } finally { await f.close(); }
});
