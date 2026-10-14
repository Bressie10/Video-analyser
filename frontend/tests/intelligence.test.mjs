import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { authAlias } from './authenticated.vite.mjs';

let server, browser, origin;
const company = '00000000-0000-4000-8000-000000000001';
const account = '00000000-0000-4000-8000-000000000002';
const refs = 'ABCDEF'.split('').map(letter => `video_${letter}`);
const groups = { higher: [2.1, 1.9, 1.8].map((value, index) => ({ video_ref: refs[index], metric_value: String(value), percentile: index === 2 ? 80 : null })),
  lower: [1.0, 0.8, 0.6].map((value, index) => ({ video_ref: refs[index + 3], metric_value: String(value), percentile: null })), middle_excluded_count: 0 };
const cited = (letter, type, time, text) => ({ video_ref: `video_${letter}`, evidence_ref: `video_${letter}:${type}:${time}`, evidence_type: type, timestamp_seconds: time, ...(text ? { excerpt: text } : {}) });
const difference = { description: 'Spoken offer in opening', evidence_type: 'transcript', higher_group_support: 3, lower_group_support: 1,
  higher_group_size: 3, lower_group_size: 3, supporting_video_refs: refs.slice(0, 3), confidence: 'bounded',
  evidence_refs: [cited('A', 'transcript', .8, 'Offer spoken here'), cited('B', 'transcript', 1.1, 'Today only'), cited('C', 'transcript', .7, 'Save now')],
  counterexamples: [cited('D', 'transcript', 1.2, 'Same offer')] };
const hypothesis = { hypothesis: 'Test a spoken opening offer', variable_to_test: 'spoken offer timing', control_condition: 'Offer after setup',
  variant_condition: 'Same offer in opening', primary_metric: 'ctr', what_to_hold_constant: ['visual format', 'duration'],
  limitations: ['Association within this cohort.'], source_difference: difference.description, counterevidence: difference.counterexamples };
const base = { metric: { description: 'Click-through rate', unit: 'percent' },
  cohort: { date_start: '2026-01-01', date_stop: '2026-01-07', distinct_ads: 6, peer_count: 5, content_groups: groups },
  performance: { summary: 'CTR was above the peer median.', metric_facts: { target_value: '1.8', median: '1', ratio: '1.8', percentile: 80, description: 'click-through rate' }, limitations: [] },
  content_differences: [difference], hypotheses: [hypothesis], creative_previews: [], abstentions: [] };

