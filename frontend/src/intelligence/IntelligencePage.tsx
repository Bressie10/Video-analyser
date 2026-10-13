import { useEffect, useRef, useState, type FormEvent } from 'react';
import { apiFetch } from '../auth/apiFetch';
import { CompanyScopeBoundary, useCompany, useCompanyStore } from '../company/CompanyProvider';
import { isUUID, ServiceError } from '../metaLibrary';
import { Button, Input, Select } from '../ui/controls';
import { Alert, Badge, LoadingState, PageLayout, Panel, SectionHeader } from '../ui/layout';
import './intelligence.css';

type Metric = 'ctr' | 'cpc' | 'cpm' | 'impressions';
type Citation = { video_ref: string; evidence_ref: string; evidence_type: string; timestamp_seconds: number; excerpt?: string };
type Difference = { description: string; higher_group_support: number; lower_group_support: number; higher_group_size: number; lower_group_size: number; confidence: string; evidence_refs: Citation[]; counterexamples: Citation[]; timing?: { higher_median_seconds: number; lower_median_seconds: number; relation: string } | null };
type Hypothesis = { hypothesis: string; variable_to_test: string; control_condition: string; variant_condition: string; primary_metric: Metric; what_to_hold_constant: string[]; limitations: string[]; counterevidence: Citation[]; source_difference: string };
type IntelligenceResult = {
  metric: { description: string; unit?: string };
  cohort: { date_start: string; date_stop: string; distinct_ads?: number; peer_count: number; currency?: string };
  performance: null | { summary: string; notable_metrics: { observation: string }[]; metric_facts: { target_value: string; median: string; ratio: string | null; percentile: number; description: string }; limitations: string[] };
  content_differences: Difference[];
  hypotheses: Hypothesis[];
  abstentions: string[];
};
const metrics: { id: Metric; label: string }[] = [
  { id: 'ctr', label: 'CTR' }, { id: 'cpc', label: 'CPC' },
  { id: 'cpm', label: 'CPM' }, { id: 'impressions', label: 'Impressions' },
];

async function runIntelligence(companyId: string, accountId: string, metricId: Metric, start: string, stop: string, signal: AbortSignal): Promise<IntelligenceResult> {
  if (!isUUID(companyId) || !isUUID(accountId)) throw new ServiceError(422, 'Invalid selection');
  const response = await apiFetch(`/api/companies/${encodeURIComponent(companyId)}/intelligence`, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store', signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_id: accountId, metric_id: metricId, date_start: start, date_stop: stop }),
  });
  if (!response.ok) throw new ServiceError(response.status, 'Intelligence request failed');
  const result: unknown = await response.json();
  if (!result || typeof result !== 'object' || !('cohort' in result) || !('metric' in result) ||
      !('abstentions' in result) || !Array.isArray(result.abstentions) ||
      !('content_differences' in result) || !Array.isArray(result.content_differences) ||
      !('hypotheses' in result) || !Array.isArray(result.hypotheses) ||
      !result.cohort || typeof result.cohort !== 'object' ||
      !('date_start' in result.cohort) || typeof result.cohort.date_start !== 'string' ||
      !('date_stop' in result.cohort) || typeof result.cohort.date_stop !== 'string' ||
      !result.metric || typeof result.metric !== 'object' ||
      !('description' in result.metric) || typeof result.metric.description !== 'string' ||
      !('performance' in result) || (result.performance !== null &&
        (!result.performance || typeof result.performance !== 'object' ||
         !('summary' in result.performance) || typeof result.performance.summary !== 'string')))
    throw new ServiceError(502, 'Invalid response');
  return result as IntelligenceResult;
}

function errorText(error: unknown) {
  if (error instanceof ServiceError) {
    if (error.status === 401) return 'Your session has expired. Please sign in again.';
    if (error.status === 403 || error.status === 404) return 'This company or Ads account is no longer available. Refresh your workspace.';
    if (error.status === 422) return 'Check the reporting dates and selected metric, then try again.';
  }
  return 'Creative Intelligence is unavailable right now. Please try again.';
}

