import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { createServer } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
const A='00000000-0000-4000-8000-000000000001', B='00000000-0000-4000-8000-000000000002';
const U='10000000-0000-4000-8000-000000000001', V='10000000-0000-4000-8000-000000000002';
const KEY='video-analyzer.active-company-id', AUTH='sb-auth-test-auth-token';
function session(id=U) { return { access_token: `test-token-${id}`, refresh_token: `refresh-${id}`, token_type:'bearer', expires_in:3600, expires_at: Math.floor(Date.now()/1000)+3600, user:{id,email:id===U?'alice@example.com':'bob@example.com',aud:'authenticated',role:'authenticated',app_metadata:{provider:'email'},user_metadata:{},created_at:'2026-01-01T00:00:00Z'} }; }
let server,browser,origin;
before(async()=>{
 server=await createServer({configFile:false,plugins:[react()],define:{'import.meta.env.VITE_SUPABASE_URL':JSON.stringify('https://auth-test.supabase.co'),'import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY':JSON.stringify('sb_publishable_test_only')},server:{host:'127.0.0.1',port:0},logLevel:'error'});
 await server.listen();origin=server.resolvedUrls.local[0];browser=await chromium.launch();await mkdir('/tmp/v6-d-auth-screenshots',{recursive:true});
});
after(async()=>{await browser?.close();await server?.close();});
async function fixture(options={}) {
 const context=await browser.newContext({viewport:{width:options.width??1440,height:900}});
 const calls=[], errors=[];let current=options.user??U;
 await context.addInitScript(({AUTH,KEY,initial,selected,verifier})=>{if(!sessionStorage.getItem('fixture-seeded')){sessionStorage.setItem('fixture-seeded','1');if(initial)localStorage.setItem(AUTH,JSON.stringify(initial));if(selected)localStorage.setItem(KEY,selected);if(verifier)localStorage.setItem(`${AUTH}-code-verifier`,JSON.stringify(verifier));}}, {AUTH,KEY,initial:options.signedIn?session(current):null,selected:options.selected,verifier:options.recovery?'verifier/recovery':options.code?'verifier':null});
 await context.route('https://auth-test.supabase.co/**',async route=>{
  const req=route.request(), url=new URL(req.url()), body=req.postDataJSON();calls.push({path:url.pathname,query:url.search,body});
  if(options.delay) await new Promise(r=>setTimeout(r,options.delay));
  if(url.pathname.endsWith('/token')) {
   if(options.bad || options.badCode || options.invalidCode || options.invalidRefresh && url.searchParams.get('grant_type')==='refresh_token') return route.fulfill({status:400,headers:{'x-supabase-api-version':'2024-01-01','access-control-expose-headers':'X-Supabase-Api-Version'},json:{code:options.badCode ?? (options.bad?'invalid_credentials':'refresh_token_not_found'),msg:'PRIVATE_PROVIDER_MESSAGE'}});
   if(body?.email==='bob@example.com') current=V;
   return route.fulfill({json:session(current)});
  }
  if(url.pathname.endsWith('/signup')) return route.fulfill({json:{...session().user,identities:[]}});
  if(url.pathname.endsWith('/recover') || url.pathname.endsWith('/logout')) return route.fulfill({json:{}});
  if(url.pathname.endsWith('/user')) return route.fulfill({json:session(current).user});
  if(url.pathname.endsWith('/authorize')) return route.fulfill({contentType:'text/html',body:'<h1>Google authorization fixture</h1>'});
  return route.fulfill({status:404,json:{}});
 });
 await context.route('**/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname,token=request.headers().authorization;
  calls.push({path,token,method:request.method(),body:request.postDataJSON()});
  const bob=token===`Bearer ${session(V).access_token}`;
  const companies=options.empty?[]:bob?[{company_id:B,name:'Bob workspace',archived:false,accounts:[]}]:[{company_id:A,name:'Alice workspace',archived:!!options.archived,accounts:[]}];
  if(path==='/api/me/companies') {
   if(options.companyDelay)await new Promise(r=>setTimeout(r,options.companyDelay));
   return route.fulfill({json:{companies:options.inaccessible?[]:companies.map(c=>({id:c.company_id,archived_at:c.archived?'2026-01-01':null}))}});
  }
  if(path==='/api/companies' && request.method()==='POST')return route.fulfill({json:{company_id:B,name:request.postDataJSON().name,archived:false,accounts:[]}});
  if(path==='/api/companies')return route.fulfill({json:{companies}});
  if(options.apiStatus && path==='/api/probe')return route.fulfill({status:options.apiStatus,json:{}});
  if(path==='/api/meta/test')return route.fulfill({json:{connected:false}});
  if(path.endsWith('/content'))return route.fulfill({json:{items:[],next_offset:null}});
  if(path.endsWith('/ideas'))return route.fulfill({json:{items:[],next_cursor:null}});
  if(path.endsWith('/profiles'))return route.fulfill({json:{shared:{state:'not_started'},platforms:[]}});
  return route.fulfill({json:{}});
 });
 const page=await context.newPage();page.setDefaultTimeout(6000);page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error' && !m.text().startsWith('Failed to load resource:'))errors.push(m.text());});
 await page.goto(origin+(options.path??''));
 return {page,context,calls,async close(){assert.deepEqual(errors,[]);await context.close();}};
}
async function login(page,email='alice@example.com'){await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill('Strong-password-123');await page.getByRole('button',{name:'Sign in',exact:true}).click();}
const heading=(p,name)=>p.getByRole('heading',{name,exact:true});
test('protected application redirects without revealing company UI',async()=>{const f=await fixture();try{await heading(f.page,'Welcome back').waitFor();assert.equal(new URL(f.page.url()).pathname,'/login');assert.equal(f.calls.some(c=>c.path.startsWith('/api/')),false);}finally{await f.close();}});
test('signup validates confirmation, sends email/password and shows verification required',async()=>{const f=await fixture({path:'signup'});try{const p=f.page;await p.getByLabel('Email',{exact:true}).fill('alice@example.com');await p.getByLabel('Password',{exact:true}).fill('Strong-password-123');await p.getByLabel('Confirm password').fill('Different-password');await p.getByRole('button',{name:'Create account',exact:true}).click();await p.getByText('Passwords do not match.').waitFor();assert.equal(f.calls.some(c=>c.path.endsWith('/signup')),false);await p.getByLabel('Confirm password').fill('Strong-password-123');await p.keyboard.press('Enter');await heading(p,'Check your email').waitFor();assert.match(await p.locator('main').innerText(),/confirmation link/);const call=f.calls.find(c=>c.path.endsWith('/signup'));assert.equal(call.body.email,'alice@example.com');assert.equal(call.body.password,'Strong-password-123');assert.match(call.query,/redirect_to=/);assert.equal(f.calls.some(c=>c.path.startsWith('/api/')),false);}finally{await f.close();}});
test('successful email sign in persists a session and signs application requests',async()=>{const f=await fixture({path:'login'});try{await login(f.page);await heading(f.page,'Overview').waitFor();await f.page.reload();await heading(f.page,'Overview').waitFor();assert.ok(f.calls.filter(c=>c.path.startsWith('/api/')).every(c=>c.token===`Bearer ${session().access_token}`));assert.ok(f.calls.find(c=>c.path==='/api/me/companies'));}finally{await f.close();}});
test('bad credentials show safe associated errors',async()=>{const f=await fixture({path:'login',bad:true});try{await login(f.page);await f.page.getByRole('alert').waitFor();assert.match(await f.page.getByRole('alert').innerText(),/incorrect/);assert.equal(await f.page.getByLabel('Password',{exact:true}).getAttribute('aria-describedby'),'auth-error');assert.doesNotMatch(await f.page.locator('main').innerText(),/PRIVATE_PROVIDER/);}finally{await f.close();}});
test('Google uses Supabase authorize and application callback',async()=>{const f=await fixture({path:'login'});try{await f.page.getByRole('button',{name:'Continue with Google',exact:true}).click();await heading(f.page,'Google authorization fixture').waitFor();const url=new URL(f.page.url());assert.equal(url.searchParams.get('provider'),'google');assert.equal(url.searchParams.get('redirect_to'),`${origin}auth/callback`);assert.ok(url.searchParams.get('code_challenge'));}finally{await f.close();}});
test('PKCE OAuth callback completes and removes the code',async()=>{const f=await fixture({path:'auth/callback?code=one-time-code',code:true});try{await heading(f.page,'Overview').waitFor();assert.equal(new URL(f.page.url()).search,'');assert.ok(f.calls.some(c=>c.query==='?grant_type=pkce'));}finally{await f.close();}});
test('forgot password has safe copy and recovery callback',async()=>{const f=await fixture({path:'forgot-password'});try{await f.page.getByLabel('Email',{exact:true}).fill('unknown@example.com');await f.page.getByRole('button',{name:'Send reset link'}).click();await heading(f.page,'Check your email').waitFor();assert.match(await f.page.locator('main').innerText(),/If an account exists/);assert.match(f.calls.find(c=>c.path.endsWith('/recover')).query,/recovery%3D1/);}finally{await f.close();}});
test('valid recovery session permits password update and success',async()=>{const f=await fixture({path:'auth/callback?recovery=1&code=recovery-code',recovery:true});try{await heading(f.page,'Set a new password').waitFor();assert.equal(new URL(f.page.url()).search,'');await f.page.getByLabel('New password',{exact:true}).fill('Another-password-123');await f.page.getByLabel('Confirm password').fill('Another-password-123');await f.page.getByRole('button',{name:'Update password'}).click();await heading(f.page,'Password updated').waitFor();assert.equal(f.calls.find(c=>c.path.endsWith('/user')).body.password,'Another-password-123');await f.page.getByRole('link',{name:'Continue to workspace'}).click();await heading(f.page,'Overview').waitFor();}finally{await f.close();}});
for(const path of ['auth/callback?recovery=1','auth/callback?error=access_denied#error_description=PRIVATE_TOKEN','auth/callback?recovery=1&code=expired'])test(`invalid recovery is safe: ${path}`,async()=>{const f=await fixture({path,recovery:path.includes('code='),invalidCode:true});try{await heading(f.page,'Link unavailable').waitFor();assert.doesNotMatch(await f.page.locator('main').innerText(),/PRIVATE_TOKEN|expired\s+credentials/);assert.equal(await f.page.getByLabel('New password',{exact:true}).count(),0);assert.equal(new URL(f.page.url()).hash,'');}finally{await f.close();}});
test('session and company loading do not flash protected content',async()=>{const f=await fixture({path:'auth/callback?code=slow',code:true,delay:350,companyDelay:350});try{await f.page.getByRole('status').waitFor();assert.equal(await heading(f.page,'Welcome back').count(),0);assert.equal(await heading(f.page,'Overview').count(),0);await heading(f.page,'Overview').waitFor();}finally{await f.close();}});
for(const state of ['valid','inaccessible','archived','empty'])test(`accessible company startup: ${state}`,async()=>{const f=await fixture({signedIn:true,selected:A,[state]:true});try{await heading(f.page,'Overview').waitFor();if(state==='valid')assert.equal(await f.page.evaluate(key=>localStorage.getItem(key),KEY),A);else{assert.equal(await f.page.evaluate(key=>localStorage.getItem(key),KEY),null);await heading(f.page,'No company selected').waitFor();}assert.ok(f.calls.findIndex(c=>c.path==='/api/me/companies')<f.calls.findIndex(c=>c.path==='/api/companies'));}finally{await f.close();}});
for(const status of [401,403])test(`${status} handling has bounded requests and correct session outcome`,async()=>{const f=await fixture({signedIn:true,apiStatus:status,invalidRefresh:status===401});try{await heading(f.page,'Overview').waitFor();await f.page.evaluate(async()=>{const {apiFetch}=await import('/src/auth/apiFetch.ts');await apiFetch('/api/probe').catch(()=>{});});if(status===401)await heading(f.page,'Welcome back').waitFor();else await heading(f.page,'Overview').waitFor();assert.equal(f.calls.filter(c=>c.path==='/api/probe').length,1);assert.equal(f.calls.filter(c=>c.query==='?grant_type=refresh_token').length,status===401?1:0);}finally{await f.close();}});
test('logout clears selected company and all mounted workspace state before User B',async()=>{const f=await fixture({signedIn:true,selected:A});try{const p=f.page;await heading(p,'Overview').waitFor();await p.locator('nav[aria-label=Primary]').getByRole('link',{name:'Generate',exact:true}).click();await p.getByLabel('Brief (optional)').fill('Alice private draft');await p.getByRole('button',{name:'Sign out',exact:true}).click();await heading(p,'Welcome back').waitFor();assert.equal(await p.evaluate(key=>localStorage.getItem(key),KEY),null);assert.equal(await p.evaluate(key=>localStorage.getItem(key),AUTH),null);await login(p,'bob@example.com');await heading(p,'Overview').waitFor();assert.doesNotMatch(await p.locator('body').innerText(),/Alice workspace|Alice private draft|alice@example.com/);await heading(p,'No company selected').waitFor();assert.equal(await p.evaluate(key=>localStorage.getItem(key),KEY),null);}finally{await f.close();}});
for(const width of [1440,1024,768,390,320])test(`auth routes fit ${width}px and support keyboard forms`,async()=>{const f=await fixture({path:'login',width});try{const p=f.page;for(const [path,title]of [['login','Welcome back'],['signup','Create your account'],['forgot-password','Reset your password']]){await p.goto(origin+path);await heading(p,title).waitFor();assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(await p.locator('vite-error-overlay').count(),0);assert.equal(await p.title(),'ContentMetric');await p.getByLabel('Email',{exact:true}).focus();assert.equal(await p.getByLabel('Email',{exact:true}).evaluate(el=>getComputedStyle(el).outlineStyle),'solid');await p.keyboard.type('alice@example.com');if(path==='login'){await p.keyboard.press('Tab');assert.equal(await p.getByLabel('Password',{exact:true}).evaluate(el=>el===document.activeElement),true);}await p.screenshot({path:`/tmp/v6-d-auth-screenshots/${path}-${width}.png`});}}finally{await f.close();}});