before(async () => { server = await createServer({ resolve: { alias: authAlias }, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  await server.listen(); origin = server.resolvedUrls.local[0]; browser = await chromium.launch(); });
after(async () => { await browser?.close(); await server?.close(); });

async function app(response = base, { linked = true, hold = false, status = 200, width = 1440 } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 } }); const calls = [], errors = [];
  await context.addInitScript(id => localStorage.setItem('video-analyzer.active-company-id', id), company);
  let release; const gate = new Promise(resolve => { release = resolve; });
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/intelligence')) { calls.push({ body: route.request().postDataJSON(), cache: route.request().headers()['cache-control'] });
      if (hold) await gate; return route.fulfill({ status, json: status === 200 ? response : { detail: 'SECRET INTERNAL PROVIDER TEXT' } }).catch(() => {}); }
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
async function submit(page) { await page.getByLabel('Start date').fill('2026-01-01'); await page.getByLabel('End date').fill('2026-01-07');
  await page.getByRole('button', { name: 'Run analysis' }).click(); }

 test('full desktop and mobile result connects six creatives, signal, evidence and one experiment', async () => {
  const f = await app(); try { await submit(f.page); await f.page.getByRole('heading', { name: 'Creative Signal Map' }).waitFor();
    assert.deepEqual(f.calls.map(item => item.body), [{ account_id: account, metric_id: 'ctr', date_start: '2026-01-01', date_stop: '2026-01-07' }]);
    assert.equal(await f.page.locator('.ci-creative').count(), 6);
    assert.equal(await f.page.locator('.ci-distribution-dot').count(), 6);
    assert.equal(await f.page.locator('.ci-map-row').count(), 1);
    assert.equal(await f.page.locator('.ci-experiment').count(), 1);
    assert.equal(await f.page.getByText('1.8×').count(), 1);
    await f.page.locator('.ci-signal-name').click();
    assert.equal(await f.page.locator('.ci-creative.support').count(), 3);
    assert.equal(await f.page.locator('.ci-creative.counterexample').count(), 1);
    assert.equal(await f.page.locator('.ci-creative.dim').count(), 2);
    await f.page.locator('.ci-inspect').click();
    await f.page.getByRole('dialog').getByText('Offer spoken here').waitFor();
    await f.page.getByRole('dialog').getByRole('button', { name: /Creative D/ }).click();
    assert.equal(await f.page.getByRole('dialog').getByText('◆ Counterexample', { exact: false }).count(), 1);
    await f.page.screenshot({ path: '/private/tmp/v9-stage82-evidence-desktop.png' });
    await f.page.getByRole('button', { name: 'Close evidence' }).click();
    await f.page.locator('.ci-signal-name').focus(); await f.page.keyboard.press('Enter');
    await f.page.locator('.ci-creative').nth(1).getByRole('button', { name: 'Focus in Signal Map' }).click();
    assert.equal(await f.page.locator('.ci-map-row.is-creative-match').count(), 1);
    await f.page.evaluate(() => window.scrollTo(0, 0));
    await f.page.screenshot({ path: '/private/tmp/v9-stage82-intelligence-desktop.png', fullPage: true });
    await f.page.setViewportSize({ width: 390, height: 844 });
    await f.page.evaluate(() => window.scrollTo(0, 0));
    await f.page.screenshot({ path: '/private/tmp/v9-stage82-intelligence-mobile.png', fullPage: true });
    await f.page.locator('.ci-inspect').click();
    await f.page.getByRole('dialog').getByText('Offer spoken here').waitFor();
    assert.equal(await f.page.getByRole('dialog').evaluate(element => element.scrollWidth <= element.clientWidth), true);
    await f.page.screenshot({ path: '/private/tmp/v9-stage82-evidence-mobile.png' });
    assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
      JSON.stringify(await f.page.evaluate(() => [...document.querySelectorAll('body *')].filter(element => element.getBoundingClientRect().right > innerWidth + 1).slice(0, 12).map(element => [element.className?.baseVal ?? element.className, Math.round(element.getBoundingClientRect().right)]))));
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});

test('three experiments stay compact and source link reselects signal', async () => {
  const f = await app({ ...base, hypotheses: [0, 1, 2].map(i => ({ ...hypothesis, hypothesis: `Test opening offer ${i}` })) });
  try { await submit(f.page); await f.page.getByRole('heading', { name: 'Experiments to try' }).waitFor();
    assert.equal(await f.page.locator('.ci-experiment').count(), 3);
    await f.page.locator('.ci-experiment-head button').first().click();
    assert.equal(await f.page.locator('.ci-map-row.is-selected').count(), 1);
  } finally { await f.close(); }
});

test('exact sampled frame and text at the same moment form one evidence trace', async () => {
  const frame = cited('A', 'frame', .8);
  const preview = { video_ref: 'video_A', frame_ref: frame.evidence_ref, timestamp_seconds: .8,
    jpeg_base64: readFileSync(new URL('./fixtures/intelligence-preview.jpg', import.meta.url)).toString('base64') };
  const f = await app({ ...base, creative_previews: [preview], content_differences: [{ ...difference,
    evidence_refs: [frame, ...difference.evidence_refs] }] });
  try { await submit(f.page); await f.page.locator('.ci-inspect').click();
    assert.equal(await f.page.getByRole('dialog').getByAltText('Bounded sampled frame for this exact citation').count(), 1);
    assert.equal(await f.page.getByRole('dialog').getByText('Offer spoken here').count(), 1);
    assert.equal(await f.page.getByRole('dialog').getByText('CITED MOMENT · 2 SOURCES').count(), 1);
  } finally { await f.close(); }
});

