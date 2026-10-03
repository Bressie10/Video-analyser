import { authAlias } from './authenticated.vite.mjs';
import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const companyId = id(1);
const content = state => ({ library_item_id: id(2), display_title: 'Published post', platform: 'instagram', content_type: 'reel', published_at: null, analysis_state: state, analyzed: state === 'completed', summary: null });
let server, browser, origin;
before(async () => { server = await createServer({ resolve: { alias: authAlias }, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); await server.listen(); origin = server.resolvedUrls.local[0]; browser = await chromium.launch(); });
after(async () => { await browser?.close(); await server?.close(); });

async function app({ accounts = [], items = [], ideas = [], sources = [], contentError = false, role = 'owner' } = {}, page = 'content') {
  const context = await browser.newContext();
  const errors = []; let contentReads = 0; const analysisCalls = [];
  await context.addInitScript(companyId => localStorage.setItem('video-analyzer.active-company-id', companyId), companyId);
  await context.route('**/api/**', route => {
    const url = new URL(route.request().url()); const path = url.pathname;
    if (path === '/api/me/companies') return route.fulfill({ json: { companies: [{ id: companyId, archived_at: null }] } });
    if (path === '/api/companies') return route.fulfill({ json: { companies: [{ company_id: companyId, name: 'Alpha', role, archived: false, accounts: accounts.map((platform, i) => ({ account_id: id(10 + i), display_name: platform, platform })) }] } });
    if (path.endsWith('/content/analyze')) { analysisCalls.push(route.request().postDataJSON()); items = items.map(item => ({ ...item, analysis_state: 'queued' })); return route.fulfill({ status: 202, json: { job_id: id(40) } }); }
    if (path.endsWith('/content')) {
      if (url.searchParams.get('analyzed_only') === 'true') return route.fulfill({ json: { items: sources, next_offset: null } });
      contentReads++;
      return contentError ? route.fulfill({ status: 503, json: { detail: 'PRIVATE PROVIDER ERROR' } }) : route.fulfill({ json: { items, next_offset: null } });
    }
    if (path.endsWith('/ideas')) return route.fulfill({ json: { items: ideas, next_cursor: null } });
    if (path === '/api/meta/test') return route.fulfill({ json: { connected: false } });
    if (path.endsWith('/profiles')) return route.fulfill({ json: { profiles: [] } });
    return route.fulfill({ json: { accounts: [] } });
  });
  const p = await context.newPage(); p.setDefaultTimeout(5000);
  p.on('pageerror', error => errors.push(error.message));
  await p.goto(`${origin}#${page}`);
  return { p, errors, analysisCalls, contentReads: () => contentReads,
    completeAnalysis() { items = items.map(item => ({ ...item, analysis_state: 'completed', analyzed: true })); sources = [...items]; },
    close: () => context.close() };
}

test('Content starts existing analysis batch and keeps member controls hidden', async () => {
  const owner = await app({ accounts: ['instagram'], items: [content('discovered')] });
  try {
    for (const width of [1440, 1024, 768, 390, 320]) {
      await owner.p.setViewportSize({ width, height: 900 });
      assert.equal(await owner.p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `analysis action overflow at ${width}`);
    }
    await owner.p.getByRole('button', { name: 'Analyze', exact: true }).focus();
    assert.equal(await owner.p.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), 'solid');
    await owner.p.getByRole('button', { name: 'Analyze', exact: true }).click();
    await owner.p.getByText('Processing', { exact: true }).waitFor();
    assert.deepEqual(owner.analysisCalls, [{ item_id: id(2) }]);
    assert.deepEqual(owner.errors, []);
  } finally { await owner.close(); }
  const member = await app({ accounts: ['instagram'], items: [content('discovered')], role: 'member' });
  try {
    await member.p.getByText('Not yet analysed').waitFor();
    assert.equal(await member.p.getByRole('button', { name: 'Analyze', exact: true }).count(), 0);
  } finally { await member.close(); }
});