for (const transition of ['identity change', 'logout and login']) test(`${transition} clears generated results, ideas, drafts, content and settings`,async()=>{
 const f=await fixture({signedIn:true,selected:A});const p=f.page;
 const saved={id:B,company_id:A,title:'Alice generated idea',concept:'Alice private concept',script:'Alice private script',status:'draft',feedback:'none',target_platforms:['instagram'],created_at:'2026-09-20T12:00:00Z',updated_at:'2026-09-20T12:00:00Z',publications:[]};
 const destination=async name=>{await p.getByRole('navigation',{name:'Primary',exact:true}).getByRole('link',{name,exact:true}).click();await heading(p,name).waitFor();};
 try {
  await p.route('**/api/companies?*',route=>route.fulfill({json:{companies:route.request().headers().authorization.includes(U)?[{company_id:A,name:'Alice workspace',archived:false,accounts:[{account_id:B,platform:'instagram',display_name:'Alice account'}]}]:[{company_id:B,name:'Bob workspace',archived:false,accounts:[]}]}}));
  await p.route('**/api/companies/*/content?**',route=>route.fulfill({json:{items:[{library_item_id:B,display_title:'Alice content',platform:'instagram',published_at:null,analyzed:true}],next_offset:null}}));
  await p.route('**/api/meta/companies/*/ideas?**',route=>route.fulfill({json:{items:[saved],next_cursor:null}}));
  await p.route(`**/api/meta/companies/${A}/ideas/${B}`,route=>route.fulfill({json:saved}));
  await p.route('**/recommendations',route=>route.fulfill({json:saved}));
  await p.reload();await heading(p,'Overview').waitFor();
  await destination('Content');await p.getByText('Alice content',{exact:true}).waitFor();
  await destination('Generate');await p.getByLabel('Brief (optional)').fill('Alice unsaved brief');await p.getByRole('button',{name:'Generate idea',exact:true}).click();await heading(p,'Alice generated idea').waitFor();
  await destination('Ideas');await p.getByRole('button',{name:saved.title,exact:true}).click();await p.getByRole('button',{name:'Edit',exact:true}).click();await p.getByLabel('Title',{exact:true}).fill('Alice unsaved title');
  await destination('Settings');await p.getByLabel('New company name').fill('Alice unsaved company');
  // Supabase SIGNED_IN can change user without reloading this document (another tab).
  if (transition === 'logout and login') {
   await p.getByRole('button',{name:'Sign out',exact:true}).click();await heading(p,'Welcome back').waitFor();await login(p,'bob@example.com');
  } else await p.evaluate(async()=>{const {authClient}=await import('/src/auth/authClient.ts');await authClient.signIn('bob@example.com','Strong-password-123');});
  await p.getByText('bob@example.com',{exact:true}).waitFor();await destination('Settings');
  assert.equal(await p.evaluate(key=>localStorage.getItem(key),KEY),null);
  assert.equal(await p.getByLabel('New company name').inputValue(),'');
  for(const name of ['Overview','Content','Generate','Ideas','Settings']){
   await destination(name);assert.doesNotMatch(await p.locator('body').textContent(),/Alice (content|private|generated|unsaved|workspace|account)/);
  }
  assert.equal(await p.getByLabel('Title',{exact:true}).count(),0);
 }finally{await f.close();}
});