function Evidence({ rows, label }: { rows: Citation[]; label: string }) {
  if (!rows.length) return null;
  return <div className="intelligence-evidence"><strong>{label}</strong><ul>{rows.map(row => <li key={`${row.video_ref}:${row.evidence_ref}`}>
    <span>{row.video_ref} · {row.evidence_type} · {row.timestamp_seconds}s</span>
    {row.excerpt && <q>{row.excerpt}</q>}
    <small>{row.evidence_ref}</small>
  </li>)}</ul></div>;
}

function Result({ result, selectedMetric }: { result: IntelligenceResult; selectedMetric: Metric }) {
  const noCohort = result.abstentions.some(item => ['insufficient_historical_cohort', 'insufficient_or_mixed_report_context', 'content_group_unavailable'].includes(item));
  const disconnected = result.abstentions.includes('meta_disconnected');
  const mediaUnavailable = result.abstentions.includes('source_media_unavailable');
  const modelUnavailable = result.abstentions.some(item => item.includes('model_or_validation_failed'));
  const facts = result.performance?.metric_facts;
  return <div className="intelligence-results" aria-label="Creative Intelligence result">
    <Panel><SectionHeader title="Performance" />
      <p><strong>{metrics.find(item => item.id === selectedMetric)?.label}</strong> ({result.metric.description}; {result.metric.unit}) · {result.cohort.date_start} to {result.cohort.date_stop}
        {result.cohort.distinct_ads !== undefined ? ` · ${result.cohort.distinct_ads} ads` : ''}
        {result.performance ? ` · ${result.cohort.peer_count} peers` : ''}
        {result.cohort.currency ? ` · ${result.cohort.currency}` : ''}</p>
      {result.performance ? <><p>{result.performance.summary}</p>
        {facts && <dl className="intelligence-facts"><div><dt>Reference ad value</dt><dd>{facts.target_value}</dd></div><div><dt>Cohort median</dt><dd>{facts.median}</dd></div><div><dt>Ratio to median</dt><dd>{facts.ratio ?? 'Unavailable'}</dd></div><div><dt>Percentile</dt><dd>{facts.percentile}</dd></div></dl>}
        {result.performance.notable_metrics.map((item, index) => <p key={index}>{item.observation}</p>)}</>
        : disconnected ? <Alert><p>Meta is disconnected. Reconnect it in <a href="#settings">Settings</a> to run this comparison.</p></Alert>
        : noCohort ? <Alert><p>ContentMetric needs more comparable ads in this exact reporting context and date window.</p></Alert>
        : <Alert><p>Comparable performance observations are unavailable for this exact reporting context.</p></Alert>}
    </Panel>
    {result.performance && <><Panel><SectionHeader title="What differed" description="Observed difference — not proven cause. Confidence reflects evidence coverage." />
      {result.content_differences.length ? result.content_differences.map((item, index) => <article className="intelligence-item" key={index}>
        <h3>{item.description}</h3><p><Badge>{item.confidence} coverage</Badge> Higher group {item.higher_group_support}/{item.higher_group_size} · Lower group {item.lower_group_support}/{item.lower_group_size}</p>
        {item.timing && <p>Median cited time: higher {item.timing.higher_median_seconds}s · lower {item.timing.lower_median_seconds}s</p>}
        <Evidence rows={item.evidence_refs} label="Supporting evidence" /><Evidence rows={item.counterexamples} label="Counterexamples" />
      </article>) : <p>{mediaUnavailable ? 'Source media could not be accessed. Performance is available, but creative comparison could not be performed.'
        : modelUnavailable ? 'Creative comparison could not be completed right now. Performance remains available.'
        : 'There isn’t enough analyzed video evidence yet to compare creative differences.'}</p>}
    </Panel>
    {result.content_differences.length > 0 && <Panel><SectionHeader title="What to test next" />{result.hypotheses.length ? result.hypotheses.map((item, index) => <article className="intelligence-item" key={index}>
      <Badge tone="info">Experiment to try</Badge><h3>{item.hypothesis}</h3>
      <dl className="intelligence-experiment"><div><dt>Variable</dt><dd>{item.variable_to_test}</dd></div><div><dt>Control</dt><dd>{item.control_condition}</dd></div><div><dt>Variant</dt><dd>{item.variant_condition}</dd></div><div><dt>Metric to watch</dt><dd>{metrics.find(metric => metric.id === item.primary_metric)?.label}</dd></div><div><dt>Keep as similar as practical</dt><dd>{item.what_to_hold_constant.join(', ')}</dd></div></dl>
      <p>Underlying observation: {item.source_difference}</p>
      <Evidence rows={item.counterevidence} label="Counterevidence" />
      {item.limitations.map((limit, i) => <p className="intelligence-limitation" key={i}>{limit}</p>)}
    </article>) : <p>{result.abstentions.includes('hypothesis_model_or_validation_failed') ? 'Experiments could not be prepared right now.' : 'No testable experiment was returned for these observations.'}</p>}</Panel>}
    </>}
  </div>;
}

