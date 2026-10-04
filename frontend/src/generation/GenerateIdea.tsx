import { ArrowRight, Check, FileVideo, Sparkles } from 'lucide-react';
import { Button, Checkbox, Input, Select, Textarea } from '../ui/controls';
import { Alert, Badge, EmptyState, LoadingState } from '../ui/layout';
import './generate.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { CompanyScopeBoundary, useCompany, useCompanyQuery, useCompanyStore } from '../company/CompanyProvider';
import { useCompanySwitchGuard } from '../CompanySwitchGuard';
import { generationApi, generationError, latestSources, type GenerationApi, type PersistedIdea, type TargetPlatform } from './generationApi';
import { PlanLimitError } from '../billing/billingApi';
import { useBilling } from '../billing/BillingProvider';
import { LimitNotice } from '../billing/BillingUI';

export function GenerateIdea({ onSetup, onSaved, api = generationApi, refreshToken = 0 }: { onSetup(): void; onSaved?(): void; api?: GenerationApi; refreshToken?: number }) {
  return <CompanyScopeBoundary fallback={<EmptyState title="Select a company to generate an idea" action={<Button onClick={onSetup}>Company setup</Button>}><p>Select or create a company to use its analysed content.</p></EmptyState>}>
    <Workflow api={api} onSetup={onSetup} onSaved={onSaved} refreshToken={refreshToken} />
  </CompanyScopeBoundary>;
}
function Workflow({ api, onSetup, onSaved, refreshToken }: { api: GenerationApi; onSetup(): void; onSaved?(): void; refreshToken: number }) {
  const { activeCompany } = useCompany();
  const billing = useBilling();
  const store = useCompanyStore();
  const [revision, revise] = useState(0);
  const [mode, setMode] = useState<'all' | 'manual'>('all');
  const load = useCallback((id: string, signal: AbortSignal) => api.listSources(id, signal, mode === 'manual'), [api, mode]);
  const sources = useCompanyQuery(`generation-sources:${revision}:${mode}:${refreshToken}`, load);
  const [selection, select] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [platform, setPlatform] = useState('all');
  const available = [...new Set((activeCompany?.accounts ?? []).map(a => a.platform).filter((p): p is TargetPlatform => p === 'instagram' || p === 'facebook'))];
  const [targets, setTargets] = useState<TargetPlatform[]>(available);
  const hadPublishingAccount = useRef(available.length > 0);
  useEffect(() => {
    if (!hadPublishingAccount.current && available.length) setTargets(available);
    hadPublishingAccount.current = available.length > 0;
  }, [available.join(',')]);
  const [brief, setBrief] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [limit, setLimit] = useState(false);
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
  const missingSelection = mode === 'manual' && sources.status === 'success' ? selection.filter(id => !items.some(i => i.id === id)) : [];
  const chosenTargets = targets.filter(t => available.includes(t));
  const visible = items.filter(i => (platform === 'all' || i.platform === platform) && i.title.toLowerCase().includes(search.toLowerCase()));
  const quotaReached = billing.state.data && billing.state.data.usage.idea_generations >= billing.state.data.entitlements.idea_generation_limit;
  async function generate() {
    if (lock.current || sources.status !== 'success' || !sourceIds.length || sourceIds.length > 20 || missingSelection.length > 0 || !chosenTargets.length) return;
    const scope = store.captureScope();
    if (!scope) return;
    lock.current = true; setBusy(true); setError(''); setLimit(false);
    const input = { companyId: scope.companyId, sourceIds, brief: brief.trim() || undefined, targetPlatforms: chosenTargets };
    const fingerprint = JSON.stringify(input);
    if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: crypto.randomUUID() };
    const signal = AbortSignal.any([scope.signal, lifetime.current.signal]);
    try {
      const saved = await api.generate({ ...input, idempotencyKey: attempt.current.key }, signal);
      if (!signal.aborted && scope.isCurrent()) { setResult(saved); attempt.current = undefined; onSaved?.(); }
    } catch (caught) {
      if (!signal.aborted && scope.isCurrent()) { if (caught instanceof PlanLimitError && caught.code === 'idea_generation_limit_reached') { setLimit(true); billing.refresh(); } else setError(generationError(caught)); void store.handleScopeError(scope, caught); }
    } finally {
      if (!signal.aborted && scope.isCurrent()) { lock.current = false; setBusy(false); }
    }
  }
  return <div className="generate-workspace">
    <section className="generation" aria-labelledby="generate-heading">
      <header className="generate-intro"><h2 id="generate-heading">Generate an idea</h2><p>Use your analysed content to create a new concept.</p></header>
      {sources.status === 'loading' && <LoadingState label="Loading analysed source content…" />}
      {sources.status === 'error' && <Alert tone="danger"><p>{generationError(sources.error)}</p><Button onClick={() => revise(v => v + 1)}>Retry sources</Button></Alert>}
      {sources.status === 'success' && !items.length && <EmptyState title="Analyze some content first" action={<a className="generate-prerequisite-link" href="#content">Go to Content <ArrowRight size={16} aria-hidden="true" /></a>}><p>ContentMetric uses your analyzed content as evidence when creating new ideas. Check Content to see what is available and its analysis status.</p></EmptyState>}
      {sources.status === 'success' && items.length > 0 && <form onSubmit={e => { e.preventDefault(); void generate(); }} aria-busy={busy}>
        <fieldset className="generate-step" disabled={busy || sources.status !== 'success' || !items.length} aria-describedby="source-help source-count source-validation">
          <legend>Sources</legend>
          <p id="source-help">Start with what you already know. Choose the content that will inform your idea.</p>
          <div className="generate-modes">
            <label><input type="radio" name="source-mode" checked={mode === 'all'} onChange={() => setMode('all')} /><span>Latest analysed content</span></label>
            <label><input type="radio" name="source-mode" checked={mode === 'manual'} onChange={() => setMode('manual')} /><span>Choose manually</span></label>
          </div>
          {mode === 'all' ? <div className="generate-source-summary"><FileVideo aria-hidden="true" size={24} /><div><strong>Use my latest analysed content</strong><p>Up to the latest 20 analysed items accessible to {activeCompany?.name}.</p></div></div> : <div className="generate-picker">
            <div className="generation-filters"><label htmlFor="generate-search">Search analysed content<Input id="generate-search" type="search" placeholder="Search by title" value={search} onChange={e => setSearch(e.target.value)} /></label>
              <label htmlFor="generate-platform">Source platform<Select id="generate-platform" value={platform} onChange={e => setPlatform(e.target.value)}><option value="all">All platforms</option>{[...new Set(items.map(i => i.platform))].map(p => <option value={p} key={p}>{p === 'meta_ads' ? 'Meta Ads (source)' : p === 'instagram' ? 'Instagram' : 'Facebook'}</option>)}</Select></label></div>
            <p id="selection-help">Select 1–20 items. Selections are kept while filtering.</p>
            {!visible.length && <p>No analysed content matches your search or platform filter.</p>}
            <div className="generation-sources" role="group" aria-label="Analysed content" aria-describedby="selection-help source-count source-validation">{visible.map(item => <label className="generate-source" key={item.id}>
              <input type="checkbox" checked={sourceIds.includes(item.id)} aria-describedby="source-validation" disabled={!sourceIds.includes(item.id) && sourceIds.length >= 20} onChange={e => select(current => e.target.checked ? current.length < 20 ? [...current, item.id] : current : current.filter(id => id !== item.id))} />
              <span className="generate-source-icon"><FileVideo aria-hidden="true" size={20} /></span>
              <span className="generate-source-label"><strong>{item.title}</strong><small>{item.platform === 'meta_ads' ? 'Meta Ads' : item.platform === 'instagram' ? 'Instagram' : 'Facebook'} · {item.publishedAt ? new Date(item.publishedAt).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'Date unavailable'}<span className="generate-analysis">Analysed</span></small></span>
            </label>)}</div>
          </div>}
          {missingSelection.length > 0 && <Alert tone="danger"><p>{missingSelection.length} selected {missingSelection.length === 1 ? 'source is' : 'sources are'} no longer available.</p><p>Review your sources before generating. Your other selections have been kept.</p><Button onClick={() => select(current => current.filter(id => !missingSelection.includes(id)))}>Remove unavailable selection</Button></Alert>}
          <p role="status" id="source-count" className="generation-count">Using {sourceIds.length} source {sourceIds.length === 1 ? 'item' : 'items'}{mode === 'manual' ? ' (maximum 20)' : ' — latest available, up to 20'}.</p>
          <p id="source-validation" className="generate-validation" role="status">{mode === 'manual' && (!sourceIds.length ? 'Select at least one analysed source item.' : sourceIds.length >= 20 ? 'Maximum 20 selected. Deselect an item to choose another.' : '')}</p>
        </fieldset>
        <fieldset className="generate-step" disabled={busy} aria-describedby="target-help target-validation">
          <legend>Target platforms</legend><p id="target-help">Where do you want to publish this idea?</p>
          <div className="generate-targets">{(['instagram', 'facebook'] as const).map(p => <Checkbox key={p} label={p === 'instagram' ? 'Instagram' : 'Facebook'} disabled={!available.includes(p)} checked={chosenTargets.includes(p)} aria-describedby="target-validation" onChange={e => setTargets(current => e.target.checked ? [...current, p] : current.filter(t => t !== p))} />)}</div>
          <div id="target-validation" role="status">{!available.length ? <p>{activeCompany?.role === 'owner' ? <>No linked publishing platforms. Link Instagram or Facebook in company setup. <Button onClick={onSetup}>Company setup</Button></> : 'Ask a company owner to link Instagram or Facebook before generating ideas.'}</p> : !chosenTargets.length ? <p className="generate-validation">Select at least one target platform.</p> : available.length < 2 && activeCompany?.role === 'owner' ? <p className="generate-help">Link another publishing platform in <a href="#settings">Settings</a> to use it here.</p> : null}</div>
        </fieldset>
        <div className="generate-step generate-brief"><label htmlFor="generate-brief">Brief (optional)</label><p id="brief-help">What do you want this idea to focus on? Share a goal, audience or message.</p><Textarea id="generate-brief" disabled={busy} aria-describedby="brief-help" rows={3} maxLength={10000} placeholder="For example, help homeowners prepare for winter." value={brief} onChange={e => setBrief(e.target.value)} /></div>
        {error && <Alert tone="danger"><p>{error}</p><Button disabled={busy} onClick={() => { setError(''); revise(v => v + 1); }}>Reload sources</Button></Alert>}
        {(limit || quotaReached) && <LimitNotice code="idea_generation_limit_reached" billing={billing.state.data} onUpgrade={() => { window.location.hash = 'settings'; }} />}
        <div className="generate-action"><Button variant="primary" type="submit" disabled={busy || sources.status !== 'success' || !sourceIds.length || sourceIds.length > 20 || missingSelection.length > 0 || !chosenTargets.length}><Sparkles size={18} aria-hidden="true" />{busy ? 'Generating…' : 'Generate idea'}</Button><p>One idea, saved to your company’s Ideas.</p></div>
      </form>}
        {busy && <Alert><strong>Generating and saving your idea. This may take a moment.</strong><p>We’re using your selected content and brief. You can stay here while your idea is prepared.</p></Alert>}
    </section>
    {result && <article className="idea-result generate-document" aria-labelledby="generated-title"><header><div className="generate-document-meta"><Badge tone="success"><Check aria-hidden="true" size={14} /> Saved idea</Badge><span>{result.targetPlatforms.map(p => p === 'instagram' ? 'Instagram' : 'Facebook').join(' · ')}</span></div><h2 id="generated-title" ref={resultHeading} tabIndex={-1}>{result.title}</h2><p>Saved to {activeCompany?.name}’s Ideas. Ready to review and develop.</p></header><div className="generate-document-body"><h3>Concept</h3><p className="concept">{result.concept}</p><h3>Script</h3><div className="script">{result.script}</div></div><footer><a href="#ideas">View in Ideas <ArrowRight size={16} aria-hidden="true" /></a></footer></article>}
  </div>;
}
