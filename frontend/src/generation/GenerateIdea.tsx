import { useCallback, useEffect, useRef, useState } from 'react';
import { CompanyScopeBoundary, useCompany, useCompanyQuery, useCompanyStore } from '../company/CompanyProvider';
import { useCompanySwitchGuard } from '../CompanySwitchGuard';
import { generationApi, generationError, latestSources, type GenerationApi, type PersistedIdea, type TargetPlatform } from './generationApi';

export function GenerateIdea({ onSetup, onSaved, api = generationApi }: { onSetup(): void; onSaved?(): void; api?: GenerationApi }) {
  return <CompanyScopeBoundary fallback={<section><h2>Select a company to generate an idea</h2><p>Select or create a company in the app shell.</p><button onClick={onSetup}>Company setup</button></section>}>
    <Workflow api={api} onSetup={onSetup} onSaved={onSaved} />
  </CompanyScopeBoundary>;
}
function Workflow({ api, onSetup, onSaved }: { api: GenerationApi; onSetup(): void; onSaved?(): void }) {
  const { activeCompany } = useCompany();
  const store = useCompanyStore();
  const [revision, revise] = useState(0);
  const [mode, setMode] = useState<'all' | 'manual'>('all');
  const load = useCallback((id: string, signal: AbortSignal) => api.listSources(id, signal, mode === 'manual'), [api, mode]);
  const sources = useCompanyQuery(`generation-sources:${revision}:${mode}`, load);
  const [selection, select] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [platform, setPlatform] = useState('all');
  const available = [...new Set((activeCompany?.accounts ?? []).map(a => a.platform).filter((p): p is TargetPlatform => p === 'instagram' || p === 'facebook'))];
  const [targets, setTargets] = useState<TargetPlatform[]>(available);
  const [brief, setBrief] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<PersistedIdea>();
  const lock = useRef(false);
  const attempt = useRef<{ fingerprint: string; key: string } | undefined>(undefined);
  const lifetime = useRef(new AbortController());
  const resultHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  useEffect(() => { if (result) resultHeading.current?.focus(); }, [result]);
  useCompanySwitchGuard({ generationInProgress: busy });
  const items = sources.data ?? [];
  const sourceIds = mode === 'all' ? latestSources(items).map(i => i.id) : selection.filter(id => items.some(i => i.id === id));
  const chosenTargets = targets.filter(t => available.includes(t));
  const visible = items.filter(i => (platform === 'all' || i.platform === platform) && i.title.toLowerCase().includes(search.toLowerCase()));
  async function generate() {
    if (lock.current || sources.status !== 'success' || !sourceIds.length || !chosenTargets.length) return;
    const scope = store.captureScope();
    if (!scope) return;
    lock.current = true; setBusy(true); setError('');
    const input = { companyId: scope.companyId, sourceIds, brief: brief.trim() || undefined, targetPlatforms: chosenTargets };
    const fingerprint = JSON.stringify(input);
    if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: crypto.randomUUID() };
    const signal = AbortSignal.any([scope.signal, lifetime.current.signal]);
    try {
      const saved = await api.generate({ ...input, idempotencyKey: attempt.current.key }, signal);
      if (!signal.aborted && scope.isCurrent()) { setResult(saved); attempt.current = undefined; onSaved?.(); }
    } catch (caught) {
      if (!signal.aborted && scope.isCurrent()) { setError(generationError(caught)); void store.handleScopeError(scope, caught); }
    } finally {
      if (!signal.aborted && scope.isCurrent()) { lock.current = false; setBusy(false); }
    }
  }
  return <>
    <section className="generation" aria-labelledby="generate-heading">
      <p className="eyebrow">{activeCompany?.name}</p><h2 id="generate-heading">Generate Idea</h2>
      <p>Build a new idea from analyzed content in this company.</p>
      {sources.status === 'loading' && <p role="status">Loading analyzed source content…</p>}
      {sources.status === 'error' && <div role="alert"><p>{generationError(sources.error)}</p><button onClick={() => revise(v => v + 1)}>Retry sources</button></div>}
      {sources.status === 'success' && !items.length && <div><h3>No analyzed source content available</h3><p>Link accounts and analyze content for this company before generating an idea.</p><button onClick={onSetup}>Company and account setup</button></div>}
      <form onSubmit={e => { e.preventDefault(); void generate(); }}>
        <fieldset disabled={busy || sources.status !== 'success' || !items.length}>
          <legend>Content source</legend>
          <label className="source-choice"><input type="radio" name="source-mode" checked={mode === 'all'} onChange={() => setMode('all')} />All analyzed content</label>
          <p className="muted">Uses the 20 most recent analyzed items accessible to this company, or all available if fewer than 20.</p>
          <label className="source-choice"><input type="radio" name="source-mode" checked={mode === 'manual'} onChange={() => setMode('manual')} />Choose manually</label>
          {mode === 'manual' && <div>
            <div className="generation-filters"><label>Search analyzed content<input type="search" value={search} onChange={e => setSearch(e.target.value)} /></label>
              <label>Source platform<select value={platform} onChange={e => setPlatform(e.target.value)}><option value="all">All platforms</option>{[...new Set(items.map(i => i.platform))].map(p => <option value={p} key={p}>{p === 'meta_ads' ? 'Meta Ads (source)' : p === 'instagram' ? 'Instagram' : 'Facebook'}</option>)}</select></label></div>
            <p className="muted">Select 1–20 items. {sourceIds.length === 20 ? 'Maximum 20 selected. Deselect an item to choose another.' : 'Selections are kept while filtering.'}</p>
            {!visible.length && <p>No analyzed content matches your search or platform filter.</p>}
            <div className="generation-sources">{visible.map(item => <label className="source-choice" key={item.id}>
              <input type="checkbox" checked={sourceIds.includes(item.id)} disabled={!sourceIds.includes(item.id) && sourceIds.length >= 20} onChange={e => select(current => e.target.checked ? current.length < 20 ? [...current, item.id] : current : current.filter(id => id !== item.id))} />
              <span>{item.title}<small>{item.platform === 'meta_ads' ? 'Meta Ads' : item.platform} · {item.publishedAt ? new Date(item.publishedAt).toLocaleDateString() : 'Date unavailable'}</small></span>
            </label>)}</div>
          </div>}
        </fieldset>
        <p role="status" className="generation-count">Using {sourceIds.length} source {sourceIds.length === 1 ? 'item' : 'items'}{mode === 'manual' ? ' (maximum 20)' : ' — latest available, up to 20'}.</p>
        <fieldset disabled={busy}>
          <legend>Brief and publishing targets</legend>
          <label className="generation-brief">Brief (optional)<textarea rows={4} maxLength={10000} placeholder="Make something aimed at homeowners before winter" value={brief} onChange={e => setBrief(e.target.value)} /></label>
          <p>Target platforms</p>
          {available.map(p => <label className="source-choice" key={p}><input type="checkbox" checked={targets.includes(p)} onChange={e => setTargets(current => e.target.checked ? [...current, p] : current.filter(t => t !== p))} />{p === 'instagram' ? 'Instagram' : 'Facebook'}</label>)}
          {!available.length ? <p>No linked publishing platforms. Link Instagram or Facebook in company setup. <button type="button" onClick={onSetup}>Company setup</button></p> : !chosenTargets.length && <p>Select at least one target platform.</p>}
        </fieldset>
        {mode === 'manual' && !sourceIds.length && <p>Select at least one analyzed source item.</p>}
        {error && <div className="notice error"><p role="alert">{error}</p><button type="button" disabled={busy} onClick={() => { select([]); setError(''); revise(v => v + 1); }}>Reload sources</button></div>}
        <button className="primary" type="submit" disabled={busy || sources.status !== 'success' || !sourceIds.length || !chosenTargets.length}>{busy ? 'Generating…' : 'Generate idea'}</button>
        {busy && <p role="status">Generating and saving your idea. This may take a moment.</p>}
      </form>
    </section>
    {result && <section className="idea-result" aria-labelledby="generated-title"><p className="eyebrow">Saved idea</p><h2 id="generated-title" ref={resultHeading} tabIndex={-1}>{result.title}</h2><h3>Concept</h3><p className="concept">{result.concept}</p><h3>Script</h3><div className="script">{result.script}</div><h3>Target platforms</h3><p>{result.targetPlatforms.map(p => p === 'instagram' ? 'Instagram' : 'Facebook').join(', ')}</p></section>}
  </>;
}