test('API retries a rejected read once, never repeats mutations, retains idempotency and cancellation',async()=>{
 const f=await fixture({signedIn:true});try{
  await heading(f.page,'Overview').waitFor();let gets=0,posts=0;
  await f.page.route('**/api/retry-probe',route=>{const request=route.request();if(request.method()==='POST'){posts++;assert.equal(request.headers()['idempotency-key'],'stable-key');return route.fulfill({status:401,json:{}});}return route.fulfill({status:++gets===1?401:200,json:{}});});
  const statuses=await f.page.evaluate(async()=>{const {apiFetch}=await import('/src/auth/apiFetch.ts');return [(await apiFetch('/api/retry-probe')).status,(await apiFetch('/api/retry-probe',{method:'POST',headers:{'Idempotency-Key':'stable-key'},body:'payload'})).status];});
  assert.deepEqual(statuses,[200,401]);assert.equal(gets,2);assert.equal(posts,1);
  assert.equal(await f.page.evaluate(async()=>{const {apiFetch}=await import('/src/auth/apiFetch.ts');const c=new AbortController();c.abort();try{await apiFetch('/api/cancelled',{signal:c.signal});return false;}catch(e){return e.name==='AbortError';}}),true);
  assert.equal(f.calls.some(c=>c.path==='/api/cancelled'),false);
  assert.equal(await f.page.evaluate(async()=>{const {apiFetch}=await import('/src/auth/apiFetch.ts');try{await apiFetch('https://foreign.invalid/api/private');return false;}catch{return true;}}),true);
 }finally{await f.close();}
});

