import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { createServer } from 'vite';
let server, api;
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const wire = () => ({ id: id(3), company_id: id(1), title: 'Title', concept: 'Concept', script: 'Script', status: 'draft', feedback: 'none', feedback_reason: null, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z', target_platforms: ['facebook'], publications: [], generation_brief: 'Brief', profile_evidence: 'secret', request_hash: 'secret' });
before(async () => { server = await createServer({ logLevel: 'error' }); api = await server.ssrLoadModule('/src/ideas/ideaApi.ts'); });
after(async () => server?.close());
test('safe detail allowlist excludes evidence and request internals', () => { const parsed = api.parseIdea(wire(), id(1)); assert.equal(JSON.stringify(parsed).includes('secret'), false); assert.equal(parsed.brief, 'Brief'); });
test('foreign-company detail is rejected', () => assert.throws(() => api.parseIdea(wire(), id(2))));
test('invalid lifecycle, identifier and date rejected', () => { for (const bad of [{ status: 'complete' }, { id: 'provider-id' }, { created_at: 'bad' }]) assert.throws(() => api.parseIdea({ ...wire(), ...bad }, id(1))); });
test('reason survives only for disliked feedback', () => { for (const feedback of ['none', 'liked', 'disliked']) assert.equal(api.parseIdea({ ...wire(), feedback, feedback_reason: 'Reason' }, id(1)).reason, feedback === 'disliked' ? 'Reason' : null); });
test('historical association requires no live content metadata', () => { const p = api.parsePublication({ library_item_id: id(7), created_at: '2026-09-01T00:00:00Z' }); assert.equal(p.available, null); assert.equal(p.title, 'Linked published content'); });
test('all history filters and cursor are encoded; dates include entire UTC day', () => { const q = new URLSearchParams(api.historyQuery({ search: ' hello & world ', status: 'used', feedback: 'liked', platform: 'facebook', from: '2026-09-01', to: '2026-09-02' }, id(8))); assert.deepEqual(Object.fromEntries(q), { limit: '25', search: 'hello & world', status: 'used', feedback: 'liked', target_platform: 'facebook', created_from: '2026-09-01T00:00:00.000Z', created_to: '2026-09-03T00:00:00.000Z', after: id(8) }); });
test('feedback adapter clears reason and never sends internal fields', async () => { const original = globalThis.fetch; const calls = []; globalThis.fetch = async (url, options) => { calls.push({ url, ...options }); return new Response(JSON.stringify(wire())); }; try { await api.ideaApi.feedback(id(1), id(3), 'liked', 'old reason', new AbortController().signal); assert.deepEqual(JSON.parse(calls[0].body), { feedback: 'liked', reason: null }); assert.equal(calls[0].credentials, 'same-origin'); assert.equal(calls[0].cache, 'no-store'); } finally { globalThis.fetch = original; } });
test('publication picker uses exact backend option projection and cursor without invented search',async()=>{
  const original=globalThis.fetch; const calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url,...options});return new Response(JSON.stringify({items:[{id:id(7),label:'Published post',platform:'instagram',content_type:'reel',published_at:'2026-09-01T00:00:00Z'}],next_cursor:id(7)}));};
  try {const result=await api.ideaApi.publications(id(1),id(8),new AbortController().signal);assert.equal(calls[0].url,`/api/meta/companies/${id(1)}/publication-options?limit=25&after=${id(8)}`);assert.equal(result.items[0].id,id(7));assert.equal(result.items[0].title,'Published post');assert.equal(result.items[0].available,true);}finally{globalThis.fetch=original;}
});
