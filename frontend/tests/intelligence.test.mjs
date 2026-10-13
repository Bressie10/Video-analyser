import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { authAlias } from './authenticated.vite.mjs';

let server, browser, origin;
const company = '00000000-0000-4000-8000-000000000001';
const account = '00000000-0000-4000-8000-000000000002';
const citation = { video_ref: 'video_demo', evidence_ref: 'video_demo:transcript:0', evidence_type: 'transcript', timestamp_seconds: 1.5, excerpt: 'Offer spoken here' };
const difference = { description: 'The offer is spoken in more higher-group videos.', higher_group_support: 3, lower_group_support: 1,
  higher_group_size: 3, lower_group_size: 3, confidence: 'low', evidence_refs: [citation], counterexamples: [{ ...citation, evidence_ref: 'video_demo:ocr:1', evidence_type: 'ocr', excerpt: 'Offer card' }] };
const hypothesis = { hypothesis: 'Test whether spoken offer presence may be associated with a different CTR.', variable_to_test: 'spoken offer presence',
  control_condition: 'Offer is shown without speech.', variant_condition: 'Offer is spoken.', primary_metric: 'ctr',
  what_to_hold_constant: ['audience', 'budget'], limitations: ['Observational association only.'],
  source_difference: difference.description, counterevidence: difference.counterexamples };
const base = { metric: { description: 'click-through rate', unit: 'percent' }, cohort: { date_start: '2026-01-01', date_stop: '2026-01-07', distinct_ads: 6, peer_count: 5 },
  performance: { summary: 'Among 5 comparable peer ads, CTR was above the cohort median.', notable_metrics: [{ observation: 'Click-through rate was above this comparison cohort\'s median.' }],
    metric_facts: { target_value: '2', median: '1', ratio: '2', percentile: 80, description: 'click-through rate' }, limitations: [] },
  content_differences: [difference], hypotheses: [hypothesis], abstentions: [] };

before(async () => {
  server = await createServer({ resolve: { alias: authAlias }, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  await server.listen(); origin = server.resolvedUrls.local[0]; browser = await chromium.launch();
});
after(async () => { await browser?.close(); await server?.close(); });

async function app(response = base, { linked = true, hold = false, status = 200 } = {}) {
  const context = await browser.newContext(); const calls = [], errors = [];
  await context.addInitScript(id => localStorage.setItem('video-analyzer.active-company-id', id), company);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/intelligence')) {
      calls.push(route.request().postDataJSON());
      if (hold) await gate;
      return route.fulfill({ status, json: status === 200 ? response : { detail: 'SECRET INTERNAL PROVIDER TEXT' } }).catch(() => {});
    }
    if (path === '/api/companies') return route.fulfill({ json: { companies: [{ company_id: company, name: 'Alpha', role: 'owner', archived: false,
      accounts: linked ? [{ account_id: account, display_name: 'Owned Ads', platform: 'meta_ads' }] : [] }] } });
    if (path === '/api/meta/test') return route.fulfill({ json: { connected: false } });
    if (path === '/api/me/companies') return route.fulfill({ json: { companies: [{ id: company, archived_at: null }] } });
    return route.fulfill({ json: { items: [], next_offset: null, accounts: [] } });
  });
  const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto(`${origin}#intelligence`);
  return { page, calls, errors, release, close: () => context.close() };
}
async function submit(page) {
  await page.getByLabel('Start date').fill('2026-01-01');
  await page.getByLabel('End date').fill('2026-01-07');
  await page.getByRole('button', { name: 'Run Creative Intelligence' }).click();
}

