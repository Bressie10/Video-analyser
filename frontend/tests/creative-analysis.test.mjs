import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { authAlias } from './authenticated.vite.mjs';

const company = '00000000-0000-4000-8000-000000000001';
const account = '00000000-0000-4000-8000-000000000002';
const ref = '00000000-0000-4000-8000-000000000003';
let server, browser, origin, media;
const detail = { creative_ref: ref, label: 'Offer video', duration_seconds: 4,
  resolution: { width: 320, height: 180 }, media: { state: 'resolution_required' },
  scenes: [{ scene_number: 1, start_seconds: 0, end_seconds: 2 }, { scene_number: 2, start_seconds: 2, end_seconds: 4 }],
  ocr: [{ appearance_seconds: .4, disappearance_seconds: 1.2, text: 'Limited offer' }],
  transcript: [{ start_seconds: .2, end_seconds: 1.1, text: 'Today only' }] };
const citation = { video_ref: 'video_A', evidence_ref: 'video_A:transcript:0', evidence_type: 'transcript', timestamp_seconds: .8, excerpt: 'Today only' };
const groups = { higher: [2.1, 1.9, 1.8].map((value, i) => ({ video_ref: `video_${'ABC'[i]}`, creative_ref: i === 0 ? ref : `00000000-0000-4000-8000-00000000000${i + 3}`, metric_value: String(value), percentile: null })),
  lower: [1, .8, .6].map((value, i) => ({ video_ref: `video_${'DEF'[i]}`, creative_ref: `00000000-0000-4000-8000-00000000000${i + 6}`, metric_value: String(value), percentile: null })), middle_excluded_count: 0 };
const comparison = { metric: { description: 'Click-through rate' }, cohort: { date_start: '2026-01-01', date_stop: '2026-01-07', peer_count: 5, currency: 'EUR', content_groups: groups },
  performance: { summary: 'Observed CTR difference.', metric_facts: { target_value: '2.1', median: '1', ratio: '2.1', percentile: 90, description: 'CTR' }, limitations: [] },
  content_differences: [{ description: 'Spoken offer', evidence_type: 'transcript', higher_group_support: 1, lower_group_support: 0,
    higher_group_size: 3, lower_group_size: 3, supporting_video_refs: ['video_A'], confidence: 'bounded', evidence_refs: [citation], counterexamples: [] }],
  hypotheses: [], creative_previews: [], abstentions: [] };

before(async () => {
  const path = join(tmpdir(), 'v9-stage83-browser-fixture.mp4');
  execFileSync('ffmpeg', ['-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=teal:s=320x180:r=10:d=4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', path]);
  media = readFileSync(path);
  server = await createServer({ resolve: { alias: authAlias }, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  await server.listen(); origin = server.resolvedUrls.local[0]; browser = await chromium.launch();
});
after(async () => { await browser?.close(); await server?.close(); });

async function app({ width = 1440, data = detail, fromComparison = false, grantStatus = 200 } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const calls = { intelligence: 0, media: 0 }; const errors = [];
  await context.addInitScript(id => localStorage.setItem('video-analyzer.active-company-id', id), company);
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/intelligence')) { calls.intelligence++; return route.fulfill({ json: comparison }); }
    if (path.endsWith('/analysis')) return route.fulfill({ json: data });
    if (path.endsWith('/media-access')) return route.fulfill({ status: grantStatus, json: grantStatus === 200 ? { ready: true } : { detail: 'SECRET PROVIDER FAILURE' } });
    if (path.endsWith('/media')) { calls.media++;
      const requested = /^bytes=(\d+)-(\d*)$/.exec(route.request().headers().range ?? '');
      const start = requested ? Number(requested[1]) : 0;
      const end = requested && requested[2] ? Math.min(Number(requested[2]), media.length - 1) : media.length - 1;
      return route.fulfill({ status: requested ? 206 : 200, headers: { 'content-type': 'video/mp4', 'accept-ranges': 'bytes',
        'content-length': String(end - start + 1), ...(requested ? { 'content-range': `bytes ${start}-${end}/${media.length}` } : {}) }, body: media.subarray(start, end + 1) }); }
    if (path === '/api/companies') return route.fulfill({ json: { companies: [{ company_id: company, name: 'Alpha', role: 'owner', archived: false,
      accounts: [{ account_id: account, display_name: 'Owned Ads', platform: 'meta_ads' }] }] } });
    if (path === '/api/meta/test') return route.fulfill({ json: { connected: false } });
    if (path === '/api/me/companies') return route.fulfill({ json: { companies: [{ id: company, archived_at: null }] } });
    return route.fulfill({ json: { items: [], next_offset: null, accounts: [] } });
  });
  const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${origin}#${fromComparison ? 'intelligence' : `creative/${ref}`}`);
  return { page, calls, errors, close: () => context.close() };
}