test('unverified email gets verification guidance',async()=>{const f=await fixture({path:'login',badCode:'email_not_confirmed'});try{await login(f.page);await f.page.getByText('Please verify your email before signing in.').waitFor();}finally{await f.close();}});
test('new user creates a company without connecting Meta',async()=>{const f=await fixture({signedIn:true,empty:true});try{const p=f.page;await heading(p,'No company selected').waitFor();await p.getByRole('button',{name:'Manage companies',exact:true}).click();await p.getByLabel('New company name').fill('New workspace');await p.getByRole('button',{name:'Create company',exact:true}).click();await p.getByRole('navigation',{name:'Company',exact:true}).getByRole('button',{name:'New workspace',exact:true}).waitFor();assert.ok(f.calls.some(c=>c.path==='/api/companies'&&c.method==='POST'&&c.body.name==='New workspace'&&c.token));assert.equal(f.calls.some(c=>c.path==='/api/meta/connect'),false);}finally{await f.close();}});
test('recovery query alone cannot turn an ordinary session into password recovery',async()=>{const f=await fixture({signedIn:true,path:'auth/callback?recovery=1'});try{await heading(f.page,'Link unavailable').waitFor();assert.equal(await f.page.getByLabel('New password',{exact:true}).count(),0);}finally{await f.close();}});