test('performance-only and media failure preserve performance without signal map', async () => {
  for (const abstention of ['insufficient_source_video_coverage', 'source_media_unavailable', 'content_model_or_validation_failed']) {
    const f = await app({ ...base, content_differences: [], hypotheses: [], abstentions: [abstention] });
    try { await submit(f.page); await f.page.getByRole('heading', { name: 'Creative comparison unavailable' }).waitFor();
      assert.equal(await f.page.locator('.ci-performance').count(), 1);
      assert.equal(await f.page.locator('.ci-map').count(), 0);
      assert.equal(await f.page.locator('.ci-experiment').count(), 0);
    } finally { await f.close(); }
  }
});

test('validated findings survive hypothesis failure', async () => {
  const f = await app({ ...base, hypotheses: [], abstentions: ['hypothesis_model_or_validation_failed'] });
  try { await submit(f.page); await f.page.getByRole('heading', { name: 'Creative Signal Map' }).waitFor();
    assert.equal(await f.page.locator('.ci-map-row').count(), 1);
    assert.equal(await f.page.locator('.ci-experiment').count(), 0);
  } finally { await f.close(); }
});

test('insufficient cohort and disconnected Meta give one recovery route', async () => {
  for (const abstention of ['insufficient_historical_cohort', 'meta_disconnected']) {
    const f = await app({ ...base, performance: null, content_differences: [], hypotheses: [], abstentions: [abstention] });
    try { await submit(f.page); await f.page.getByRole('heading', { name: 'No comparison available yet' }).waitFor();
      assert.equal(await f.page.locator('.ci-performance').count(), 0);
      assert.equal(await f.page.locator('.ci-partial a').count(), 1);
    } finally { await f.close(); }
  }
});

test('no linked Ads account hides unusable controls', async () => {
  const f = await app(base, { linked: false }); try { await f.page.getByRole('heading', { name: 'Link a Meta Ads account' }).waitFor();
    assert.equal(await f.page.locator('.ci-toolbar').count(), 0); assert.equal(f.calls.length, 0);
  } finally { await f.close(); }
});

test('loading disables controls and prevents duplicate requests', async () => {
  const f = await app(base, { hold: true }); try { await submit(f.page); await f.page.getByText('Comparing performance and creative evidence…').waitFor();
    await f.page.locator('.ci-toolbar').evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
    assert.equal(await f.page.getByRole('button', { name: 'Run analysis' }).isDisabled(), true);
    assert.equal(f.calls.length, 1); f.release(); await f.page.locator('.ci-performance').waitFor(); assert.equal(f.calls.length, 1);
  } finally { f.release(); await f.close(); }
});

test('API errors and malformed responses hide internal data', async () => {
  for (const setting of [{ status: 401 }, { status: 422 }, { status: 503 }, { response: { detail: 'SECRET INTERNAL PROVIDER TEXT' } }]) {
    const f = await app(setting.response ?? base, { status: setting.status ?? 200 });
    try { await submit(f.page); await f.page.getByRole('alert').waitFor();
      assert.equal((await f.page.locator('body').innerText()).includes('SECRET INTERNAL PROVIDER TEXT'), false);
    } finally { await f.close(); }
  }
});
test('long observations and recommendations fit a narrow mobile result without inventing media', async () => {
  const longDescription = 'Spoken opening offer with a detailed product explanation and an unusually long campaign message';
  const f = await app({ ...base, content_differences: [{ ...difference, description: longDescription }],
    hypotheses: [{ ...hypothesis, source_difference: longDescription, hypothesis: 'Test whether a concise spoken offer helps viewers understand the product before a much longer explanation begins in this creative.' }] }, { width: 320 });
  try { await submit(f.page); await f.page.locator('.ci-signal-name strong').getByText(longDescription, { exact: true }).waitFor();
    assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await f.page.locator('.ci-inspect').click(); await f.page.getByRole('dialog').getByText('Frame preview unavailable for this citation').waitFor();
    assert.equal(await f.page.getByRole('dialog').evaluate(element => element.scrollWidth <= element.clientWidth), true);
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});
