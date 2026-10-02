import { authAlias } from './authenticated.vite.mjs';
import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { mkdir, readFile } from 'node:fs/promises';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const KEY = 'video-analyzer.active-company-id';
const A = '00000000-0000-4000-8000-000000000001';
const B = '00000000-0000-4000-8000-000000000002';
const pages = ['Overview', 'Content', 'Generate', 'Ideas', 'Settings'];
let server, browser, origin;
before(async () => {
  server = await createServer({ resolve: { alias: authAlias }, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  await server.listen(); origin = server.resolvedUrls.local[0]; browser = await chromium.launch();
  if (process.env.V5_SCREENSHOT_DIR) await mkdir(process.env.V5_SCREENSHOT_DIR, { recursive: true });
});
after(async () => { await browser?.close(); await server?.close(); });
async function fixture({ selected = A, width = 1440, archived = false, inaccessible = false, fail = false, companyName = 'Northline Studio', sources = false } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  if (selected) await context.addInitScript(({ KEY, selected }) => localStorage.setItem(KEY, selected), { KEY, selected });
  const calls = [], errors = [];
  await context.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname; calls.push(path);
    if (new URL(route.request().url()).pathname === '/api/me/companies') return route.fulfill({ json: { companies: [A, B].map(value => ({ id: typeof value === 'string' ? value : value.id, archived_at: null })) } });
    if (path === '/api/companies') return route.fulfill({ status: fail ? 503 : 200, json: { companies: [
      ...(!inaccessible ? [{ company_id: A, name: companyName, archived, accounts: [{ account_id: B, platform: 'instagram', display_name: 'Northline Instagram' }] }] : []),
      { company_id: B, name: 'Beta', role: "owner", archived: false, accounts: [] },
    ] } });
    if (path.endsWith('/content')) return route.fulfill({ json: { items: sources && new URL(route.request().url()).searchParams.get('analyzed_only') === 'true' ? [{ library_item_id: B, display_title: 'Northline source', platform: 'instagram', published_at: null, analyzed: true }] : [], next_offset: null } });
    if (path.endsWith('/ideas')) return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: { connected: false, accounts: [] } });
  });
  const page = await context.newPage(); page.setDefaultTimeout(5000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (['error', 'warning'].includes(message.type()) && !fail) errors.push(message.text()); });
  await page.goto(origin);
  await page.getByRole('heading', { name: 'Overview', exact: true }).waitFor();
  await page.getByRole('navigation', { name: 'Company', exact: true }).getByRole('button').first().waitFor({ state: 'visible' });
  await page.waitForFunction(() => !document.querySelector('.company-navigation > button').disabled);
  return { page, calls, close: async () => { await context.close(); assert.deepEqual(errors, []); } };
}
const primary = p => p.getByRole('navigation', { name: 'Primary', exact: true });
const company = p => p.getByRole('navigation', { name: 'Company', exact: true });
async function destination(p, name, width = 1440) {
  if (width <= 700 && !await primary(p).isVisible()) await p.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await primary(p).getByRole('link', { name, exact: true }).click();
  await p.getByRole('heading', { level: 1, name, exact: true }).waitFor();
}
async function screenshot(page, name) {
  if (process.env.V5_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.V5_SCREENSHOT_DIR}/${name}.png`, fullPage: true });
}

test('shell destinations, active link, refresh, history and persistent global context', async () => {
  const f = await fixture(); const p = f.page;
  try {
    assert.equal(await p.title(), 'ContentMetric');
    assert.equal(await p.getByRole('main').count(), 1);
    assert.equal(await p.locator('.app-header .company-navigation').count(), 1);
    for (const name of pages) {
      assert.equal(await primary(p).getByRole('link', { name, exact: true }).getAttribute('href'), `#${name.toLowerCase()}`);
      await destination(p, name);
      assert.equal(await primary(p).locator('[aria-current=page]').innerText(), name);
      assert.equal(await primary(p).locator('[aria-current=page]').count(), 1);
      assert.equal(await company(p).getByRole('button').first().innerText(), 'Northline Studio');
    }
    await p.reload(); await p.getByRole('heading', { level: 1, name: 'Settings', exact: true }).waitFor();
    await p.goBack(); await p.getByRole('heading', { level: 1, name: 'Ideas', exact: true }).waitFor();
    assert.equal(await p.getByText('Meta is not connected.', { exact: true }).isVisible(), false);
    assert.equal(f.calls.filter(path => path === '/api/meta/test').length, 2); // initial mount + reload only
    assert.equal(await p.locator('vite-error-overlay').count(), 0);
  } finally { await f.close(); }
});