test('completed Content analysis refreshes Generate sources on navigation', async () => {
  const f = await app({ accounts: ['instagram'], items: [content('discovered')] });
  try {
    await f.p.getByRole('button', { name: 'Analyze', exact: true }).click();
    await f.p.getByText('Processing', { exact: true }).waitFor();
    f.completeAnalysis();
    await f.p.getByRole('button', { name: 'Refresh analysis status' }).click();
    await f.p.getByText('Analysed', { exact: true }).waitFor();
    await f.p.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Generate' }).click();
    await f.p.getByRole('button', { name: 'Generate idea', exact: true }).waitFor();
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});

test('Content separates no publishing source from linked but empty, with keyboard navigation', async () => {
  for (const [accounts, title, action] of [[['meta_ads'], 'Connect your content source', 'Go to Settings'], [['instagram'], 'No content here yet', 'Review linked accounts']]) {
    const f = await app({ accounts });
    try {
      await f.p.getByRole('heading', { name: title }).waitFor();
      const link = f.p.getByRole('link', { name: action });
      await link.focus(); assert.equal(await link.evaluate(node => document.activeElement === node), true);
      await f.p.keyboard.press('Enter'); assert.equal(new URL(f.p.url()).hash, '#settings');
      assert.deepEqual(f.errors, []);
    } finally { await f.close(); }
  }
});

test('Content explains not analyzed, processing and failure without raw errors', async () => {
  for (const [state, title] of [['discovered', 'Analyze content to inform your ideas'], ['queued', 'Analysis is in progress'], ['failed', 'Some analysis needs attention']]) {
    const f = await app({ accounts: ['instagram'], items: [content(state)] });
    try {
      await f.p.getByRole('heading', { name: title }).waitFor();
      await f.p.getByText(state === 'failed' ? 'Analysis failed' : state === 'queued' ? 'Processing' : 'Not yet analysed', { exact: true }).waitFor();
      if (state !== 'discovered') {
        const refresh = f.p.getByRole('button', { name: 'Refresh analysis status' });
        await refresh.focus(); await f.p.keyboard.press('Enter');
        await f.p.waitForFunction(() => document.querySelector('.cm-content-results') !== null);
        assert.ok(f.contentReads() >= 2);
      }
      assert.equal((await f.p.locator('body').innerText()).includes('PRIVATE PROVIDER ERROR'), false);
    } finally { await f.close(); }
  }
  const f = await app({ accounts: ['instagram'], contentError: true });
  try { await f.p.getByRole('button', { name: 'Retry content' }).waitFor(); assert.equal((await f.p.locator('body').innerText()).includes('PRIVATE PROVIDER ERROR'), false); } finally { await f.close(); }
});

test('Generate hides its form without analyzed sources and keeps it with sources', async () => {
  const empty = await app({ accounts: ['instagram'] }, 'generate');
  try {
    await empty.p.getByRole('heading', { name: 'Analyze some content first' }).waitFor();
    assert.equal(await empty.p.locator('.generation form').count(), 0);
    const link = empty.p.getByRole('link', { name: 'Go to Content' });
    await link.focus(); await empty.p.keyboard.press('Enter'); assert.equal(new URL(empty.p.url()).hash, '#content');
  } finally { await empty.close(); }
  const ready = await app({ accounts: ['instagram'], sources: [content('completed')] }, 'generate');
  try { await ready.p.getByRole('button', { name: 'Generate idea', exact: true }).waitFor(); assert.equal(await ready.p.locator('.generation form').count(), 1); } finally { await ready.close(); }
});

test('Ideas empty action follows known publishing prerequisite and populated history remains', async () => {
  for (const [accounts, action, destination] of [[[], 'Go to Content', '#content'], [['instagram'], 'Generate an idea', '#generate']]) {
    const f = await app({ accounts }, 'ideas');
    try {
      await f.p.getByRole('heading', { name: 'Your ideas will appear here' }).waitFor();
      const link = f.p.locator('.idea-empty').getByRole('link', { name: action });
      await link.focus(); await f.p.keyboard.press('Enter'); assert.equal(new URL(f.p.url()).hash, destination);
    } finally { await f.close(); }
  }
  const f = await app({ accounts: ['instagram'], ideas: [{ id: id(30), title: 'Saved idea', concept: 'A practical concept', target_platforms: ['instagram'], status: 'draft', feedback: 'none', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }] }, 'ideas');
  try { await f.p.getByRole('button', { name: 'Saved idea' }).waitFor(); assert.equal(await f.p.getByRole('heading', { name: 'Your ideas will appear here' }).count(), 0); } finally { await f.close(); }
});

test('activation states fit five widths without document overflow', async () => {
  for (const [page, title, selector] of [['content', 'Connect your content source', '.cm-library .ui-empty-state'], ['generate', 'Analyze some content first', '.generate-workspace .ui-empty-state'], ['ideas', 'Your ideas will appear here', '.ideas-workspace .ui-empty-state']]) {
    const f = await app({ accounts: [] }, page);
    try {
      await f.p.getByRole('heading', { name: title }).waitFor();
      for (const width of [1440, 1024, 768, 390, 320]) {
        await f.p.setViewportSize({ width, height: 900 });
        assert.equal(await f.p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${page} overflow at ${width}`);
        assert.equal(await f.p.locator(selector).evaluate(node => getComputedStyle(node).minHeight), width <= 700 ? '0px' : '280px');
      }
      await f.p.screenshot({ path: `/private/tmp/contentmetric-v7-${page}-empty-320.png`, fullPage: true });
    } finally { await f.close(); }
  }
});
