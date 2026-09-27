import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';
const origin = 'http://127.0.0.1:5288', KEY = 'video-analyzer.active-company-id';
let backend, vite, browser, directory, session, companies;
async function wait(url, child) {
  for (let i = 0; i < 200; i++) {
    if (child.exitCode !== null) throw Error(`Server exited ${child.exitCode}`);
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise(r => setTimeout(r, 100));
  }
  throw Error(`Server unavailable: ${url}`);
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Server did not stop')), 20000);
    child.once('exit', () => { clearTimeout(timer); resolve(); }); child.kill('SIGTERM');
  });
}
before(async () => {
  assert.ok(process.env.TEST_DATABASE_URL, 'TEST_DATABASE_URL must point to disposable PostgreSQL');
  directory = await mkdtemp(join(tmpdir(), 'company-browser-'));
  backend = spawn('.venv/bin/python', ['tests/wave2_browser_server.py'], { cwd: '../backend', env: { ...process.env, FRONTEND_E2E_PORT: "8163", COMPANY_E2E_DIRECTORY: directory }, stdio: 'inherit' });
  await wait('http://127.0.0.1:8163/health', backend);
  vite = spawn('./node_modules/.bin/vite', ['--config', 'tests/wave2-integration.vite.mjs'], { stdio: 'inherit' });
  await wait(origin, vite);
  session = JSON.parse(await readFile(join(directory, 'session.json'), 'utf8'));
  browser = await chromium.launch({ headless: true });
  const c = await context();
  companies = (await (await c.request.get(`${origin}/api/companies`)).json()).companies;
  await c.close();
});
after(async () => {
  await browser?.close(); await stop(vite); await stop(backend);
  if (directory) {
    const report = JSON.parse(await readFile(join(directory, 'report.json'), 'utf8'));
    try { assert.equal(report.model_calls, 1); assert.deepEqual(report.ideas, [{title:'Wave 2 saved Title',script:'Wave 2 saved Script',status:'used',feedback:'liked'}]); }
    finally { await rm(directory, { recursive: true, force: true }); }
  }
});
async function context(persisted) {
  const c = await browser.newContext({ extraHTTPHeaders: { Cookie: `${session.name}=${session.value}`, Authorization: `Bearer ${session.jwt}` } });
  await c.addInitScript(jwt => { window.__authMock = { session: { access_token: jwt, user: { id: '11111111-1111-4111-8111-111111111111', email: 'test@example.com' } } }; }, session.jwt);
  await c.addCookies([{ name: session.name, value: session.value, domain: '127.0.0.1', path: '/api', httpOnly: true, secure: true, sameSite: 'Lax' }]);
  if (persisted !== undefined) await c.addInitScript(({ KEY, persisted }) => { if (!sessionStorage.initialized) { localStorage.setItem(KEY, persisted); sessionStorage.initialized = 'true'; } }, { KEY, persisted });
  return c;
}
async function pageFor(c) { const p = await c.newPage(); p.setDefaultTimeout(10000); await p.goto(`${origin}#ideas`); return p; }
const nav = p => p.getByRole('navigation', { name: 'Company', exact: true });
async function manage(p) { await nav(p).getByRole('button').first().click(); await nav(p).getByRole('button', { name: 'Manage companies', exact: true }).click(); await p.getByRole('heading', { name: 'Manage companies', exact: true }).waitFor(); }
async function select(p, name) { await nav(p).getByRole('button').first().click(); await nav(p).getByRole('button', { name, exact: true }).click(); }
async function selected(p, name) { await nav(p).getByRole('button', { name, exact: true }).waitFor(); }
async function stored(p, id) { await p.waitForFunction(({KEY,id}) => localStorage.getItem(KEY) === id, {KEY,id}); }
async function check(p, name, checked) {
  const input = p.getByRole('checkbox', { name, exact: true });
  assert.notEqual(await input.isChecked(), checked);
  await Promise.all([p.waitForResponse(r => r.request().method() === (checked ? 'PUT' : 'DELETE') && r.url().includes('/api/companies/')), input.click()]);
  await p.waitForFunction(() => !document.body.textContent.includes('Saving company changes…') && !document.body.textContent.includes('Loading available accounts and ads…'));
  assert.equal(await input.isChecked(), checked);
}
test('browser → React → FastAPI → PostgreSQL: content, generation, history, explicit save, feedback, lifecycle and publications', {timeout:90000}, async () => {
  const c = await context(); const p = await pageFor(c); const calls = []; const errors = [];
  p.on('request', r => { if (r.url().includes('/api/')) calls.push(r); }); p.on('pageerror', e => errors.push(e.message));
  const b = companies.find(c => c.name === 'B');
  const get = async path => { const r = await c.request.get(origin + path); assert.equal(r.status(),200,await r.text()); return r.json(); };
  try {
    await manage(p);
    await p.getByLabel('New company name').fill('Release studio');
    await p.getByRole('button',{name:'Create company',exact:true}).click();
    await selected(p,'Release studio');
    const a = {company_id:await p.evaluate(KEY=>localStorage.getItem(KEY),KEY),name:'Release studio'};
    companies.push(a);
    const base = `/api/meta/companies/${a.company_id}`;
    await manage(p);
    await check(p,'Release Facebook',true); await check(p,'Release Instagram',true);
    await p.getByRole('button',{name:'Back to workspace',exact:true}).click();
    const allA = await get(`/api/companies/${a.company_id}/content?analyzed_only=true&limit=100`);
    const allB = await get(`/api/companies/${b.company_id}/content?analyzed_only=true&limit=100`);
    assert.equal(allA.items.length,25);
    // Shared creative may legitimately belong to both; direct organic B content must not leak.
    for (const item of allB.items.filter(i => i.content_type === 'reel')) assert.equal(allA.items.some(a => a.library_item_id === item.library_item_id),false);
    assert.ok((await get(`/api/companies/${a.company_id}/content?limit=100`)).items.some(i => i.video_id === null && !i.analyzed));
    await p.getByRole('navigation', {name:'Primary'}).getByRole('link', {name:'Content',exact:true}).click();
    const library = p.getByRole('region',{name:'Company content library'});
    await library.getByText('Facebook video',{exact:true}).first().waitFor();
    await library.getByLabel('Content platform').selectOption('instagram'); await library.getByText('Instagram reel',{exact:true}).waitFor();
    assert.equal(await library.getByText('Facebook video',{exact:true}).count(),0);
    await library.getByLabel('Content platform').selectOption('');
    await p.getByRole('navigation', {name:'Primary'}).getByRole('link', {name:'Generate',exact:true}).click();
    await p.getByRole('button',{name:'Generate idea',exact:true}).click();
    await p.locator('.idea-result h2').waitFor();
    const generation = calls.find(r => r.url().endsWith('/recommendations')).postDataJSON();
    assert.deepEqual(generation.video_ids,allA.items.slice(0,20).map(i=>i.library_item_id));
    assert.equal(generation.video_ids.includes(allA.items[0].video_id),false);
    assert.deepEqual([...generation.target_platforms].sort(),['facebook','instagram']);
    const history = await get(base+'/ideas'); assert.equal(history.items.length,1);
    const id = history.items[0].id; const title = history.items[0].title;
    await p.getByRole('navigation', {name:'Primary'}).getByRole('link', {name:'Ideas',exact:true}).click();
    await p.getByRole('button',{name:title,exact:true}).click();
    await p.getByRole('button',{name:'Edit',exact:true}).click();
    for (const field of ['Title','Concept','Script']) await p.getByLabel(field,{exact:true}).fill(`Wave 2 saved ${field}`);
    await p.getByRole('button',{name:'Save',exact:true}).click();
    const saved = () => p.getByRole('status').filter({hasText:/^Saved\.$/}).waitFor(); await saved();
    await p.getByRole('button',{name:'Like',exact:true}).click(); await saved();
    await p.getByRole('button',{name:'Dislike',exact:true}).click();
    await p.getByLabel('Dislike reason (optional)').fill('Needs a stronger hook');
    await p.getByRole('button',{name:'Save dislike',exact:true}).click(); await saved();
    assert.equal((await get(base+'/ideas/'+id)).feedback_reason,'Needs a stronger hook');
    await p.getByRole('button',{name:'Like',exact:true}).click(); await saved();
    assert.equal((await get(base+'/ideas/'+id)).feedback_reason,null);
    await p.getByRole('button',{name:'Used',exact:true}).click(); await saved();
    await p.getByRole('button',{name:'Link published content',exact:true}).click();
    await p.getByRole('dialog').locator('time').first().waitFor();
    await p.getByRole('dialog').getByRole('button',{name:/^Link /}).first().click();
    await p.getByRole('status').filter({hasText:'1 linked'}).waitFor();
    await p.getByRole('dialog').getByRole('button',{name:/^Link /}).first().click();
    await p.getByRole('status').filter({hasText:'2 linked'}).waitFor(); await p.getByRole('button',{name:'Done',exact:true}).click();
    let detail = await get(base+'/ideas/'+id); assert.equal(detail.title,'Wave 2 saved Title'); assert.equal(detail.concept,'Wave 2 saved Concept'); assert.equal(detail.script,'Wave 2 saved Script'); assert.equal(detail.feedback,'liked'); assert.equal(detail.status,'used'); assert.equal(detail.publications.length,2);
    await p.getByRole('button',{name:'Unlink Linked published content',exact:true}).first().click(); await saved();
    detail = await get(base+'/ideas/'+id); assert.equal(detail.publications.length,1);
    await p.getByText('Live availability is not verified.',{exact:false}).waitFor();
    await p.reload(); await p.getByRole('button',{name:'Wave 2 saved Title',exact:true}).click(); await p.getByText('Wave 2 saved Script',{exact:true}).waitFor();
    await manage(p); await p.getByText('Company intelligence · Release studio',{exact:true}).click();
    await p.getByRole('button',{name:'Refresh company intelligence',exact:true}).click(); await p.getByText('Refresh requested.',{exact:false}).waitFor();
    await p.getByText('Company intelligence refreshed.',{exact:true}).waitFor();
    await select(p,'B'); await selected(p,'B'); await p.getByText('No saved ideas yet for this company.').waitFor();
    assert.equal((await p.locator('body').innerText()).includes('Wave 2 saved'),false);
    await p.reload(); await selected(p,'B'); await stored(p,b.company_id);
    await p.getByText('No saved ideas yet for this company.').waitFor();
    assert.equal((await p.locator('body').innerText()).includes('Wave 2 saved'),false);
    assert.equal(calls.some(r=>/^\/api\/meta\/(library|jobs|sync|recommendations)/.test(new URL(r.url()).pathname)),false);
    assert.deepEqual(errors,[]);
  } finally { await c.close(); }
});

test('real archived-company mutation shows safe failure and preserves saved data',async()=>{
  const a=companies.find(c=>c.name==='Release studio'); const c=await context(a.company_id); const p=await pageFor(c);
  try {
    await p.getByRole('button',{name:'Wave 2 saved Title',exact:true}).click(); await p.getByRole('button',{name:'Edit',exact:true}).click(); await p.getByLabel('Title',{exact:true}).fill('Must not save');
    assert.equal((await c.request.post(`${origin}/api/companies/${a.company_id}/archive`)).status(),200);
    await p.getByRole('button',{name:'Save',exact:true}).click(); await p.getByRole('alert').filter({hasText:'archived'}).waitFor(); assert.equal(await p.getByLabel('Title',{exact:true}).inputValue(),'Must not save');
    assert.equal((await c.request.post(`${origin}/api/companies/${a.company_id}/restore`)).status(),200);
    const history=await (await c.request.get(`${origin}/api/meta/companies/${a.company_id}/ideas`)).json(); assert.equal(history.items[0].title,'Wave 2 saved Title');
  } finally {await c.close();}
});