test('company disclosure supports keyboard, Escape, active state and UUID-only persistence', async () => {
  const f = await fixture(); const p = f.page;
  try {
    const trigger = company(p).getByRole('button').first();
    await trigger.focus(); await p.keyboard.press('Enter');
    assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
    assert.ok(await trigger.getAttribute('aria-controls'));
    await p.keyboard.press('Tab');
    assert.match(await p.evaluate(() => document.activeElement.textContent), /Northline Studio.*Active/);
    assert.equal(await p.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), 'solid');
    await screenshot(p, 'company-keyboard-focus');
    await p.keyboard.press('Escape');
    assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true);
    await trigger.click(); await company(p).getByRole('button', { name: 'Beta', exact: true }).click();
    await company(p).getByRole('button', { name: 'Beta', exact: true }).waitFor();
    assert.equal(await p.evaluate(KEY => localStorage.getItem(KEY), KEY), B);
    assert.equal((await p.locator('main').innerText()).includes('Northline Studio'), false);
  } finally { await f.close(); }
});

for (const state of ['empty', 'invalid', 'archived', 'inaccessible']) test(`${state} company selection clears without fallback and keeps navigation usable`, async () => {
  const f = await fixture({ selected: state === 'empty' ? null : state === 'invalid' ? 'provider-id' : A, archived: state === 'archived', inaccessible: state === 'inaccessible' });
  try {
    await f.page.getByRole('heading', { name: 'No company selected', exact: true }).waitFor();
    assert.equal(await f.page.evaluate(KEY => localStorage.getItem(KEY), KEY), null);
    assert.equal(await company(f.page).getByRole('button').first().innerText(), 'Select company');
    if (state === 'empty') await screenshot(f.page, 'empty-1440');
    await destination(f.page, 'Content');
    await f.page.getByRole('heading', { name: 'No company selected', exact: true }).waitFor();
    await f.page.getByRole('button', { name: 'Manage companies', exact: true }).click();
    await f.page.getByRole('heading', { level: 1, name: 'Settings', exact: true }).waitFor();
    await f.page.getByLabel('New company name').waitFor();
  } finally { await f.close(); }
});

test('company load failure leaves Settings and retry accessible', async () => {
  const f = await fixture({ fail: true });
  try {
    await f.page.getByRole('button', { name: 'Retry companies', exact: true }).waitFor();
    await destination(f.page, 'Settings');
    await f.page.getByRole('button', { name: 'Connect Meta', exact: true }).waitFor();
  } finally { await f.close(); }
});

test('workflow draft survives navigation to another page', async () => {
  const f = await fixture({ sources: true }); const p = f.page;
  try {
    await destination(p, 'Generate');
    await p.getByLabel('Brief (optional)').fill('Keep this draft across navigation');
    await destination(p, 'Content'); await destination(p, 'Generate');
    assert.equal(await p.getByLabel('Brief (optional)').inputValue(), 'Keep this draft across navigation');
  } finally { await f.close(); }
});

test('integrated navigation preserves filters, sources and unsaved idea edits until a confirmed company switch', async () => {
  const f = await fixture(); const p = f.page;
  const saved = { id: B, company_id: A, title: 'Studio story', concept: 'Show the process', script: 'Open with the finished work.', status: 'draft', feedback: 'none', target_platforms: ['instagram'], created_at: '2026-09-20T12:00:00Z', updated_at: '2026-09-20T12:00:00Z', publications: [] };
  try {
    await p.route('**/api/companies/*/content?**', route => route.fulfill({ json: { items: [{ library_item_id: B, display_title: 'Studio source', platform: 'instagram', content_type: 'reel', published_at: null, analyzed: true }], next_offset: null } }));
    await p.route('**/api/meta/companies/*/ideas?**', route => route.fulfill({ json: { items: route.request().url().includes(A) ? [saved] : [], next_cursor: null } }));
    await p.route(`**/api/meta/companies/${A}/ideas/${B}`, route => route.fulfill({ json: saved }));
    await p.reload();
    await destination(p, 'Content');
    await p.getByLabel('Content platform', { exact: true }).selectOption('instagram');
    await destination(p, 'Generate');
    await p.getByLabel('Choose manually').check();
    await p.getByRole('checkbox', { name: /^Studio source / }).check();
    await p.getByLabel('Brief (optional)').fill('Keep the creative direction');
    await destination(p, 'Ideas');
    await p.getByRole('button', { name: saved.title, exact: true }).click();
    await p.getByRole('button', { name: 'Edit', exact: true }).click();
    await p.getByLabel('Title', { exact: true }).fill('Unsaved studio story');
    await destination(p, 'Settings'); await destination(p, 'Overview');
    await destination(p, 'Content');
    assert.equal(await p.getByLabel('Content platform', { exact: true }).inputValue(), 'instagram');
    await destination(p, 'Generate');
    assert.equal(await p.getByRole('checkbox', { name: /^Studio source / }).isChecked(), true);
    assert.equal(await p.getByLabel('Brief (optional)').inputValue(), 'Keep the creative direction');
    // The hidden Ideas editor must still register its switch guard.
    await company(p).getByRole('button').first().click();
    await company(p).getByRole('button', { name: 'Beta', exact: true }).click();
    await p.getByRole('dialog', { name: 'Switch company?' }).getByText('You have unsaved edits. Switching may discard those edits.').waitFor();
    await p.getByRole('button', { name: 'Stay here', exact: true }).click();
    await destination(p, 'Ideas');
    assert.equal(await p.getByLabel('Title', { exact: true }).inputValue(), 'Unsaved studio story');
    await company(p).getByRole('button').first().click();
    await company(p).getByRole('button', { name: 'Beta', exact: true }).click();
    await p.getByRole('button', { name: 'Continue and switch', exact: true }).click();
    await p.getByRole('heading', { name: 'Your ideas will appear here', exact: true }).waitFor();
    assert.equal(await p.getByLabel('Title', { exact: true }).count(), 0);
    await destination(p, 'Content');
    assert.equal(await p.getByLabel('Content platform', { exact: true }).inputValue(), '');
    await destination(p, 'Generate');
    assert.equal(await p.getByLabel('Brief (optional)').inputValue(), '');
    assert.equal(await p.getByLabel('Latest analysed content', { exact: true }).isChecked(), true);
    await p.getByLabel('Choose manually').check();
    assert.equal(await p.locator('.generation-sources input:checked').count(), 0);
  } finally { await f.close(); }
});


