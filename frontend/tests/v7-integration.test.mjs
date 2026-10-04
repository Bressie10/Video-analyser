import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';

const origin = 'http://127.0.0.1:5289';
async function wait(url, child) {
  for (let i = 0; i < 300; i++) {
    if (child.exitCode !== null) throw Error(`Server exited ${child.exitCode}`);
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw Error(`Server unavailable: ${url}`);
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Server did not stop')), 20000);
    child.once('exit', () => { clearTimeout(timer); resolve(); });
    child.kill('SIGTERM');
  });
}

test('new user browser activation reaches 100% through real FastAPI and PostgreSQL', { timeout: 150000 }, async () => {
  assert.ok(process.env.TEST_DATABASE_URL, 'TEST_DATABASE_URL must point to disposable PostgreSQL');
  const directory = await mkdtemp(join(tmpdir(), 'v7-browser-'));
  let backend, vite, browser, context;
  try {
    backend = spawn('.venv/bin/python', ['tests/v7_browser_server.py'], {
      cwd: '../backend', env: { ...process.env, V7_E2E_DIRECTORY: directory }, stdio: 'inherit',
    });
    await wait('http://127.0.0.1:8165/health', backend);
    vite = spawn('./node_modules/.bin/vite', ['--config', 'tests/v7-integration.vite.mjs'], { stdio: 'inherit' });
    await wait(origin, vite);
    const session = JSON.parse(await readFile(join(directory, 'session.json'), 'utf8'));
    browser = await chromium.launch();
    context = await browser.newContext();
    await context.addInitScript(jwt => { window.__authMock = { session: { access_token: jwt,
      user: { id: '11111111-1111-4111-8111-111111111111', email: 'a@example.com' } } }; }, session.user_a);
    await context.route('https://www.facebook.com/**', route => {
      const state = new URL(route.request().url()).searchParams.get('state');
      return route.fulfill({ status: 302, headers: { location: `${origin}/api/meta/callback?state=${encodeURIComponent(state)}&code=fixture` }, body: '' });
    });
    const page = await context.newPage(); page.setDefaultTimeout(12000);
    const errors = [], calls = [], forbidden = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (['error', 'warning'].includes(message.type()) && message.text() !== 'Failed to load resource: the server responded with a status of 402 (Payment Required)') errors.push(message.text()); });
    page.on('request', request => { if (request.url().includes('/api/')) calls.push({ path: new URL(request.url()).pathname,
      method: request.method(), authorization: request.headers().authorization }); });
    page.on('response', response => { if (response.status() === 403) forbidden.push(new URL(response.url()).pathname); });
    const state = async (token = session.user_a) => {
      const response = await context.request.get(`${origin}/api/me/onboarding`, { headers: { Authorization: `Bearer ${token}` } });
      assert.equal(response.status(), 200, await response.text()); return response.json();
    };
    const fixture = async path => {
      const response = await context.request.post(`${origin}/__v7_fixture/${path}`);
      assert.equal(response.status(), 200, await response.text()); return response.json();
    };
    const nav = async name => page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name, exact: true }).click();
    await page.goto(origin);
    await page.getByRole('heading', { name: 'Welcome to ContentMetric' }).waitFor();
    assert.equal((await state()).progress, 0);
    await page.getByRole('button', { name: 'Start setup' }).click();
    await page.getByRole('button', { name: 'Create workspace' }).click();
    await page.getByLabel('New company name').fill('V7 workspace');
    await page.getByRole('button', { name: 'Create company' }).click();
    await page.waitForFunction(() => document.body.textContent.includes('20% complete'));
    assert.equal((await state()).progress, 20);
    const companyId = await page.evaluate(() => localStorage.getItem('video-analyzer.active-company-id'));
    const billingPath = `/api/companies/${companyId}/billing`;
    const freeBilling = await context.request.get(origin + billingPath, { headers: { Authorization: `Bearer ${session.user_a}` } });
    assert.equal(freeBilling.status(), 200, await freeBilling.text());
    assert.equal((await freeBilling.json()).effective_plan, 'free');
    const secondWorkspace = await page.evaluate(async jwt => {
      const response = await fetch('/api/companies', { method: 'POST', headers: { Authorization: `Bearer ${jwt}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Second Free workspace' }) });
      return { status: response.status, body: await response.json() };
    }, session.user_a);
    assert.equal(secondWorkspace.status, 402);
    assert.equal(secondWorkspace.body.detail.code, 'free_workspace_limit_reached');

    const popup = context.waitForEvent('page');
    await page.getByRole('button', { name: 'Connect Meta' }).click();
    await popup;
    await page.waitForFunction(() => document.body.textContent.includes('40% complete'));
    assert.equal((await state()).progress, 40);
    assert.ok(calls.some(call => call.path === '/api/meta/connect' && call.authorization === `Bearer ${session.user_a}`));

    const seeded = await fixture('content');
    await nav('Settings');
    const [link] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes('/accounts/')),
      page.getByRole('checkbox', { name: 'V7 Instagram' }).click(),
    ]);
    assert.equal(link.status(), 200, await link.text());
    await page.getByRole('checkbox', { name: 'V7 Instagram' }).waitFor({ state: 'visible' });
    await page.waitForFunction(() => !document.body.textContent.includes('Saving company changes…'));
    assert.equal((await state()).progress, 60);
    await nav('Content');
    await page.getByRole('button', { name: 'Analyze', exact: true }).click();
    await page.getByText('Processing', { exact: true }).waitFor();
    assert.ok(calls.some(call => call.path.endsWith('/content/analyze') && call.method === 'POST'));
    await fixture('complete-analysis');
    await page.getByRole('button', { name: 'Refresh analysis status' }).click();
    await page.getByText('Analysed', { exact: true }).waitFor();
    assert.equal((await state()).progress, 80);
    await nav('Generate');
    await page.getByRole('button', { name: 'Generate idea', exact: true }).click();
    await page.getByRole('heading', { name: 'One idea' }).waitFor();
    assert.equal((await state()).progress, 100);
    const usedBilling = await context.request.get(origin + billingPath, { headers: { Authorization: `Bearer ${session.user_a}` } });
    assert.equal(usedBilling.status(), 200, await usedBilling.text());
    assert.deepEqual((await usedBilling.json()).usage, { analyses: 1, idea_generations: 1 });
    assert.equal((await context.request.get(origin + billingPath, { headers: { Authorization: `Bearer ${session.user_b}` } })).status(), 403);
    await nav('Overview');
    await page.getByRole('heading', { name: "You're ready to go" }).waitFor();
    await page.getByRole('button', { name: 'Go to Overview' }).click();
    assert.equal(await page.getByRole('heading', { name: 'Finish setting up ContentMetric' }).count(), 0);
    assert.ok(seeded.item_id);

    await page.evaluate(jwt => window.__changeAuth({ access_token: jwt,
      user: { id: '22222222-2222-4222-8222-222222222222', email: 'b@example.com' } }), session.user_b);
    await page.getByText('b@example.com').waitFor();
    assert.equal((await state(session.user_b)).progress, 0);
    assert.doesNotMatch(await page.locator('body').innerText(), /V7 workspace|One idea|100% complete/);
    await page.evaluate(jwt => window.__changeAuth({ access_token: jwt,
      user: { id: '11111111-1111-4111-8111-111111111111', email: 'a@example.com' } }), session.user_a);
    await page.getByText('a@example.com').waitFor();
    assert.equal((await state()).progress, 100);
    await fixture('disconnect');
    await page.reload();
    await page.getByRole('progressbar').waitFor();
    const regressed = await state();
    assert.equal(regressed.progress, 80);
    assert.equal(regressed.next_step, 'meta');
    assert.deepEqual(regressed.steps, { workspace: true, meta: false, account: true, analysis: true, idea: true });
    assert.deepEqual(forbidden, ['/api/meta/test']); // User B cannot use User A's provider cookie.
    assert.deepEqual(errors.filter(error => !error.startsWith('Failed to load resource: the server responded with a status of 403')), []);
  } finally {
    await context?.close(); await browser?.close(); await stop(vite); await stop(backend);
    await rm(directory, { recursive: true, force: true });
  }
});