test('stored evidence, keyboard seeking, synchronization and no-signal lane', async () => {
  const f = await app(); try {
    await f.page.getByRole('heading', { name: 'Offer video' }).waitFor();
    assert.equal(await f.page.locator('.ca-lane').count(), 4);
    assert.equal(await f.page.getByText('No validated signals for this view').count(), 1);
    await f.page.waitForFunction(() => document.querySelector('video')?.readyState >= 1);
    const text = f.page.getByRole('button', { name: /TEXT Limited offer at/ });
    await text.focus(); await f.page.keyboard.press('Enter');
    await f.page.getByText('00:00.4', { exact: true }).first().waitFor();
    assert.equal(await f.page.locator('video').evaluate(video => Math.abs(video.currentTime - .4) < .2), true,
      JSON.stringify(await f.page.locator('video').evaluate(video => ({ time: video.currentTime, duration: video.duration, ready: video.readyState, error: video.error?.message }))));
    await f.page.locator('video').evaluate(video => { video.currentTime = 2.3; video.dispatchEvent(new Event('timeupdate')); });
    await f.page.getByRole('button', { name: /SCENES Scene 2 at/ }).focus(); await f.page.keyboard.press('Space');
    await f.page.getByRole('button', { name: 'Pin this moment' }).waitFor();
    assert.equal(await f.page.locator('.ca-lane .ca-event').count(), 4);
    assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
      JSON.stringify(await f.page.evaluate(() => ['.app-main', '.ca-page', '.ca-main-grid', '.ca-timeline'].map(sel => { const r = document.querySelector(sel)?.getBoundingClientRect(); return [sel, r?.left, r?.width, r?.right]; }))));
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});

test('comparison citation opens exact moment and return preserves result without another request', async () => {
  const f = await app({ fromComparison: true }); try {
    await f.page.getByLabel('Start date').fill('2026-01-01'); await f.page.getByLabel('End date').fill('2026-01-07');
    await f.page.getByRole('button', { name: 'Run analysis' }).click();
    await f.page.getByRole('heading', { name: 'Creative Signal Map' }).waitFor();
    await f.page.locator('.ci-signal-name').click();
    await f.page.getByRole('button', { name: 'Open Creative A analysis' }).click();
    await f.page.getByText(/From comparison · Spoken offer · CTR · higher numeric group · 00:00.8/).waitFor();
    assert.equal(await f.page.locator('.ca-signal').count(), 1);
    await f.page.getByRole('link', { name: /Back to Creative Intelligence/ }).click();
    await f.page.getByRole('heading', { name: 'Creative Signal Map' }).waitFor();
    assert.equal(f.calls.intelligence, 1);
    assert.equal(await f.page.locator('.ci-map-row.is-selected').count(), 1);
  } finally { await f.close(); }
});

test('mobile evidence sheet and unavailable media retain timeline', async () => {
  const f = await app({ width: 390, data: { ...detail, media: { state: 'unavailable' }, transcript: [], ocr: [] } }); try {
    await f.page.getByText('Video currently unavailable').waitFor();
    assert.equal(await f.page.locator('.ca-lane').count(), 4);
    await f.page.getByRole('button', { name: /SCENES Scene 2 at/ }).click();
    await f.page.getByRole('dialog', { name: 'Focused evidence' }).waitFor();
    await f.page.getByRole('button', { name: 'Close focused evidence' }).click();
    assert.equal(await f.page.getByRole('dialog', { name: 'Focused evidence' }).count(), 0);
    assert.equal(await f.page.getByText('Transcript unavailable.').isVisible(), false);
    await f.page.getByText(/Full transcript/).click();
    await f.page.getByText('Transcript unavailable.').waitFor();
    assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
      JSON.stringify(await f.page.evaluate(() => ['.app-main', '.ca-page', '.ca-main-grid', '.ca-timeline'].map(sel => { const r = document.querySelector(sel)?.getBoundingClientRect(); return [sel, r?.left, r?.width, r?.right]; }))));
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});

test('media access failure leaves stored evidence visible without leaking provider text', async () => {
  const f = await app({ grantStatus: 503 }); try {
    await f.page.getByText('Video currently unavailable').waitFor();
    assert.equal(await f.page.getByRole('button', { name: /TEXT Limited offer at/ }).count(), 1);
    assert.equal((await f.page.locator('body').innerText()).includes('SECRET PROVIDER FAILURE'), false);
    assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});

test('unknown stored duration shows timed events without a fabricated full clip scale', async () => {
  const f = await app({ data: { ...detail, duration_seconds: null, media: { state: 'unavailable' } } }); try {
    await f.page.getByText('Duration unavailable · timed event list').waitFor();
    assert.equal(await f.page.locator('.ca-lane-track.is-unscaled').count(), 4);
    assert.equal(await f.page.locator('.ca-playhead').count(), 0);
    await f.page.getByRole('button', { name: /SPEECH Today only at/ }).click();
    await f.page.getByRole('button', { name: 'Pin this moment' }).waitFor();
  } finally { await f.close(); }
});
