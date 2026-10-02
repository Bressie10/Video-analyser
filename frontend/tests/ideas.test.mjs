import { authAlias } from './authenticated.vite.mjs';
import assert from 'node:assert/strict';
import { test as nodeTest, before, after } from 'node:test';
import { createServer } from 'vite';
import { chromium } from 'playwright';
const test = (name, fn) => nodeTest(name, { timeout: 20000 }, fn);
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const A = id(1), B = id(2);
const idea = (n, extra = {}) => ({ id: id(n), company_id: A, title: `Idea ${n}`, concept: `Concept ${n}`, script: `Script ${n}`, status: 'draft', feedback: 'none', feedback_reason: null, target_platforms: ['facebook'], created_at: '2026-09-20T10:00:00Z', updated_at: '2026-09-21T10:00:00Z', publications: [], generation_brief: 'Our brief', profile_evidence: 'PRIVATE EVIDENCE', ...extra });
const pub = n => ({ library_item_id: id(n), title: `Post ${n}`, platform: 'facebook', available: true, created_at: '2026-09-20T10:00:00Z' });
let server, browser, origin;
before(async () => { server = await createServer({ resolve: { alias: authAlias }, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); await server.listen(); origin = server.resolvedUrls.local[0].replace(/\/$/, ''); browser = await chromium.launch({ headless: true }); });
after(async () => { await browser?.close(); await server?.close(); });
async function fixture(options = {}) {
  const p = await browser.newPage(); p.setDefaultTimeout(5000);
  const state = { items: options.items ?? [idea(10), idea(11, { title: 'B idea', company_id: B })], calls: [], failure: null, errors: [] };
  p.on('pageerror', e => state.errors.push(e.message));
  if (options.ignoreAbort) await p.addInitScript(() => { const original = window.fetch.bind(window); window.fetch = (url, options) => original(url, String(url).includes('/api/meta/companies/') ? { ...options, signal: undefined } : options); });
  await p.addInitScript(A => localStorage.setItem('video-analyzer.active-company-id', A), A);
  await p.route('**/api/**', async route => {
    const req = route.request(), u = new URL(req.url()), path = u.pathname, method = req.method();
    state.calls.push({ path, method, query: Object.fromEntries(u.searchParams), body: req.postDataJSON() });
    const send = (json, status = 200) => route.fulfill({ status, json });
    if (path === '/api/meta/test') return send({ connected: false });
    if (new URL(route.request().url()).pathname === '/api/me/companies') return route.fulfill({ json: { companies: [A, B].map(value => ({ id: typeof value === 'string' ? value : value.id, archived_at: null })) } });
    if (path === '/api/companies') return send({ companies: [A, B].map((c, i) => ({ company_id: c, name: i ? 'Beta' : 'Alpha', archived: !!options.archived && !i, accounts: [] })) });
    if (path.endsWith('/content')) return send({items:[],next_offset:null});
    if (options.intercept && await options.intercept(route, state)) return;
    const parts = path.split('/'), c = parts[4], kind = parts[5], itemId = parts[6];
    if (state.failure) { const failure = state.failure; state.failure = null; return failure === 'network' ? route.abort('failed') : send({ detail: 'PRIVATE FAILURE' }, failure); }
    if (kind === 'publication-options') {
      let pubs = [30,31].map(n => ({id:id(n),label:`Post ${n}`,platform:'facebook',content_type:'video',published_at:'2026-09-20T10:00:00Z'}));
      return send({ items: pubs, next_cursor: null });
    }
    if (kind === 'ideas' && !itemId) {
      let items = state.items.filter(i => i.company_id === c);
      const q = u.searchParams;
      if (q.get('search')) items = items.filter(i => `${i.title} ${i.concept} ${i.script}`.toLowerCase().includes(q.get('search').toLowerCase()));
      for (const key of ['status', 'feedback']) if (q.get(key)) items = items.filter(i => i[key] === q.get(key));
      if (q.get('target_platform')) items = items.filter(i => i.target_platforms.includes(q.get('target_platform')));
      if (q.get('created_from')) items = items.filter(i => i.created_at >= q.get('created_from'));
      if (q.get('created_to')) items = items.filter(i => i.created_at <= q.get('created_to'));
      if (q.get('after')) items = items.slice(items.findIndex(i => i.id === q.get('after')) + 1);
      return send({ items: items.slice(0, 2), next_cursor: items.length > 2 ? items[1].id : null });
    }
    const item = state.items.find(i => i.company_id === c && i.id === itemId);
    if (!item) return send({}, 404);
    if (method === 'PATCH') Object.assign(item, req.postDataJSON());
    if (parts[7] === 'feedback') { const body = req.postDataJSON(); item.feedback = body.feedback; item.feedback_reason = body.reason; }
    if (parts[7] === 'publications') { if (method === 'DELETE') item.publications = item.publications.filter(p => p.library_item_id !== parts[8]); else if (!item.publications.some(p => p.library_item_id === parts[8])) item.publications.push(pub(Number(parts[8].slice(-12)))); }
    return send(item);
  });
  await p.goto(`${origin}#ideas`);
  return { p, state, close: async () => { assert.deepEqual(state.errors, []); await p.close(); } };
}
const button = (p, name) => p.getByRole('button', { name, exact: true });
async function open(p, title = 'Idea 10') { await button(p, title).click(); await button(p, 'Edit').waitFor(); }
async function switchB(p) { const nav = p.getByRole('navigation', { name: 'Company', exact: true }); await nav.getByRole('button').first().click(); await nav.getByRole('button', { name: 'Beta', exact: true }).click(); }
async function saved(p) { await p.getByRole('status').filter({ hasText: /^Saved\.$/ }).waitFor(); }
test('keyboard feedback, lifecycle and publication actions expose focus and saved state', async () => {
  const f = await fixture(); const p = f.p;
  async function activate(name) {
    const control = button(p, name);
    await control.focus();
    assert.equal(await control.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
    await p.keyboard.press('Enter');
  }
  try {
    await p.getByLabel('Created from (UTC)').focus();
    for (let step = 0; step < 8; step++) {
      await p.keyboard.press('Tab');
      const focusedDate = await p.evaluate(() => {
        const input = document.activeElement;
        return input.matches('input[type=date]') ? getComputedStyle(input).outlineStyle : null;
      });
      if (focusedDate !== null) assert.equal(focusedDate, 'solid');
    }
    await activate('Idea 10'); await button(p, 'Edit').waitFor();
    await activate('Like'); await saved(p);
    assert.equal(await button(p, 'Like').getAttribute('aria-pressed'), 'true');
    await activate('Dislike');
    assert.equal(await p.getByLabel('Dislike reason (optional)').evaluate(el => el === document.activeElement), true);
    await p.keyboard.type('Make the opening clearer');
    await p.keyboard.press('Tab');
    assert.equal(await button(p, 'Save dislike').evaluate(el => el === document.activeElement), true);
    await p.keyboard.press('Enter'); await saved(p);
    assert.equal(f.state.items[0].feedback_reason, 'Make the opening clearer');
    await activate('Used'); await saved(p);
    assert.equal(await button(p, 'Used').getAttribute('aria-pressed'), 'true');
    await activate('Link published content'); await button(p, 'Link Post 30').waitFor();
    await activate('Link Post 30');
    await p.getByRole('dialog').getByRole('status').filter({ hasText: '1 linked' }).waitFor();
    await p.keyboard.press('Escape');
    assert.equal(await button(p, 'Link published content').evaluate(el => el === document.activeElement), true);
    await activate('Unlink Post 30'); await saved(p);
    assert.equal(f.state.items[0].publications.length, 0);
  } finally { await f.close(); }
});
test('company history and detail use current company and safe creation metadata', async () => { const f = await fixture(); try { await open(f.p); await f.p.getByText('Script 10', { exact: true }).waitFor(); assert.equal((await f.p.locator('body').innerText()).includes('PRIVATE EVIDENCE'), false); await button(f.p, 'Back to history').click(); await switchB(f.p); await button(f.p, 'B idea').waitFor(); assert.equal(await button(f.p, 'Idea 10').count(), 0); assert.ok(f.state.calls.some(c => c.path.includes(B))); } finally { await f.close(); } });
for (const [name, field, value, extra] of [
  ['search', 'Search ideas', 'Needle', { title: 'Needle' }], ['status', 'Status', 'used', { status: 'used' }], ['feedback', 'Feedback', 'liked', { feedback: 'liked' }], ['platform', 'Target platform', 'instagram', { target_platforms: ['instagram'] }], ['date from', 'Created from (UTC)', '2026-09-22', { created_at: '2026-09-23T10:00:00Z' }], ['date through', 'Created through (UTC)', '2026-09-19', { created_at: '2026-09-18T10:00:00Z' }]
]) test(`history ${name} filter returns matching results`, async () => { const f = await fixture({ items: [idea(10), idea(12, extra)] }); try { await button(f.p, 'Idea 10').waitFor(); const input = f.p.getByLabel(field, { exact: true }); if (['status', 'feedback', 'platform'].includes(name)) await input.selectOption(value); else await input.fill(value); await button(f.p, extra.title ?? 'Idea 12').waitFor(); await button(f.p, 'Idea 10').waitFor({ state: 'detached' }); await button(f.p, 'Clear filters').click(); await button(f.p, 'Idea 10').waitFor(); } finally { await f.close(); } });
test('load more keeps earlier ideas and filter changes reset pagination', async () => { const f = await fixture({ items: [idea(10), idea(12), idea(13)] }); try { await button(f.p, 'Load more ideas').click(); await button(f.p, 'Idea 13').waitFor(); assert.equal(await button(f.p, 'Idea 10').count(), 1); await f.p.getByLabel('Search ideas').fill('Idea 10'); await button(f.p, 'Idea 13').waitFor({ state: 'detached' }); } finally { await f.close(); } });
test('explicit edit Save persists all fields, Cancel restores saved values without autosave', async () => { const f = await fixture(); try { await open(f.p); await button(f.p, 'Edit').click(); for (const name of ['Title', 'Concept', 'Script']) await f.p.getByLabel(name, { exact: true }).fill(`New ${name}`); assert.equal(f.state.calls.filter(c => c.method === 'PATCH').length, 0); await button(f.p, 'Save').click(); await saved(f.p); assert.equal(f.state.items[0].title, 'New Title'); assert.equal(f.state.items[0].concept, 'New Concept'); assert.equal(f.state.items[0].script, 'New Script'); await button(f.p, 'Edit').click(); await f.p.getByLabel('Title', { exact: true }).fill('Throw away'); await button(f.p, 'Cancel edit').click(); await button(f.p, 'Edit').click(); assert.equal(await f.p.getByLabel('Title', { exact: true }).inputValue(), 'New Title'); } finally { await f.close(); } });
test('unsaved editing uses global company switch guard and confirmed switch clears detail', async () => { const f = await fixture(); try { await open(f.p); await button(f.p, 'Edit').click(); await f.p.getByLabel('Title', { exact: true }).fill('Unsaved'); await switchB(f.p); await f.p.getByRole('dialog').waitFor(); await button(f.p, 'Stay here').click(); assert.equal(await f.p.getByLabel('Title', { exact: true }).inputValue(), 'Unsaved'); await switchB(f.p); await button(f.p, 'Continue and switch').click(); await button(f.p, 'B idea').waitFor(); assert.equal(await f.p.getByLabel('Title', { exact: true }).count(), 0); } finally { await f.close(); } });
test('Like, Dislike with and without reason, clear feedback', async () => { const f = await fixture(); try { await open(f.p); await button(f.p, 'Like').click(); await saved(f.p); assert.equal(f.state.items[0].feedback, 'liked'); for (const reason of ['Too generic', '']) { await button(f.p, 'Dislike').click(); await f.p.getByLabel('Dislike reason (optional)').fill(reason); await button(f.p, 'Save dislike').click(); await saved(f.p); assert.equal(f.state.items[0].feedback, 'disliked'); assert.equal(f.state.items[0].feedback_reason, reason || null); } await button(f.p, 'Clear feedback').click(); await saved(f.p); assert.equal(f.state.items[0].feedback, 'none'); assert.equal(f.state.items[0].feedback_reason, null); } finally { await f.close(); } });
test('all lifecycle statuses allow backward transitions', async () => { const f = await fixture(); try { await open(f.p); for (const status of ['Used', 'Published', 'Draft', 'Discarded', 'Used', 'Draft']) { await button(f.p, status).click(); await saved(f.p); assert.equal(f.state.items[0].status, status.toLowerCase()); assert.equal(await button(f.p, status).getAttribute('aria-pressed'), 'true'); } } finally { await f.close(); } });
test('link one then multiple company-scoped publications and unlink', async () => { const f = await fixture(); try { await open(f.p); await button(f.p, 'Link published content').click(); await button(f.p, 'Link Post 30').click(); await f.p.getByRole('status').filter({ hasText: '1 linked' }).waitFor(); await button(f.p, 'Link Post 31').click(); await f.p.getByRole('status').filter({ hasText: '2 linked' }).waitFor(); await button(f.p, 'Done').click(); assert.equal(f.state.items[0].publications.length, 2); await button(f.p, 'Unlink Post 30').click(); await saved(f.p); assert.deepEqual(f.state.items[0].publications.map(p => p.library_item_id), [id(31)]); assert.ok(f.state.calls.filter(c => c.path.includes('publication-options')).every(c => c.path.includes(A))); } finally { await f.close(); } });
test('unavailable historical links display without fetching inaccessible content', async () => { const f = await fixture({ items: [idea(10, { publications: [{ ...pub(30), available: false }] })] }); try { await open(f.p); await f.p.getByText(/Content unavailable for live metrics/).waitFor(); assert.equal(f.state.calls.some(c => c.path.includes(id(30))), false); await button(f.p, 'Unlink Post 30').click(); await saved(f.p); assert.equal(f.state.items[0].publications.length, 0); } finally { await f.close(); } });
for (const code of [404, 403, 'network']) test(`detail handles ${code} with safe message and retry`, async () => { const f = await fixture(); try { await button(f.p, 'Idea 10').waitFor(); f.state.failure = code; await button(f.p, 'Idea 10').click(); await f.p.getByRole('alert').waitFor(); assert.equal((await f.p.locator('body').innerText()).includes('PRIVATE FAILURE'), false); await button(f.p, 'Retry').click(); await button(f.p, 'Edit').waitFor(); } finally { await f.close(); } });
test('409 retains edits for cancel and reload', async () => { const f = await fixture(); try { await open(f.p); await button(f.p, 'Edit').click(); await f.p.getByLabel('Title', { exact: true }).fill('Keep this'); f.state.failure = 409; await button(f.p, 'Save').click(); await f.p.getByRole('alert').waitFor(); assert.equal(await f.p.getByLabel('Title', { exact: true }).inputValue(), 'Keep this'); await button(f.p, 'Cancel edit').click(); await button(f.p, 'Reload idea').click(); await button(f.p, 'Edit').waitFor(); assert.equal(f.state.items[0].title, 'Idea 10'); } finally { await f.close(); } });
test('empty history, invalid date range and archived selection', async () => { const f = await fixture({ items: [] }); try { await f.p.getByText('Your ideas will appear here').waitFor(); await f.p.getByLabel('Created from (UTC)').fill('2026-09-22'); await f.p.getByLabel('Created through (UTC)').fill('2026-09-01'); await f.p.getByRole('alert').waitFor(); } finally { await f.close(); } const a = await fixture({ role: "owner", archived: true }); try { await a.p.getByRole('heading', { name: 'No company selected' }).waitFor(); assert.equal(a.state.calls.some(c => c.path.includes('/ideas')), false); } finally { await a.close(); } });
for (const resource of ['history', 'detail', 'mutation']) test(`late Company A ${resource} cannot populate Company B`, async () => {
  let release, began; const gate = new Promise(r => release = r), started = new Promise(r => began = r);
  const f = await fixture({ ignoreAbort: true, intercept: async route => { const path = new URL(route.request().url()).pathname; const matches = resource === 'history' ? path === `/api/meta/companies/${A}/ideas` : path === `/api/meta/companies/${A}/ideas/${id(10)}` && route.request().method() === (resource === 'mutation' ? 'PATCH' : 'GET'); if (!matches) return false; began(); await gate; try { await route.fulfill({ json: resource === 'history' ? { items: [idea(10)], next_cursor: null } : idea(10) }); } catch {} return true; } });
  try { if (resource === 'detail') await button(f.p, 'Idea 10').click(); if (resource === 'mutation') { await open(f.p); await button(f.p, 'Used').click(); } await started; await switchB(f.p); await button(f.p, 'B idea').waitFor(); release(); await f.p.waitForTimeout(100); assert.equal((await f.p.locator('body').innerText()).includes('Idea 10'), false); assert.equal(await f.p.getByRole('alert').count(), 0); } finally { release(); await f.close(); }
});
for (const width of [1440, 1280, 1024, 768, 390, 320]) test(`responsive ${width}px and keyboard focus through editor and picker`, async () => { const f = await fixture(); try { await f.p.setViewportSize({ width, height: 900 }); await button(f.p, 'Idea 10').waitFor(); assert.equal(await f.p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); await f.p.screenshot({ path: `/tmp/v5-ideas-history-${width}.png`, fullPage: true }); await button(f.p, 'Idea 10').focus(); await f.p.keyboard.press('Enter'); await button(f.p, 'Edit').waitFor(); await button(f.p, 'Edit').focus(); await f.p.keyboard.press('Enter'); assert.equal(await f.p.getByLabel('Title', { exact: true }).evaluate(e => e === document.activeElement), true); assert.equal(await f.p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); await f.p.keyboard.press('Tab'); assert.equal(await f.p.getByLabel('Concept', { exact: true }).evaluate(e => e === document.activeElement), true); await button(f.p, 'Cancel edit').click(); await button(f.p, 'Link published content').focus(); await f.p.keyboard.press('Enter'); await f.p.getByRole('dialog').waitFor(); await button(f.p, 'Link Post 30').waitFor(); assert.equal(await f.p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); await f.p.screenshot({ path: `/tmp/v5-ideas-picker-${width}.png`, fullPage: true }); await f.p.keyboard.press('Escape'); assert.equal(await button(f.p, 'Link published content').evaluate(e => e === document.activeElement), true); await f.p.evaluate(() => window.scrollTo(0, 0)); await f.p.screenshot({ path: `/tmp/v5-ideas-detail-${width}.png`, fullPage: true }); } finally { await f.close(); } });

test('history network failure retries without presenting an empty history', async () => {
  let failed = false;
  const f = await fixture({ intercept: async route => { if (!failed && new URL(route.request().url()).pathname.endsWith('/ideas')) { failed = true; await route.abort('failed'); return true; } return false; } });
  try { await f.p.getByRole('alert').waitFor(); assert.equal(await f.p.getByText('Your ideas will appear here').count(), 0); await button(f.p, 'Retry').click(); await button(f.p, 'Idea 10').waitFor(); } finally { await f.close(); }
});
test('content unavailable during linking reports an error and keeps existing associations', async () => {
  const f = await fixture({ items: [idea(10, { publications: [pub(30)] })] });
  try { await open(f.p); await button(f.p, 'Link published content').click(); await button(f.p, 'Link Post 31').waitFor(); f.state.failure = 404; await button(f.p, 'Link Post 31').click(); await f.p.getByRole('dialog').getByRole('alert').waitFor(); assert.equal(f.state.items[0].publications.length, 1); await button(f.p, 'Done').click(); await button(f.p, 'Unlink Post 30').waitFor(); } finally { await f.close(); }
});

test('V5 compact history exposes platforms and hides full scripts; no matches can be cleared', async () => {
  const f = await fixture(); try {
    await button(f.p, 'Idea 10').waitFor();
    await f.p.locator('.idea-row').getByText('Facebook', { exact: true }).waitFor();
    assert.equal(await f.p.getByText('Script 10', { exact: true }).count(), 0);
    await f.p.getByLabel('Search ideas').fill('No such idea');
    await f.p.getByRole('heading', { name: 'No ideas match these filters.' }).waitFor();
    await button(f.p, 'Clear filters').click(); await button(f.p, 'Idea 10').waitFor();
    await f.p.getByRole('link', { name: 'Generate idea', exact: true }).click();
    assert.equal(new URL(f.p.url()).hash, '#generate');
  } finally { await f.close(); }
});
test('V5 navigation preserves unsaved edits and back is protected until cancel', async () => {
  const f = await fixture(); try {
    await open(f.p); await button(f.p, 'Edit').click();
    await f.p.getByLabel('Title', { exact: true }).fill('Keep my draft');
    assert.equal(await button(f.p, 'Back to history').isDisabled(), true);
    await f.p.getByRole('link', { name: 'Content', exact: true }).click();
    await f.p.getByRole('link', { name: 'Ideas', exact: true }).click();
    assert.equal(await f.p.getByLabel('Title', { exact: true }).inputValue(), 'Keep my draft');
    await button(f.p, 'Cancel edit').click(); await button(f.p, 'Back to history').click();
    await button(f.p, 'Idea 10').waitFor();
  } finally { await f.close(); }
});
test('V5 empty publication options and keyboard filter disclosure', async () => {
  const f = await fixture({ intercept: async route => {
    if (!new URL(route.request().url()).pathname.endsWith('/publication-options')) return false;
    await route.fulfill({ json: { items: [], next_cursor: null } }); return true;
  } }); try {
    await button(f.p, 'Idea 10').waitFor();
    const disclosure = f.p.locator('.idea-filter-disclosure summary');
    await disclosure.focus(); await f.p.keyboard.press('Enter');
    assert.equal(await f.p.getByLabel('Status', { exact: true }).isVisible(), false);
    await f.p.keyboard.press('Enter'); assert.equal(await f.p.getByLabel('Status', { exact: true }).isVisible(), true);
    await open(f.p); await button(f.p, 'Link published content').click();
    await f.p.getByText('No accessible published content found.').waitFor();
    await f.p.keyboard.press('Escape'); assert.equal(await button(f.p, 'Link published content').evaluate(e => e === document.activeElement), true);
  } finally { await f.close(); }
});

test('V5 long-form workspace is readable at every required viewport', async () => {
  const title = 'Show the craft behind your morning coffee';
  const script = 'HOOK — Start with the sound of coffee beans pouring into the grinder.\n\n“Your morning coffee starts long before the first sip.”\n\nSTORY — Follow the barista from weighing the beans to pouring a slow, deliberate latte. Use close-up shots of the grind, the extraction and the milk texture. Let the natural café sounds carry the scene.\n\n“Every small detail changes what ends up in your cup. Here is how we make yours.”\n\nCLOSE — Hand the finished cup across the counter.\n\n“Come find your new morning ritual. Save this for your next coffee stop.”';
  const f = await fixture({ items: [idea(10, { title, concept: 'A behind-the-scenes look at the care that goes into every cup. Bring the audience into the café and give them a reason to visit.', script, target_platforms: ['facebook', 'instagram'] }), idea(12, { title: 'Meet the people behind the counter', status: 'used', feedback: 'liked' })] });
  try {
    for (const width of [1440, 1280, 1024, 768, 390, 320]) {
      await f.p.setViewportSize({ width, height: 900 });
      await button(f.p, title).waitFor();
      const filters = f.p.locator('.idea-filter-disclosure');
      if (width <= 390 && await filters.getAttribute('open') !== null) await filters.locator('summary').click();
      await f.p.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
      assert.equal(await f.p.title(), 'ContentMetric');
      assert.equal(await f.p.locator('vite-error-overlay').count(), 0);
      await f.p.screenshot({ path: `/tmp/v5-ideas-review-history-${width}.png`, fullPage: true });
      await open(f.p, title);
      const text = f.p.locator('.script');
      assert.equal(await text.innerText(), script);
      const typography = await text.evaluate(el => ({ size: parseFloat(getComputedStyle(el).fontSize), height: parseFloat(getComputedStyle(el).lineHeight) }));
      assert.ok(typography.size >= 15 && typography.height >= typography.size * 1.6);
      assert.equal(await f.p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await f.p.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
      await f.p.screenshot({ path: `/tmp/v5-ideas-review-detail-${width}.png`, fullPage: true });
      await button(f.p, 'Back to history').click();
    }
  } finally { await f.close(); }
});
