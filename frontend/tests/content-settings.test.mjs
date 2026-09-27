import { authAlias } from './authenticated.vite.mjs';
import assert from 'node:assert/strict';
import { test,before,after } from 'node:test';
import { createServer } from 'vite';
import { chromium } from 'playwright';
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const A=id(1), B=id(2); let server,browser,origin;
before(async()=>{server=await createServer({ resolve: { alias: authAlias },server:{host:'127.0.0.1',port:0},logLevel:'error'});await server.listen();origin=server.resolvedUrls.local[0];browser=await chromium.launch();});
after(async()=>{await browser?.close();await server?.close();});
async function fixture(intercept){
  const c=await browser.newContext();await c.addInitScript(A=>{localStorage.setItem('video-analyzer.active-company-id',A);const original=window.fetch.bind(window);window.fetch=(url,options)=>original(url,{...options,signal:undefined});},A);
  await c.route('**/api/**',async route=>{
    const u=new URL(route.request().url());
    if(await intercept?.(route,u))return;
    if (new URL(route.request().url()).pathname === '/api/me/companies') return route.fulfill({ json: { companies: [A, B].map(value => ({ id: typeof value === 'string' ? value : value.id, archived_at: null })) } });
    if(u.pathname==='/api/companies')return route.fulfill({json:{companies:[A,B].map((company_id,i)=>({company_id,name:i?'Beta':'Alpha',role: "owner", archived: false,accounts:[]}))}});
    if(u.pathname.endsWith('/ideas'))return route.fulfill({json:{items:[],next_cursor:null}});
    if(u.pathname.endsWith('/content'))return route.fulfill({json:{items:[],next_offset:null}});
    if(u.pathname.endsWith('/profiles'))return route.fulfill({json:{profiles:[{scope:'shared',freshness:'fresh',job:{state:'completed'}}]}});
    return route.fulfill({json:{accounts:[],connected:false}});
  });
  const p=await c.newPage();p.setDefaultTimeout(5000);await p.goto(`${origin}#content`);return {p,close:()=>c.close()};
}
const button=(p,name)=>p.getByRole('button',{name,exact:true});
async function manage(p){const nav=p.getByRole('navigation',{name:'Company',exact:true});await nav.getByRole('button').first().click();await button(nav,'Manage companies').click();await p.getByText('Company intelligence · Alpha',{exact:true}).click();}
async function switchB(p){const nav=p.getByRole('navigation',{name:'Company',exact:true});await nav.getByRole('button').first().click();await button(nav,'Beta').click();}
const card=(company,n)=>({library_item_id:id(n),video_id:null,display_title:`${company} post ${n}`,platform:'facebook',content_type:'video',published_at:null,analysis_state:'discovered',analyzed:false,summary:{duration_seconds:null,width:null,height:null}});
test('company content browsing filters before pagination and resets on switch; no global requests',async()=>{
  const calls=[];const f=await fixture(async(route,u)=>{calls.push(u.pathname);if(!u.pathname.endsWith('/content')||u.searchParams.get('analyzed_only')==='true')return false;assert.equal(u.searchParams.has('search')&&u.searchParams.get('search')==='',false);const company=u.pathname.includes(A)?'Alpha':'Beta';const offset=Number(u.searchParams.get('offset'));return route.fulfill({json:{items:[card(company,offset?30:10)],next_offset:offset||u.searchParams.get('search')?null:20}}).then(()=>true);});
  try {await f.p.getByText('Alpha post 10',{exact:true}).waitFor();await button(f.p,'Next content').click();await f.p.getByText('Alpha post 30',{exact:true}).waitFor();await f.p.getByLabel('Search content',{exact:true}).fill('post');await f.p.getByText('Alpha post 10',{exact:true}).waitFor();await switchB(f.p);await f.p.getByText('Beta post 10',{exact:true}).waitFor();assert.equal(await f.p.getByLabel('Search content',{exact:true}).inputValue(),'');assert.equal((await f.p.locator('body').innerText()).includes('Alpha post'),false);assert.equal(calls.some(p=>p==='/api/meta/library'),false);}finally{await f.close();}
});
test('late content browse response cannot display underneath a new company even without transport abort',async()=>{
  let release,began;const gate=new Promise(r=>release=r),started=new Promise(r=>began=r);
  const f=await fixture(async(route,u)=>{if(!u.pathname.includes(A)||!u.pathname.endsWith('/content')||u.searchParams.get('analyzed_only')==='true')return false;began();await gate;await route.fulfill({json:{items:[card('Alpha',10)],next_offset:null}}).catch(()=>{});return true;});
  try{await started;await switchB(f.p);release();await f.p.waitForTimeout(100);assert.equal((await f.p.locator('body').innerText()).includes('Alpha post'),false);}finally{release();await f.close();}
});
test('settings refresh safely retries transport uncertainty with same key and sends active company',async()=>{
  const calls=[];const f=await fixture(async(route,u)=>{if(!u.pathname.endsWith('/refresh'))return false;calls.push({path:u.pathname,key:route.request().headers()['idempotency-key']});await(calls.length===1?route.abort():route.fulfill({status:202,json:{}}));return true;});
  try{await manage(f.p);await button(f.p,'Refresh company intelligence').click();await f.p.getByRole('alert').waitFor();await button(f.p,'Refresh company intelligence').click();await f.p.getByText('Refresh requested.',{exact:false}).waitFor();assert.equal(calls[0].path,`/api/companies/${A}/profiles/shared/refresh`);assert.equal(calls[0].key,calls[1].key);await button(f.p,'Refresh company intelligence').click();await f.p.getByText('Refresh requested.',{exact:false}).waitFor();assert.notEqual(calls[1].key,calls[2].key);}finally{await f.close();}
});
for(const status of [401,404,409])test(`settings refresh ${status} shows safe error`,async()=>{
  const f=await fixture(async(route,u)=>{if(!u.pathname.endsWith('/refresh'))return false;await route.fulfill({status,json:{detail:'SECRET'}});return true;});
  try{await manage(f.p);await button(f.p,'Refresh company intelligence').click();await f.p.getByRole('alert').waitFor();assert.equal((await f.p.locator('body').innerText()).includes('SECRET'),false);}finally{await f.close();}
});
test('settings tracks queued, running, completed and failed refresh jobs without rendering provider details',async()=>{
  let state='queued';const f=await fixture(async(route,u)=>{
    if(u.pathname.endsWith('/refresh')){await route.fulfill({status:202,json:{job_id:id(90)}});return true;}
    if(u.pathname.endsWith('/profiles')){await route.fulfill({json:{profiles:[{scope:'shared',freshness:'fresh',job:{id:id(90),state,error:'PRIVATE PROVIDER DETAIL'}}]}});return true;}
    return false;
  });
  try{await manage(f.p);await button(f.p,'Refresh company intelligence').click();await f.p.getByText('Company intelligence refresh queued.',{exact:true}).waitFor();
    state='running';await f.p.getByText('Company intelligence refresh in progress.',{exact:true}).waitFor();
    state='completed';await f.p.getByText('Company intelligence refreshed.',{exact:true}).waitFor();
    state='failed';await button(f.p,'Refresh company intelligence').click();await f.p.getByRole('alert').filter({hasText:'Company intelligence refresh failed. Try again.'}).waitFor();
    assert.equal((await f.p.locator('body').innerText()).includes('PRIVATE PROVIDER DETAIL'),false);
  }finally{await f.close();}
});
test('refresh status network failure retries only the read and does not submit another job',async()=>{
  let posts=0,reads=0;const f=await fixture(async(route,u)=>{
    if(u.pathname.endsWith('/refresh')){posts++;await route.fulfill({status:202,json:{job_id:id(90)}});return true;}
    if(u.pathname.endsWith('/profiles')){reads++;if(reads===1){await route.abort();return true;}}
    return false;
  });
  try{await manage(f.p);await button(f.p,'Refresh company intelligence').click();await button(f.p,'Retry refresh status').click();await f.p.getByText('Company intelligence refreshed.',{exact:true}).waitFor();assert.equal(posts,1);assert.equal(reads,2);}finally{await f.close();}
});
test('late refresh status cannot populate another company even if transport ignores abort',async()=>{
  let release,began;const gate=new Promise(r=>release=r),started=new Promise(r=>began=r);
  const f=await fixture(async(route,u)=>{
    if(u.pathname.endsWith('/refresh')){await route.fulfill({status:202,json:{job_id:id(90)}});return true;}
    if(u.pathname.includes(A)&&u.pathname.endsWith('/profiles')){began();await gate;await route.fulfill({json:{profiles:[{scope:'shared',freshness:'fresh',job:{state:'completed'}}]}}).catch(()=>{});return true;}
    return false;
  });
  try{await manage(f.p);await button(f.p,'Refresh company intelligence').click();await started;await switchB(f.p);release();await f.p.waitForTimeout(100);assert.equal((await f.p.locator('body').innerText()).includes('Company intelligence refreshed.'),false);}finally{release();await f.close();}
});
