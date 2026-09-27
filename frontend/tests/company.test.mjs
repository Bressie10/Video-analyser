import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { chromium } from 'playwright';
const origin = 'http://127.0.0.1:5283';
let server, browser;
before(async () => {
  server = spawn('./node_modules/.bin/vite', ['--config', 'tests/authenticated.vite.mjs', '--host', '127.0.0.1', '--port', '5283', '--strictPort'], { stdio: 'inherit' });
  for (let i = 0; i < 70; i++) { try { if ((await fetch(origin)).ok) break; } catch {} await new Promise(r => setTimeout(r, 100)); }
  browser = await chromium.launch({ headless: true });
});
after(async () => { await browser?.close(); server?.kill(); });
async function fixture(mode = '', size) {
  const page = await browser.newPage(size ? { viewport: size } : {});
  await page.goto(`${origin}/tests/company.html?mode=${mode}`);
  return page;
}
async function manage(page) {
  await page.getByRole('navigation', { name: 'Company', exact: true }).getByRole('button', { name: /Alpha|Select company|Beta/ }).click();
  await page.getByRole('button', { name: 'Manage companies', exact: true }).first().click();
  await page.getByRole('heading', { name: 'Manage companies', exact: true }).waitFor();
}
async function switchBeta(page) {
  await page.getByRole('navigation').getByRole('button', { name: /Alpha/ }).click();
  await page.getByRole('navigation').getByRole('button', { name: 'Beta', exact: true }).click();
}
test('selector active context, ordinary switch callback and keyboard disclosure', async () => {
  const p = await fixture();
  try {
    const trigger = p.getByRole('navigation').getByRole('button', { name: 'Alpha', exact: true });
    await trigger.focus(); await p.keyboard.press('Enter');
    assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
    assert.equal(await p.getByRole('button', { name: /Old company/ }).count(), 0);
    await p.keyboard.press('Tab'); await p.keyboard.press('Tab'); await p.keyboard.press('Enter');
    await p.getByRole('navigation').getByRole('button', { name: /Beta/ }).waitFor();
    assert.equal(await p.getByRole('dialog').count(), 0);
    assert.equal(await p.getByLabel('Calls').textContent(), 'switch:b');
    await p.getByRole('navigation').getByRole('button', { name: /Beta/ }).click(); await p.keyboard.press('Escape');
    assert.equal(await p.getByRole('navigation').getByRole('button').getAttribute('aria-expanded'), 'false');
    assert.equal(await p.locator('body').textContent().then(t => t.includes('raw-meta')), false);
  } finally { await p.close(); }
});
for (const flag of ['Unsaved edits', 'Generation in progress']) test(`${flag} guards switch and cancel preserves workspace`, async () => {
  const p = await fixture();
  try {
    await p.getByLabel(flag, { exact: true }).check(); await switchBeta(p);
    await p.getByRole('dialog').waitFor(); assert.equal(await p.getByLabel('Calls').textContent(), '');
    await p.getByRole('button', { name: 'Stay here' }).click();
    await switchBeta(p); await p.getByRole('button', { name: 'Continue and switch' }).click();
    await p.getByRole('navigation').getByRole('button', { name: /Beta/ }).waitFor();
    assert.equal(await p.getByLabel('Calls').textContent(), 'switch:b');
  } finally { await p.close(); }
});
test('no company, create selects through callback, setup and skip', async () => {
  const p = await fixture('none');
  try {
    await p.getByRole('heading', { name: 'No company selected' }).waitFor(); await manage(p);
    await p.getByLabel('New company name').fill('New studio'); await p.getByRole('button', { name: 'Create company', exact: true }).click();
    await p.getByRole('heading', { name: 'New studio is ready' }).waitFor();
    assert.equal(await p.getByLabel('Calls').textContent(), 'create:New studio|switch:new');
    await p.getByRole('navigation').getByRole('button', { name: /New studio/ }).waitFor();
    await p.getByRole('button', { name: 'Skip for now' }).click(); await p.getByText('You can link accounts later in Manage companies.').waitFor();
    await p.getByRole('button', { name: 'Connect/link Meta accounts' }).click(); await p.getByRole('heading', { name: 'Manage companies', exact: true }).waitFor();
  } finally { await p.close(); }
});
test('rename archive restore; archived workspace cannot be used', async () => {
  const p = await fixture();
  try {
    await manage(p); await p.getByLabel('Company name', { exact: true }).fill('Renamed'); await p.getByRole('button', { name: 'Save name' }).click();
    await p.getByRole('heading', { name: 'Renamed', exact: true }).waitFor();
    await p.getByRole('button', { name: 'Archive company', exact: true }).click(); await p.getByRole('button', { name: 'Restore company' }).waitFor();
    assert.equal(await p.getByLabel('Facebook Page').isDisabled(), true);
    await p.getByRole('button', { name: 'Back to workspace' }).click(); await p.getByRole('heading', { name: 'Renamed is archived' }).waitFor();
    await p.getByRole('button', { name: 'Manage companies', exact: true }).click(); await p.getByText('Manage existing and archived companies', { exact: true }).click(); await p.getByLabel('Show archived companies').check();
    await p.getByRole('button', { name: 'Renamed — Archived' }).waitFor(); await p.getByRole('button', { name: 'Restore company' }).click();
    await p.getByRole('button', { name: 'Archive company', exact: true }).waitFor();
  } finally { await p.close(); }
});
test('Facebook Instagram Ads link/unlink and specific Ads assign/unassign', async () => {
  const p = await fixture();
  try {
    await manage(p);
    for (const name of ['Facebook Page', 'Instagram Business', 'Ads Business']) { await p.getByLabel(name).check(); assert.equal(await p.getByLabel(name).isChecked(), true); }
    await p.getByRole('checkbox', { name: 'Summer video ad', exact: true }).check(); assert.equal(await p.getByRole('checkbox', { name: 'Summer video ad', exact: true }).isChecked(), true);
    await p.getByRole('checkbox', { name: 'Summer video ad', exact: true }).uncheck(); assert.equal(await p.getByRole('checkbox', { name: 'Summer video ad', exact: true }).isChecked(), false);
    for (const name of ['Facebook Page', 'Instagram Business', 'Ads Business']) { await p.getByLabel(name).uncheck(); assert.equal(await p.getByLabel(name).isChecked(), false); }
  } finally { await p.close(); }
});
for (const width of [320, 600]) test(`empty workspace and management fit ${width}px`, async () => {
  const p = await fixture('empty', { width, height: 800 });
  try {
    await p.getByRole('heading', { name: 'Alpha is ready' }).waitFor();
    await p.getByRole('button', { name: 'Connect/link Meta accounts' }).click();
    await p.getByRole('heading', { name: 'Manage companies', exact: true }).waitFor();
    assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await p.screenshot({ path: `/tmp/company-ui-${width}.png`, fullPage: true });
  } finally { await p.close(); }
});
test('loading, load error/retry, mutation error retain usable context', async () => {
  const p = await fixture('loading');
  try {
    assert.equal(await p.getByRole('button', { name: /Loading companies/ }).isDisabled(), true);
    await p.goto(`${origin}/tests/company.html?mode=error`); await p.getByRole('button', { name: 'Retry companies' }).click(); await p.getByRole('heading', { name: 'Workspace content' }).waitFor();
    await p.goto(`${origin}/tests/company.html?mode=switch-error`); await switchBeta(p); await p.getByRole('alert').waitFor();
    await p.getByRole('navigation').getByRole('button', { name: /Alpha/ }).waitFor();
  } finally { await p.close(); }
});
test('generation guard remains registered on management page', async () => {
  const p = await fixture();
  try {
    await p.getByLabel('Generation in progress', { exact: true }).check(); await manage(p);
    await switchBeta(p); await p.getByRole('dialog').getByText('A generation is in progress. Switching may interrupt it.').waitFor();
    await p.keyboard.press('Escape'); assert.equal(await p.getByLabel('Calls').textContent(), '');
  } finally { await p.close(); }
});
test('create retry does not duplicate a company after activation fails', async () => {
  const p = await fixture('switch-error');
  try {
    await manage(p); await p.getByLabel('New company name').fill('Retry studio'); await p.getByRole('button', { name: 'Create company', exact: true }).click();
    await p.getByRole('alert').waitFor(); await p.getByRole('button', { name: 'Create company', exact: true }).click();
    await p.waitForFunction(() => document.querySelector('output').textContent === 'create:Retry studio|switch:new|switch:new');
    await p.getByText('Manage existing and archived companies', { exact: true }).click(); assert.equal(await p.getByRole('button', { name: 'Retry studio', exact: true }).count(), 1);
  } finally { await p.close(); }
});