for(const width of [1440,1024,768,390,320])test(`password recovery fits ${width}px and keyboard submits`,async()=>{
 const f=await fixture({path:'auth/callback?recovery=1&code=recovery-code',recovery:true,width});try{const p=f.page;await heading(p,'Set a new password').waitFor();assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await p.getByLabel('New password',{exact:true}).focus();await p.keyboard.type('Keyboard-password-123');await p.keyboard.press('Tab');await p.keyboard.type('Keyboard-password-123');await p.screenshot({path:`/tmp/v6-d-auth-screenshots/reset-${width}.png`});await p.keyboard.press('Enter');await heading(p,'Password updated').waitFor();assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}finally{await f.close();}
});

test('sign-out failure locks private UI and offers retry',async()=>{
 const f=await fixture({signedIn:true,selected:A});try{const p=f.page;await heading(p,'Overview').waitFor();await p.route('https://auth-test.supabase.co/auth/v1/logout*',r=>r.fulfill({status:500,json:{msg:'offline'}}));await p.getByRole('button',{name:'Sign out',exact:true}).click();await heading(p,'Finish signing out').waitFor();assert.doesNotMatch(await p.locator('body').textContent(),/Alice workspace|alice@example.com/);await p.unroute('https://auth-test.supabase.co/auth/v1/logout*');await p.getByRole('button',{name:'Sign out',exact:true}).click();await heading(p,'Welcome back').waitFor();}finally{await f.close();}
});