test('in-progress generation guard survives navigation and confirmed switch clears the result', async () => {
  const f = await fixture(); const p = f.page;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  try {
    await p.route('**/api/companies/*/content?**', route => route.fulfill({ json: { items: [{ library_item_id: B, display_title: 'Analyzed source', platform: 'instagram', published_at: null, analyzed: true }], next_offset: null } }));
    await p.route('**/recommendations', async route => { await gate; await route.fulfill({ json: { id: B, company_id: A, title: 'Late idea', concept: 'Concept', script: 'Script', target_platforms: ['instagram'] } }).catch(() => {}); });
    await p.reload(); await destination(p, 'Generate');
    await p.getByRole('button', { name: 'Generate idea', exact: true }).click();
    await p.getByText('Generating and saving', { exact: false }).waitFor();
    await destination(p, 'Content');
    await company(p).getByRole('button').first().click(); await company(p).getByRole('button', { name: 'Beta', exact: true }).click();
    await p.getByRole('dialog', { name: 'Switch company?' }).getByText('A generation is in progress. Switching may interrupt it.').waitFor();
    await p.getByRole('button', { name: 'Stay here', exact: true }).click();
    assert.equal(await p.evaluate(KEY => localStorage.getItem(KEY), KEY), A);
    await company(p).getByRole('button').first().click(); await company(p).getByRole('button', { name: 'Beta', exact: true }).click();
    await p.getByRole('button', { name: 'Continue and switch', exact: true }).click();
    await company(p).getByRole('button', { name: 'Beta', exact: true }).waitFor();
    release(); await destination(p, 'Generate');
    assert.equal(await p.getByRole('heading', { name: 'Late idea', exact: true }).count(), 0);
  } finally { release(); await f.close(); }
});

test('skip link and mobile navigation keyboard disclosure, Escape and route focus', async () => {
  const f = await fixture({ width: 390 }); const p = f.page;
  try {
    await p.keyboard.press('Tab');
    assert.equal(await p.evaluate(() => document.activeElement.textContent), 'Skip to content');
    await p.keyboard.press('Enter'); assert.equal(await p.evaluate(() => document.activeElement.id), 'main-content');
    const toggle = p.getByRole('button', { name: 'Open navigation', exact: true });
    assert.equal(await primary(p).isVisible(), false);
    await toggle.focus(); await p.keyboard.press('Enter');
    assert.equal(await p.evaluate(() => document.activeElement.textContent), 'Overview');
    await screenshot(p, 'mobile-navigation-390');
    await p.keyboard.press('Escape'); assert.equal(await toggle.evaluate(el => el === document.activeElement), true);
    await toggle.click(); await p.keyboard.press('Tab'); await p.keyboard.press('Enter');
    await p.getByRole('heading', { name: 'Content', level: 1, exact: true }).waitFor();
    assert.equal(await primary(p).isVisible(), false);
    assert.equal(await p.evaluate(() => document.activeElement.id), 'main-content');
  } finally { await f.close(); }
});