export function IntelligencePage() {
  return <CompanyScopeBoundary><IntelligenceWorkspace /></CompanyScopeBoundary>;
}

function IntelligenceWorkspace() {
  const store = useCompanyStore();
  const { activeCompany } = useCompany();
  const accounts = activeCompany?.accounts.filter(account => account.platform === 'meta_ads') ?? [];
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? '');
  const [metric, setMetric] = useState<Metric>('ctr');
  const [start, setStart] = useState('');
  const [stop, setStop] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<IntelligenceResult | null>(null);
  const [resultMetric, setResultMetric] = useState<Metric>('ctr');
  const lock = useRef(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (lock.current) return;
    if (!start || !stop || stop < start) { setError('Choose a valid exact reporting window. The end date must be on or after the start date.'); return; }
    const scope = store.captureScope();
    if (!scope || !accounts.some(account => account.id === accountId)) return;
    lock.current = true; setBusy(true); setError(''); setResult(null);
    const controller = new AbortController(); request.current = controller;
    const signal = AbortSignal.any([scope.signal, controller.signal]);
    try {
      const next = await runIntelligence(scope.companyId, accountId, metric, start, stop, signal);
      if (scope.isCurrent() && !signal.aborted) { setResult(next); setResultMetric(metric); }
    } catch (caught) {
      if (scope.isCurrent() && !signal.aborted) setError(errorText(caught));
    } finally {
      if (request.current === controller) request.current = null;
      lock.current = false;
      if (scope.isCurrent() && !signal.aborted) setBusy(false);
    }
  }
  return <PageLayout className="intelligence-page">
    <Panel><SectionHeader title="Compare creative evidence" description={`Run an on-demand comparison for ${activeCompany?.name ?? 'this company'}.`} />
      {!accounts.length ? <Alert><p>No linked Meta Ads account is available. Connect Meta and link an Ads account in <a href="#settings">Settings</a>.</p></Alert>
        : <form className="intelligence-form" onSubmit={event => void submit(event)}>
          <label>Meta Ads account<Select value={accountId} onChange={event => setAccountId(event.target.value)} disabled={busy}>{accounts.map(account => <option value={account.id} key={account.id}>{account.name}</option>)}</Select></label>
          <label>Performance metric<Select value={metric} onChange={event => setMetric(event.target.value as Metric)} disabled={busy}>{metrics.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}</Select></label>
          <label>Start date<Input type="date" required value={start} max={stop || undefined} disabled={busy} onChange={event => setStart(event.target.value)} /></label>
          <label>End date<Input type="date" required value={stop} min={start || undefined} disabled={busy} onChange={event => setStop(event.target.value)} /></label>
          <Button variant="primary" type="submit" disabled={busy || !accountId || !start || !stop}>Run Creative Intelligence</Button>
        </form>}
      {busy && <LoadingState label="Comparing performance and creative evidence…" />}
      {error && <Alert tone="danger"><p>{error}</p></Alert>}
    </Panel>
    {result && <Result result={result} selectedMetric={resultMetric} />}
  </PageLayout>;
}
