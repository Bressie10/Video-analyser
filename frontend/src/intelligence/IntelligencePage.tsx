import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, Film } from 'lucide-react';
import { apiFetch } from '../auth/apiFetch';
import { CompanyScopeBoundary, useCompany, useCompanyStore } from '../company/CompanyProvider';
import { isUUID, ServiceError } from '../metaLibrary';
import { Button, Input, Select } from '../ui/controls';
import { Alert, PageLayout } from '../ui/layout';
import { IntelligenceResultView } from './IntelligenceResult';
import { type IntelligenceResult, type Metric, metrics, parseIntelligence } from './intelligenceModel';
import './intelligence.css';

async function runIntelligence(companyId: string, accountId: string, metricId: Metric, start: string, stop: string, signal: AbortSignal): Promise<IntelligenceResult> {
  if (!isUUID(companyId) || !isUUID(accountId)) throw new ServiceError(422, 'Invalid selection');
  const response = await apiFetch(`/api/companies/${encodeURIComponent(companyId)}/intelligence`, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store', signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_id: accountId, metric_id: metricId, date_start: start, date_stop: stop }),
  });
  if (!response.ok) throw new ServiceError(response.status, 'Intelligence request failed');
  try { return parseIntelligence(await response.json()); }
  catch { throw new ServiceError(502, 'Invalid response'); }
}

function errorText(error: unknown) {
  if (error instanceof ServiceError) {
    if (error.status === 401) return 'Your session has expired. Please sign in again.';
    if (error.status === 403 || error.status === 404) return 'This workspace or Ads account is no longer available. Check Integrations and try again.';
    if (error.status === 422) return 'Check the reporting dates and selected metric, then try again.';
  }
  return 'Creative Intelligence is unavailable right now. Please try again.';
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
  const [resultAccount, setResultAccount] = useState('');
  const lock = useRef(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { if (!accounts.some(account => account.id === accountId)) setAccountId(accounts[0]?.id ?? ''); }, [accounts, accountId]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (lock.current) return;
    if (!start || !stop || stop < start) { setError('Choose a valid exact reporting window. The end date must be on or after the start date.'); return; }
    const scope = store.captureScope();
    if (!scope || !accounts.some(account => account.id === accountId)) return;
    lock.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    const signal = AbortSignal.any([scope.signal, controller.signal]);
    try {
      const next = await runIntelligence(scope.companyId, accountId, metric, start, stop, signal);
      if (scope.isCurrent() && !signal.aborted) {
        setResult(next); setResultMetric(metric);
        setResultAccount(accounts.find(account => account.id === accountId)?.name ?? 'Meta Ads account');
      }
    } catch (caught) {
      if (scope.isCurrent() && !signal.aborted) setError(errorText(caught));
    } finally {
      if (request.current === controller) request.current = null;
      lock.current = false;
      if (scope.isCurrent() && !signal.aborted) setBusy(false);
    }
  }
  return <PageLayout className="intelligence-page">
    {!accounts.length ? <section className="ci-no-account"><Film size={26} aria-hidden="true" /><h2>Link a Meta Ads account</h2>
      <p>Creative Intelligence compares ads from one linked account in an exact reporting window.</p><a href="#settings">Open Integrations <ArrowRight size={16} aria-hidden="true" /></a></section>
      : <><form className="ci-toolbar" onSubmit={event => void submit(event)} aria-label="Intelligence controls">
        <label>Ads account<Select value={accountId} onChange={event => setAccountId(event.target.value)} disabled={busy}>{accounts.map(account => <option value={account.id} key={account.id}>{account.name}</option>)}</Select></label>
        <label>Metric<Select value={metric} onChange={event => setMetric(event.target.value as Metric)} disabled={busy}>{metrics.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}</Select></label>
        <div className="ci-date-range"><label htmlFor="intelligence-start">Start date</label><Input id="intelligence-start" type="date" required value={start} max={stop || undefined} disabled={busy} onChange={event => setStart(event.target.value)} />
          <span aria-hidden="true">–</span><label htmlFor="intelligence-stop">End date</label><Input id="intelligence-stop" type="date" required value={stop} min={start || undefined} disabled={busy} onChange={event => setStop(event.target.value)} /></div>
        <Button variant="primary" type="submit" disabled={busy || !accountId || !start || !stop}>Run analysis</Button>
      </form>
      {busy && <div className="ci-loading" role="status"><span className="ci-loading-mark" aria-hidden="true" />Comparing performance and creative evidence…</div>}
      {error && <Alert tone="danger" className="ci-error"><p>{error}</p></Alert>}
      {result ? <IntelligenceResultView key={`${result.cohort.date_start}:${result.cohort.date_stop}:${resultMetric}:${resultAccount}`} result={result} metric={resultMetric} accountName={resultAccount} />
        : <section className="ci-ready"><h2>See what changed across your creatives</h2><p>Compare performance, inspect validated video differences, and review experiments to try next.</p>
          <div><span><b>01</b> Performance</span><span><b>02</b> Creative signals</span><span><b>03</b> Experiments</span></div></section>}
      </>}
  </PageLayout>;
}