for (const width of [1440, 1280, 1024, 768, 390, 320]) test(`all shell destinations and company dropdown fit ${width}px`, async () => {
  const f = await fixture({ width }); const p = f.page;
  try {
    for (const name of pages) {
      await destination(p, name, width);
      assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, name);
      await screenshot(p, `${name.toLowerCase()}-${width}`);
    }
    await company(p).getByRole('button').first().click();
    const bounds = await p.locator('.company-switcher').boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width);
    assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (width <= 390) await screenshot(p, `company-dropdown-${width}`);
  } finally { await f.close(); }
});

test('hash destinations need no Vercel rewrite and API proxy stays first and unchanged', async () => {
  const { rewrites } = JSON.parse(await readFile('vercel.json', 'utf8'));
  assert.deepEqual(rewrites[0], { source: '/api/:path*', destination: 'https://video-analyser-1ek5.onrender.com/api/:path*' });
  for (const source of ['/privacy', '/terms', '/data-deletion']) assert.deepEqual(rewrites.find(rule => rule.source === source), { source, destination: '/index.html' });
});

test('long company names keep header and dropdown usable at desktop and 320px', async () => {
  for (const width of [1440, 320]) {
    const name = 'Long company workspace name '.repeat(7).slice(0, 200);
    const f = await fixture({ width, companyName: name });
    try {
      const trigger = company(f.page).getByRole('button').first();
      assert.equal(await trigger.innerText(), name.trim());
      assert.ok((await trigger.boundingBox()).height <= 44, 'company trigger stays within header');
      await trigger.click();
      await company(f.page).getByRole('button', { name: `${name} — Active`, exact: true }).waitFor();
      assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    } finally { await f.close(); }
  }
});

test('shared native controls expose labels, state, action hierarchy and error styling', async () => {
  const f = await fixture(); const p = f.page;
  try {
    await p.evaluate(async () => {
      const { default: React } = await import('/node_modules/.vite/deps/react.js');
      const dom = await import('/node_modules/.vite/deps/react-dom_client.js');
      const { createRoot } = dom.default ?? dom;
      const { Button, Input, Select, Textarea, Checkbox, IconButton } = await import('/src/ui/controls.tsx');
      const { Panel, Badge, LoadingState } = await import('/src/ui/layout.tsx');
      const h = React.createElement;
      const host = document.createElement('div'); document.body.append(host);
      createRoot(host).render(h(Panel, { id: 'primitive-check' },
        ...['primary', 'secondary', 'ghost', 'danger'].map(variant => h(Button, { variant, key: variant }, `${variant} action`)),
        h(IconButton, { label: 'Sample utility' }, '×'),
        h('label', { htmlFor: 'sample-title' }, 'Sample title'), h(Input, { id: 'sample-title', 'aria-invalid': true }),
        h('label', { htmlFor: 'sample-disabled' }, 'Disabled field'), h(Input, { id: 'sample-disabled', disabled: true }),
        h('label', { htmlFor: 'sample-description' }, 'Sample description'), h(Textarea, { id: 'sample-description' }),
        h('label', { htmlFor: 'sample-choice' }, 'Sample choice'), h(Select, { id: 'sample-choice' }, h('option', {value:'one'}, 'One'), h('option', {value:'two'}, 'Two')),
        h(Checkbox, { label: 'Sample permission' }), h(Badge, {tone:'success'}, 'Saved'), h(LoadingState, {label:'Loading sample'}),
      ));
    });
    await p.getByLabel('Sample title', { exact: true }).fill('Accessible input');
    assert.equal(await p.getByLabel('Sample title', { exact: true }).evaluate(el => getComputedStyle(el).borderTopColor), 'rgb(161, 44, 50)');
    assert.equal(await p.getByLabel('Disabled field').isDisabled(), true);
    assert.equal(await p.getByLabel('Disabled field').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(238, 241, 243)');
    await p.getByLabel('Sample description').fill('Description');
    await p.getByLabel('Sample choice').selectOption('two');
    await p.getByLabel('Sample permission').check(); assert.equal(await p.getByLabel('Sample permission').isChecked(), true);
    const primary = p.getByRole('button', {name:'primary action',exact:true});
    assert.equal(await primary.getAttribute('type'), 'button');
    assert.notEqual(await primary.evaluate(el => getComputedStyle(el).backgroundColor), await p.getByRole('button',{name:'secondary action',exact:true}).evaluate(el => getComputedStyle(el).backgroundColor));
    await p.getByRole('button', {name:'Sample utility'}).waitFor();
    await p.getByRole('status').filter({hasText:'Loading sample'}).waitFor();
  } finally { await f.close(); }
});
