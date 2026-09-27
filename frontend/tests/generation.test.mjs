import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { createServer } from 'vite';
import { chromium } from 'playwright';
let server, browser, origin, apiModule;
const uuid = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const A = uuid(1000), B = uuid(2000);
const item = n => ({ library_item_id: uuid(n), video_id: n % 2 ? null : uuid(n+5000), display_title: `Source ${n}`, platform: n % 2 ? 'instagram' : 'facebook', published_at: new Date(Date.UTC(2026, 0, n)).toISOString(), analyzed: true });
const company = (id, name, platforms = ['instagram', 'facebook', 'meta_ads']) => ({ company_id: id, name, archived: false, accounts: platforms.map((platform, i) => ({ account_id: uuid(3000+i), display_name: platform, platform })) });
const saved = { id: uuid(9000), company_id: A, title: 'Persisted winter idea', concept: 'Help homeowners prepare.', script: 'Start with the roof.\nThen check the windows.', target_platforms: ['instagram'] };
before(async () => {
  server = await createServer({ server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); await server.listen(); origin = server.resolvedUrls.local[0];
  apiModule = await server.ssrLoadModule('/src/generation/generationApi.ts'); browser = await chromium.launch();
});
after(async () => { await browser?.close(); await server?.close(); });
async function app(options = {}) {
  const context = await browser.newContext(); const calls = []; const errors = [];
  await context.addInitScript(() => { const original = window.fetch.bind(window); window.fetch = (url, options) => original(url, /\/(content|recommendations)(\?|$)/.test(String(url)) ? {...options, signal: undefined} : options); });
  if (!options.noCompany) await context.addInitScript(id => localStorage.setItem('video-analyzer.active-company-id', id), A);
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/recommendations')) { calls.push(route.request().postDataJSON()); if (options.generate) return options.generate(route, calls); return route.fulfill({ json: saved }); }
    if (path.endsWith('/content') && new URL(route.request().url()).searchParams.get('analyzed_only') !== 'true') return route.fulfill({ json: {items:[],next_offset:null} });
    if (path.endsWith('/ideas')) return route.fulfill({ json: {items:[],next_cursor:null} });
    if (path.endsWith('/content')) { if (options.sources) return options.sources(route, path); const q = new URL(route.request().url()).searchParams; const offset = Number(q.get('offset') || 0); const rows = Array.from({ length: options.count ?? 25 }, (_, i) => item(i+1)).reverse(); return route.fulfill({ json: { items: rows.slice(offset, offset+20), next_offset: offset+20 < rows.length ? offset+20 : null } }); }
    if (path === '/api/companies') return route.fulfill({ json: { companies: [company(A, 'Alpha', options.platforms), company(B, 'Beta')] } });
    if (path === '/api/meta/test') return route.fulfill({ json: { connected: false } });
    return route.fulfill({ json: { accounts: [] } });
  });
  const page = await context.newPage(); page.setDefaultTimeout(5000); page.on('pageerror', e => errors.push(e.message)); await page.goto(origin);
  return { page, calls, errors, close: () => context.close() };
}
const generate = p => p.getByRole('button', { name: 'Generate idea', exact: true });
async function switchBeta(p) { const nav = p.getByRole('navigation', { name: 'Company', exact: true }); await nav.getByRole('button', { name: 'Alpha', exact: true }).click(); await nav.getByRole('button', { name: 'Beta', exact: true }).click(); }
for (const count of [1, 7, 20, 25]) test(`default All mode resolves latest ${count} available to explicit max 20 IDs`, async () => {
  const f = await app({ count }); const p = f.page;
  try {
    await generate(p).waitFor(); await p.waitForFunction(() => !document.querySelector('button[type=submit]').disabled);
    assert.equal(await p.getByLabel('All analyzed content', { exact: true }).isChecked(), true);
    assert.equal(await p.getByLabel('Instagram', { exact: true }).isChecked(), true); assert.equal(await p.getByLabel('Facebook', { exact: true }).isChecked(), true);
    assert.equal(await p.getByRole('checkbox', { name: /Meta Ads/ }).count(), 0);
    await p.getByLabel('Facebook', { exact: true }).uncheck(); await generate(p).click();
    await p.getByRole('heading', { name: saved.title }).waitFor();
    assert.deepEqual(f.calls[0].video_ids, Array.from({ length: Math.min(20, count) }, (_, i) => uuid(count-i)));
    assert.equal(f.calls[0].generation_brief, null); assert.deepEqual(f.calls[0].target_platforms, ['instagram']); assert.match(f.calls[0].request_id, /^[a-f0-9-]{36}$/);
    assert.equal(p.url(), origin); assert.equal(await p.locator('.concept').textContent(), saved.concept); assert.equal(await p.locator('.script').textContent(), saved.script); assert.deepEqual(f.errors, []);
  } finally { await f.close(); }
});
test('manual search, filter, max 20, deselection, optional brief, no-target block and keyboard', async () => {
  const f = await app(); const p = f.page;
  try {
    const radio = p.getByLabel('Choose manually'); await radio.waitFor(); await radio.focus(); await p.keyboard.press('Space');
    await p.getByRole('checkbox', { name: /^Source 25 / }).waitFor(); assert.equal(await generate(p).isDisabled(), true);
    const choices = p.locator('.generation-sources input');
    for (let i=0;i<20;i++) await choices.nth(i).check();
    assert.equal(await choices.nth(20).isDisabled(), true); await choices.nth(0).uncheck(); assert.equal(await choices.nth(20).isDisabled(), false); await choices.nth(20).check();
    await p.getByLabel('Search analyzed content').fill('nothing'); await p.getByText('No analyzed content matches', { exact: false }).waitFor();
    await p.getByLabel('Search analyzed content').fill('Source 2'); await p.getByLabel('Source platform').selectOption('facebook');
    assert.ok(await p.locator('.generation-sources label').count() > 0);
    await p.getByLabel('Instagram', { exact: true }).uncheck(); await p.getByLabel('Facebook', { exact: true }).uncheck(); assert.equal(await generate(p).isDisabled(), true);
    await p.getByLabel('Facebook', { exact: true }).focus(); await p.keyboard.press('Space');
    await p.getByLabel('Brief (optional)').fill('Make something aimed at homeowners before winter'); await generate(p).click(); await p.getByRole('heading', { name: saved.title }).waitFor();
    assert.equal(f.calls[0].video_ids.length, 20); assert.equal(f.calls[0].video_ids.includes(uuid(25)), false); assert.equal(f.calls[0].generation_brief, 'Make something aimed at homeowners before winter');
  } finally { await f.close(); }
});
test('manual selection and result reset on company switch', async () => {
  const f = await app(); const p = f.page;
  try { await p.getByLabel('Choose manually').check(); await p.locator('.generation-sources input').first().check(); await generate(p).click(); await p.getByRole('heading', { name: saved.title }).waitFor(); await switchBeta(p); await p.getByLabel('All analyzed content', { exact: true }).waitFor(); assert.equal(await p.getByRole('heading', { name: saved.title }).count(), 0); await p.getByLabel('Choose manually').check(); assert.equal(await p.locator('.generation-sources input:checked').count(), 0); } finally { await f.close(); }
});
test('stale content response ignored after switching companies', async () => {
  let release, began; const gate = new Promise(r => release=r), started = new Promise(r => began=r);
  const f = await app({ sources: async (route, path) => { if (path.includes(A)) { began(); await gate; } await route.fulfill({ json: { items: [item(path.includes(A) ? 1 : 2)], next_offset: null } }).catch(() => {}); } });
  try { await started; await switchBeta(f.page); await f.page.getByLabel('Choose manually').check(); await f.page.getByRole('checkbox', { name: /^Source 2 / }).waitFor(); release(); await f.page.waitForTimeout(100); assert.equal(await f.page.getByRole('checkbox', { name: /^Source 1 / }).count(), 0); } finally { release(); await f.close(); }
});
test('duplicate submission locked and generation registers switch guard; late result hidden', async () => {
  let release; const gate = new Promise(r => release=r);
  const f = await app({ generate: async route => { await gate; await route.fulfill({ json: saved }).catch(() => {}); } }); const p = f.page;
  try { await generate(p).click(); await p.getByText('Generating and saving', { exact: false }).waitFor(); await p.locator('.generation form').evaluate(form => { form.requestSubmit(); form.requestSubmit(); }); assert.equal(f.calls.length, 1); await switchBeta(p); await p.getByRole('dialog').waitFor(); await p.getByRole('button', { name: 'Stay here' }).click(); await switchBeta(p); await p.getByRole('button', { name: 'Continue and switch' }).click(); release(); await p.getByRole('navigation').getByRole('button', { name: 'Beta', exact: true }).waitFor(); assert.equal(await p.getByRole('heading', { name: saved.title }).count(), 0); } finally { release(); await f.close(); }
});
for (const failure of [401, 404, 409, 422, 502, 503, 'network']) test(`safe generation failure ${failure}`, async () => {
  const f = await app({ generate: route => failure === 'network' ? route.abort() : route.fulfill({ status: failure, json: { detail: 'SECRET-PROVIDER' } }) });
  try { await generate(f.page).click(); await f.page.getByRole('alert').first().waitFor(); assert.equal((await f.page.locator('body').innerText()).includes('SECRET-PROVIDER'), false);
    if (![401,404].includes(failure)) { await generate(f.page).click(); await f.page.getByRole('alert').first().waitFor(); assert.equal(f.calls.length, 2); assert.equal(f.calls[0].request_id, f.calls[1].request_id); }
  } finally { await f.close(); }
});
for (const scenario of ['noCompany', 'empty', 'adsOnly']) test(`empty state ${scenario}`, async () => {
  const f = await app(scenario === 'noCompany' ? { noCompany: true } : scenario === 'empty' ? { count: 0 } : { platforms: ['meta_ads'] });
  try {
    if (scenario === 'noCompany') await f.page.getByRole('heading', { name: 'No company selected' }).waitFor();
    else { await f.page.getByText(scenario === 'empty' ? 'No analyzed source content available' : 'No linked publishing platforms.', { exact: false }).waitFor(); assert.equal(await generate(f.page).isDisabled(), true); await f.page.getByRole('button', { name: scenario === 'empty' ? 'Company and account setup' : 'Company setup', exact: true }).click(); await f.page.getByRole('heading', { name: 'Manage companies', exact: true }).waitFor(); }
  } finally { await f.close(); }
});
test('source error retry and loading state', async () => {
  let count=0; const f = await app({ sources: route => ++count === 1 ? route.fulfill({ status: 503, json: { detail: 'SECRET' } }) : route.fulfill({ json: { items: [item(1)], next_offset: null } }) });
  try { await f.page.getByRole('button', { name: 'Retry sources' }).click(); await f.page.getByText('Using 1 source item', { exact: false }).waitFor(); assert.equal(await generate(f.page).isEnabled(), true); } finally { await f.close(); }
});
test('responsive 320/600/1280 and result focus', async () => {
  const f = await app(); const p = f.page;
  try { await p.getByLabel('Choose manually').check(); await p.locator('.generation-sources input').first().check();
    for (const width of [320,600,1280]) { await p.setViewportSize({ width, height: 900 }); assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); await p.screenshot({ path: `/tmp/generation-${width}.png`, fullPage: true }); }
    await p.setViewportSize({ width:320,height:900 }); await generate(p).click(); await p.getByRole('heading', { name: saved.title }).waitFor(); assert.equal(await p.evaluate(() => document.activeElement.id), 'generated-title'); assert.equal(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  } finally { await f.close(); }
});
test('adapter pagination, analyzed-only, deduplication and latest order', async () => {
  const paths=[]; const api=apiModule.createGenerationApi(async path => { paths.push(path); return new Response(JSON.stringify(paths.length===1 ? {items:[item(1), {...item(2),analyzed:false}],next_offset:20} : {items:[item(1),item(3)],next_offset:null})); });
  const rows=await api.listSources(A,new AbortController().signal,true); assert.deepEqual(rows.map(i=>i.id),[uuid(1),uuid(3)]); assert.match(paths[1],/offset=20/); assert.match(paths[0],/analyzed_only=true/);
});
test('adapter rejects malformed or non-persisted results and invalid generation input', async () => {
  const input={companyId:A,sourceIds:[uuid(1)],targetPlatforms:['instagram'],idempotencyKey:uuid(6)};
  for (const result of [{...saved,id:undefined},{...saved,company_id:B},{...saved,script:''}]) { const api=apiModule.createGenerationApi(async()=>new Response(JSON.stringify(result))); await assert.rejects(api.generate(input,new AbortController().signal)); }
  const api=apiModule.createGenerationApi(async()=>{throw Error('must not fetch');});
  for (const patch of [{sourceIds:[]},{sourceIds:Array.from({length:21},(_,i)=>uuid(i+1))},{targetPlatforms:[]}]) await assert.rejects(api.generate({...input,...patch},new AbortController().signal),e=>e.status===422);
});
test('successful generations get fresh keys and release switch guard', async () => {
  const f = await app({count:2}); const p=f.page;
  try { await generate(p).click(); await p.getByRole('heading',{name:saved.title}).waitFor(); await generate(p).click(); await p.waitForFunction(()=>!document.querySelector('button[type=submit]').disabled); assert.equal(f.calls.length,2); assert.notEqual(f.calls[0].request_id,f.calls[1].request_id); assert.equal(await p.locator('.idea-result').count(),1); await switchBeta(p); assert.equal(await p.getByRole('dialog').count(),0); } finally { await f.close(); }
});
test('loading disables generation and changed retry payload gets a new key', async () => {
  let release; const gate=new Promise(r=>release=r);
  const f=await app({sources:async route=>{await gate; await route.fulfill({json:{items:[item(1)],next_offset:null}});},generate:route=>route.abort()}); const p=f.page;
  try { await p.getByText('Loading analyzed source content…').waitFor(); assert.equal(await generate(p).isDisabled(),true); release(); await generate(p).click(); await p.getByRole('alert').waitFor(); await p.getByLabel('Brief (optional)').fill('A different brief'); await generate(p).click(); await p.getByRole('alert').waitFor(); assert.equal(f.calls.length,2); assert.notEqual(f.calls[0].request_id,f.calls[1].request_id); await p.getByRole('button',{name:'Reload sources'}).click(); await p.getByText('Using 1 source item',{exact:false}).waitFor(); } finally {release(); await f.close();}
});
test('default source resolution fetches only latest page 20 and uses library IDs despite null/different video IDs', async () => {
  const calls=[];
  const api=apiModule.createGenerationApi(async path => { calls.push(path); return new Response(JSON.stringify({items:[item(1),item(2)],next_offset:20})); });
  const rows=await api.listSources(A,new AbortController().signal);
  assert.equal(calls.length,1);
  assert.deepEqual(Object.fromEntries(new URL(calls[0],'http://local').searchParams),{analyzed_only:'true',limit:'20',order:'desc'});
  assert.deepEqual(rows.map(i=>i.id),[uuid(1),uuid(2)]);
  assert.equal(rows.some(i=>i.id===uuid(5002)),false);
});