test('full result uses exact request fields and renders performance, evidence, and one experiment', async () => {
  const f = await app(); try {
    await submit(f.page); await f.page.getByRole('heading', { name: 'What to test next' }).waitFor();
    assert.deepEqual(f.calls, [{ account_id: account, metric_id: 'ctr', date_start: '2026-01-01', date_stop: '2026-01-07' }]);
    assert.equal(await f.page.getByText('Higher group 3/3 · Lower group 1/3').count(), 1);
    assert.equal(await f.page.getByText('Offer spoken here').count(), 1);
    assert.equal(await f.page.getByText('Offer card').count(), 2);
    assert.equal(await f.page.getByText('Control').count(), 1);
    assert.equal(await f.page.title(), 'ContentMetric');
    await f.page.screenshot({ path: '/private/tmp/v9-stage82-intelligence-desktop.png', fullPage: true });
    await f.page.setViewportSize({ width: 390, height: 844 });
    await f.page.screenshot({ path: '/private/tmp/v9-stage82-intelligence-mobile.png', fullPage: true });
    assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});

test('three hypotheses render as three experiments', async () => {
  const f = await app({ ...base, hypotheses: [0, 1, 2].map(i => ({ ...hypothesis, hypothesis: `${hypothesis.hypothesis} ${i}` })) });
  try { await submit(f.page); await f.page.getByRole('heading', { name: 'What to test next' }).waitFor();
    assert.equal(await f.page.getByText('Experiment to try').count(), 3);
  } finally { await f.close(); }
});

test('performance-only result gives analyzed evidence state without experiments', async () => {
  const f = await app({ ...base, content_differences: [], hypotheses: [], abstentions: ['insufficient_source_video_coverage'] });
  try { await submit(f.page); await f.page.getByText('There isn’t enough analyzed video evidence yet to compare creative differences.').waitFor();
    assert.equal(await f.page.getByRole('heading', { name: 'What to test next' }).count(), 0);
  } finally { await f.close(); }
});

test('insufficient cohort and disconnected Meta render normal states', async () => {
  for (const abstention of ['insufficient_historical_cohort', 'meta_disconnected']) {
    const f = await app({ ...base, performance: null, content_differences: [], hypotheses: [], abstentions: [abstention] });
    try { await submit(f.page); await f.page.getByRole('heading', { name: 'Performance' }).waitFor();
      await f.page.getByText(abstention === 'meta_disconnected' ? 'Meta is disconnected.' : 'ContentMetric needs more comparable ads', { exact: false }).waitFor();
      assert.equal(await f.page.getByRole('heading', { name: 'What differed' }).count(), 0);
    } finally { await f.close(); }
  }
});

test('unlinked Meta points to Settings without an intelligence call', async () => {
  const f = await app(base, { linked: false }); try {
    await f.page.getByText('No linked Meta Ads account is available.', { exact: false }).waitFor();
    assert.equal(f.calls.length, 0);
  } finally { await f.close(); }
});

test('media unavailable keeps performance and hides experiments', async () => {
  const f = await app({ ...base, content_differences: [], hypotheses: [], abstentions: ['source_media_unavailable'] });
  try { await submit(f.page); await f.page.getByText('Source media could not be accessed.', { exact: false }).waitFor();
    assert.equal(await f.page.getByText(base.performance.summary).count(), 1);
  } finally { await f.close(); }
});

test('loading locks duplicate submits and rerender does not repeat request', async () => {
  const f = await app(base, { hold: true }); try {
    await submit(f.page); await f.page.getByText('Comparing performance and creative evidence…').waitFor();
    await f.page.locator('.intelligence-form').evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
    await f.page.evaluate(() => window.dispatchEvent(new Event('hashchange')));
    await f.page.setViewportSize({ width: 390, height: 844 });
    await f.page.screenshot({ path: '/private/tmp/v9-stage82-intelligence-loading-mobile.png' });
    assert.equal(await f.page.getByRole('button', { name: 'Run Creative Intelligence' }).isDisabled(), true);
    assert.equal(f.calls.length, 1); f.release();
    await f.page.getByRole('heading', { name: 'What differed' }).waitFor(); assert.equal(f.calls.length, 1);
  } finally { f.release(); await f.close(); }
});

test('API errors never show internal detail', async () => {
  for (const status of [401, 422, 503]) {
    const f = await app(base, { status }); try {
      await submit(f.page); await f.page.getByRole('alert').waitFor();
      assert.equal((await f.page.locator('body').innerText()).includes('SECRET INTERNAL PROVIDER TEXT'), false);
    } finally { await f.close(); }
  }
});

test('malformed successful response shows a safe error', async () => {
  const f = await app({ secret: 'SECRET INTERNAL PROVIDER TEXT' });
  try { await submit(f.page); await f.page.getByRole('alert').waitFor();
    assert.equal((await f.page.locator('body').innerText()).includes('SECRET INTERNAL PROVIDER TEXT'), false);
  } finally { await f.close(); }
});
