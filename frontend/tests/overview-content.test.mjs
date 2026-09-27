import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { mkdir } from 'node:fs/promises';
import { createServer } from 'vite';
import { chromium } from 'playwright';
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const A = id(1), B = id(2), key = 'video-analyzer.active-company-id';
const item = (n, extra = {}) => ({ library_item_id: id(n), display_title: `Studio content ${n}`, platform: 'instagram', content_type: 'reel', published_at: '2026-09-20T12:00:00Z', analysis_state: 'completed', analyzed: true, summary: { duration_seconds: 24.5, width: 1080, height: 1920 }, ...extra });
const idea = { id: id(90), title: 'Show the craft behind the final result', concept: 'A behind-the-scenes story', status: 'draft', feedback: 'none', created_at: '2026-09-21T12:00:00Z', updated_at: '2026-09-21T12:00:00Z', target_platforms: ['instagram'] };
const populated = [item(10, { display_title: 'Instagram reel' }), item(11, { platform: 'facebook', content_type: 'video', display_title: 'Facebook video', analysis_state: 'processing', analyzed: false }), item(12, { display_title: 'September launch campaign', platform: 'meta_ads', content_type: 'ad', analysis_state: 'failed', analyzed: false }), item(13, { display_title: '', analysis_state: 'discovered', analyzed: false, published_at: null, summary: null })];
let server, browser, origin;
before(async () => {
  server = await createServer({ server: { host: '127.0.0.1', port: 5196 }, logLevel: 'error' });
  await server.listen(); origin = server.resolvedUrls.local[0]; browser = await chromium.launch();
  if (process.env.V5_SCREENSHOT_DIR) await mkdir(process.env.V5_SCREENSHOT_DIR, { recursive: true });
});
after(async () => { await browser?.close(); await server?.close(); });
async function fixture({ page = 'content', width = 1440, selected = A, linked = true, content = populated, ideas = [idea], intercept, ignoreAbort = false } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 1000 } });
  await context.addInitScript(({ selected, key, ignoreAbort }) => {
    if (selected) localStorage.setItem(key, selected);
    if (ignoreAbort) { const original = window.fetch.bind(window); window.fetch = (url, options) => original(url, { ...options, signal: undefined }); }
  }, { selected, key, ignoreAbort });
  const calls = [], errors = [];
  await context.route('**/api/**', async route => {
    const url = new URL(route.request().url()); calls.push(url);
    if (await intercept?.(route, url)) return;
    if (url.pathname === '/api/companies') return route.fulfill({ json: { companies: [A, B].map((company_id, i) => ({ company_id, name: i ? 'Beta' : 'Northline Studio', archived: false, accounts: linked ? [{ account_id: id(i + 3), platform: 'instagram', display_name: 'Studio Instagram' }] : [] })) } });
    if (url.pathname.endsWith('/content')) return route.fulfill({ json: { items: (url.searchParams.get('analyzed_only') === 'true' ? content.filter(c => c.analyzed) : content).slice(0, Number(url.searchParams.get('limit') || 20)), next_offset: null } });
    if (url.pathname.endsWith('/ideas')) return route.fulfill({ json: { items: ideas, next_cursor: null } });
    return route.fulfill({ json: { connected: false, accounts: [] } });
  });
  const p = await context.newPage(); p.setDefaultTimeout(7000);
  p.on('pageerror', e => errors.push(e.message));
  p.on('console', message => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()); });
  await p.goto(`${origin}#${page}`);
  return { p, calls, errors, close: () => context.close() };
}
const library = p => p.getByRole('region', { name: 'Company content library', exact: true });
const overview = p => p.locator('.cm-overview');
async function switchCompany(p) {
  const nav = p.getByRole('navigation', { name: 'Company', exact: true });
  await nav.getByRole('button').first().click(); await nav.getByRole('button', { name: 'Beta', exact: true }).click();
}
async function screenshot(p, name) { if (process.env.V5_SCREENSHOT_DIR) await p.screenshot({ path: `${process.env.V5_SCREENSHOT_DIR}/${name}.png`, fullPage: true }); }

test('Overview shows linked platforms, qualified source count, recent content and saved ideas', async () => {
  const f = await fixture({ page: 'overview' });
  try {
    await overview(f.p).getByText(idea.title, { exact: true }).waitFor();
    assert.match(await overview(f.p).innerText(), /1 analysed video/);
    assert.match(await overview(f.p).innerText(), /1 linked account/);
    assert.equal(await f.p.getByRole('heading', { level: 1 }).count(), 1);
    assert.equal(await overview(f.p).getByRole('link', { name: 'Generate idea', exact: true }).getAttribute('href'), '#generate');
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});
test('Overview does not present a paginated count as an exact total', async () => {
  const f = await fixture({ page: 'overview', intercept: async (r, u) => {
    if (!u.pathname.endsWith('/content') || u.searchParams.get('analyzed_only') !== 'true') return false;
    await r.fulfill({ json: { items: Array.from({ length: 20 }, (_, n) => item(n + 100)), next_offset: 20 } }); return true;
  } });
  try { await overview(f.p).getByText('20+', { exact: true }).waitFor(); await overview(f.p).getByText('At least 20 videos are ready to use as sources.').waitFor(); }
  finally { await f.close(); }
});
for (const state of ['no company', 'no accounts', 'no content', 'no analysis', 'no ideas']) test(`Overview empty state: ${state}`, async () => {
  const f = await fixture({ page: 'overview', selected: state === 'no company' ? null : A, linked: state !== 'no accounts', content: state === 'no content' ? [] : state === 'no analysis' ? [item(10, { analyzed: false, analysis_state: 'queued' })] : populated, ideas: [] });
  try {
    const title = ({ 'no company': 'No company selected', 'no accounts': 'Northline Studio is ready', 'no content': 'Waiting for your first content', 'no analysis': 'Your content is here. Analysis is next.', 'no ideas': 'Turn your content into a new idea' })[state];
    await f.p.getByRole('heading', { name: title, exact: true }).waitFor();
    if (state === 'no company') assert.equal(f.calls.some(u => u.pathname.endsWith('/content')), false);
    if (state === 'no accounts') await f.p.getByRole('button', { name: 'Connect/link Meta accounts' }).waitFor();
    await screenshot(f.p, `overview-${state.replaceAll(' ', '-')}`);
  } finally { await f.close(); }
});
test('Content renders safe labels, known statuses, format metadata and a neutral preview fallback', async () => {
  const f = await fixture();
  try {
    const list = library(f.p); await list.getByText('Showing 1–4 items').waitFor();
    for (const label of ['Analysed', 'Processing', 'Analysis failed', 'Not yet analysed', '1080 × 1920', 'Date unavailable']) assert.ok(await list.getByText(label, { exact: true }).count());
    assert.equal(await list.locator('img').count(), 0);
    assert.equal((await list.innerText()).includes(id(10)), false);
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});
test('Content applies supported filters, coalesces search requests, validates dates and resets pagination', async () => {
  const contentCalls = [];
  const f = await fixture({ intercept: async (r, u) => {
    if (!u.pathname.endsWith('/content') || u.searchParams.get('analyzed_only') === 'true') return false;
    contentCalls.push(u); await r.fulfill({ json: { items: [item(Number(u.searchParams.get('offset')) ? 30 : 10)], next_offset: Number(u.searchParams.get('offset')) ? null : 20 } }); return true;
  } });
  try {
    const p = f.p, list = library(p); await list.getByText('Studio content 10', { exact: true }).waitFor();
    await list.getByRole('button', { name: 'Next content' }).click(); await list.getByText('Studio content 30', { exact: true }).waitFor();
    const before = contentCalls.length;
    await list.getByLabel('Search content', { exact: true }).pressSequentially('launch', { delay: 15 });
    await list.getByText('Studio content 10', { exact: true }).waitFor();
    assert.equal(contentCalls.length, before + 1); assert.equal(contentCalls.at(-1).searchParams.get('search'), 'launch'); assert.equal(contentCalls.at(-1).searchParams.get('offset'), '0');
    for (const [label, value, param] of [['Content platform', 'facebook', 'platform'], ['Content type', 'video', 'content_type'], ['Sort by', 'asc', 'order']]) {
      await Promise.all([p.waitForResponse(r => new URL(r.url()).searchParams.get(param) === value), list.getByLabel(label, { exact: true }).selectOption(value)]);
      assert.equal(contentCalls.at(-1).searchParams.get(param), value);
    }
    await list.getByText('Publication dates', { exact: true }).click();
    await Promise.all([p.waitForResponse(r => new URL(r.url()).searchParams.get('published_from') === '2026-09-10T00:00:00.000Z'), list.getByLabel('Published from (UTC)').fill('2026-09-10')]);
    await Promise.all([p.waitForResponse(r => new URL(r.url()).searchParams.get('published_to') === '2026-09-20T23:59:59.999Z'), list.getByLabel('Published to (UTC)').fill('2026-09-20')]);
    const count = contentCalls.length;
    await list.getByLabel('Published to (UTC)').fill('2026-09-01');
    await list.getByRole('alert').waitFor(); await p.waitForTimeout(100); assert.equal(contentCalls.length, count);
    await list.getByRole('button', { name: 'Clear filters', exact: true }).click();
    await list.getByText('Studio content 10', { exact: true }).waitFor();
    assert.equal(contentCalls.at(-1).searchParams.has('search'), false);
    await list.getByLabel('Analysed only').check();
    await list.getByText('Showing 1–1 matching items').waitFor();
    assert.ok(f.calls.some(u => u.searchParams.get('analyzed_only') === 'true'));
  } finally { await f.close(); }
});
test('Content distinguishes empty library from no filter matches with useful recovery actions', async () => {
  const f = await fixture({ content: [] });
  try {
    const list = library(f.p); await list.getByRole('heading', { name: 'Your content library starts here' }).waitFor();
    await list.getByLabel('Search content').fill('nothing');
    await list.getByRole('heading', { name: 'No matching content' }).waitFor();
    await screenshot(f.p, 'content-no-matches');
    await list.getByRole('button', { name: 'Clear filters', exact: true }).last().click();
    await list.getByRole('heading', { name: 'Your content library starts here' }).waitFor();
  } finally { await f.close(); }
});
test('Content loading, safe API error and retry', async () => {
  let release, begun; const gate = new Promise(r => release = r), started = new Promise(r => begun = r); let fail = true;
  const f = await fixture({ intercept: async (r, u) => {
    if (!u.pathname.endsWith('/content') || u.searchParams.get('analyzed_only') === 'true') return false;
    begun(); await gate;
    await r.fulfill(fail ? { status: 503, json: { detail: 'SECRET TOKEN' } } : { json: { items: populated, next_offset: null } }); return true;
  } });
  try { await started; await library(f.p).getByText('Loading company content…').waitFor(); release(); await library(f.p).getByRole('alert').waitFor(); assert.equal((await library(f.p).innerText()).includes('SECRET'), false); fail = false; await library(f.p).getByRole('button', { name: 'Retry content' }).click(); await library(f.p).getByText('Showing 1–4 items').waitFor(); }
  finally { release(); await f.close(); }
});
test('Overview loading and partial errors retain successful panels and recover safely', async () => {
  let release; const gate = new Promise(r => release = r); let fail = true;
  const f = await fixture({ page: 'overview', intercept: async (r, u) => {
    if (!u.pathname.endsWith('/content') || u.searchParams.get('limit') !== '4') return false;
    await gate; await r.fulfill(fail ? { status: 503, json: { detail: 'SECRET' } } : { json: { items: populated, next_offset: null } }); return true;
  } });
  try { await overview(f.p).getByText('Loading recent content…').waitFor(); release(); await overview(f.p).getByRole('alert').waitFor(); await overview(f.p).getByText(idea.title, { exact: true }).waitFor(); assert.equal((await overview(f.p).innerText()).includes('SECRET'), false); fail = false; await overview(f.p).getByRole('button', { name: 'Refresh overview' }).click(); await overview(f.p).getByText('Facebook video', { exact: true }).waitFor(); }
  finally { release(); await f.close(); }
});
for (const destination of ['overview', 'content']) test(`${destination}: stale results cannot populate a newly selected company, even without fetch abort`, async () => {
  let release, begun; const gate = new Promise(r => release = r), started = new Promise(r => begun = r);
  const f = await fixture({ page: destination, ignoreAbort: true, content: [], ideas: [], intercept: async (r, u) => {
    if (!u.pathname.includes(A) || (!u.pathname.endsWith('/content') && !u.pathname.endsWith('/ideas'))) return false;
    begun(); await gate; await r.fulfill({ json: u.pathname.endsWith('/ideas') ? { items: [{ ...idea, title: 'Private Alpha idea' }], next_cursor: null } : { items: [item(10, { display_title: 'Private Alpha content' })], next_offset: null } }).catch(() => {}); return true;
  } });
  try { await started; await switchCompany(f.p); release(); await f.p.waitForTimeout(150); assert.equal((await f.p.locator('main').innerText()).includes('Private Alpha'), false); assert.equal((await f.p.locator('main').innerText()).includes('Northline Studio'), false); }
  finally { release(); await f.close(); }
});
test('Company switch clears visible old content and local filters', async () => {
  const f = await fixture({ intercept: async (r, u) => {
    if (!u.pathname.endsWith('/content')) return false;
    await r.fulfill({ json: { items: [item(10, { display_title: u.pathname.includes(A) ? 'Alpha content' : 'Beta content' })], next_offset: null } }); return true;
  } });
  try { const list = library(f.p); await list.getByText('Alpha content', { exact: true }).waitFor(); await list.getByLabel('Content type').selectOption('reel'); await switchCompany(f.p); await list.getByText('Beta content', { exact: true }).waitFor(); assert.equal(await list.getByText('Alpha content', { exact: true }).count(), 0); assert.equal(await list.getByLabel('Content type').inputValue(), ''); }
  finally { await f.close(); }
});
for (const width of [1440, 1280, 1024, 768, 390, 320]) test(`Overview and Content at ${width}px: no overflow, keyboard filters and readable actions`, async () => {
  const f = await fixture({ page: 'overview', width });
  try {
    await overview(f.p).getByText(idea.title, { exact: true }).waitFor();
    await screenshot(f.p, `overview-${width}`);
    for (const destination of ['overview', 'content']) {
      if (destination === 'content') { await overview(f.p).getByRole('link', { name: 'View library', exact: true }).click(); await library(f.p).getByText('Showing 1–4 items').waitFor(); }
      assert.equal(await f.p.title(), 'ContentMetric'); assert.equal(await f.p.locator('vite-error-overlay').count(), 0);
      assert.ok(await f.p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${destination} overflow at ${width}`);
      assert.equal(await f.p.getByRole('heading', { level: 1 }).count(), 1);
    }
    const search = library(f.p).getByLabel('Search content'); await search.focus();
    assert.equal(await search.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
    await f.p.keyboard.press('Tab'); assert.equal(await library(f.p).getByLabel('Content platform').evaluate(el => el === document.activeElement), true);
    await screenshot(f.p, `content-${width}`);
    await library(f.p).getByText('Publication dates', { exact: true }).click();
    assert.ok(await f.p.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});
