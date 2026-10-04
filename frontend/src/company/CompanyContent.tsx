import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Library, Search } from 'lucide-react';
import { CompanyScopeBoundary, useCompany, useCompanyQuery } from './CompanyProvider';
import { Button, Checkbox, Input, Select } from '../ui/controls';
import { Alert, EmptyState, LoadingState, PageLayout, Panel, SectionHeader } from '../ui/layout';
import { ContentList } from '../content/ContentList';
import { analyzeContent, contentError, defaultFilters, loadContent, type ContentFilters } from '../content/contentApi';
import '../content/content.css';
import { PlanLimitError } from '../billing/billingApi';
import { useBilling } from '../billing/BillingProvider';
import { LimitNotice } from '../billing/BillingUI';

export function CompanyContent({ onAnalysisChange }: { onAnalysisChange?: () => void }) { return <CompanyScopeBoundary><Content onAnalysisChange={onAnalysisChange} /></CompanyScopeBoundary>; }
function Content({ onAnalysisChange }: { onAnalysisChange?: () => void }) {
  const { activeCompany } = useCompany();
  const billing = useBilling();
  const [filters, setFilters] = useState(defaultFilters);
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [revision, revise] = useState(0);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');
  const [limit, setLimit] = useState(false);
  const actionController = useRef<AbortController | null>(null);
  const lastStatuses = useRef('');
  useEffect(() => () => actionController.current?.abort(), []);
  // Coalesce typing; other filters apply immediately and always reset pagination.
  useEffect(() => {
    if (search.trim() === filters.search) return;
    const timer = setTimeout(() => { setFilters(current => current.search === search.trim() ? current : { ...current, search: search.trim() }); setOffset(0); }, 300);
    return () => clearTimeout(timer);
  }, [search, filters.search]);
  const update = <K extends keyof ContentFilters>(key: K, value: ContentFilters[K]) => { setFilters(current => ({ ...current, [key]: value })); setOffset(0); };
  const invalidDates = Boolean(filters.from && filters.to && filters.from > filters.to);
  const load = useCallback((company: string, signal: AbortSignal) => invalidDates ? Promise.resolve({ items: [], next_offset: null }) : loadContent(company, signal, filters, offset), [filters, offset, invalidDates]);
  const result = useCompanyQuery(`content:${revision}`, load);
  const filtered = Boolean(filters.search || filters.platform || filters.type || filters.analyzed || filters.from || filters.to);
  const publishingLinked = activeCompany?.accounts.some(account => account.platform === 'instagram' || account.platform === 'facebook') ?? false;
  const allItems = result.data?.items ?? [];
  const statuses = result.data?.items.map(item => `${item.library_item_id}:${item.analysis_state}:${item.analyzed}`).join('|') ?? '';
  useEffect(() => {
    if (!result.data || statuses === lastStatuses.current) return;
    lastStatuses.current = statuses;
    onAnalysisChange?.();
  }, [result.data, statuses, onAnalysisChange]);
  const startAnalysis = async (id: string) => {
    if (!activeCompany || analyzing) return;
    const controller = new AbortController();
    actionController.current = controller;
    setAnalyzing(id); setActionError(''); setLimit(false);
    try {
      await analyzeContent(activeCompany.id, id, controller.signal);
      if (!controller.signal.aborted) { revise(v => v + 1); onAnalysisChange?.(); }
    } catch (error) {
      if (!controller.signal.aborted) { if (error instanceof PlanLimitError && error.code === 'analysis_limit_reached') { setLimit(true); billing.refresh(); } else setActionError('Analysis could not be started. Try again or check your access in Settings.'); }
    } finally {
      if (!controller.signal.aborted) setAnalyzing(null);
    }
  };
  const completeUnfilteredPage = !filtered && offset === 0 && result.data?.next_offset === null;
  const noAnalysis = completeUnfilteredPage && allItems.length > 0 && allItems.every(item => !item.analyzed);
  const processing = allItems.some(item => ['queued', 'pending', 'processing', 'running', 'downloading', 'analyzing'].includes(item.analysis_state));
  const failed = allItems.some(item => item.analysis_state === 'failed');
  const quotaReached = billing.state.data && billing.state.data.usage.analyses >= billing.state.data.entitlements.analysis_limit;
  const reset = () => { setSearch(''); setFilters(defaultFilters); setOffset(0); };
  return <PageLayout className="cm-library" role="region" aria-label="Company content library">
    <SectionHeader title="Content library" description="Browse the content linked to this company. Analysed videos can inform your next idea."
      actions={<a className="cm-feature-link" href="#generate">Generate idea <ArrowRight size={16} aria-hidden="true" /></a>} />
    <Panel className="cm-content-filters">
      <div className="cm-content-filter-main">
        <label className="cm-content-search">Search content<Input type="search" maxLength={200} value={search} placeholder="Search by title" onChange={e => setSearch(e.target.value)} /></label>
        <div className="cm-content-filter-field"><label htmlFor="content-platform">Content platform</label><Select id="content-platform" value={filters.platform} onChange={e => update('platform', e.target.value)}><option value="">All platforms</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="meta_ads">Meta Ads</option></Select></div>
        <div className="cm-content-filter-field"><label htmlFor="content-type">Content type</label><Select id="content-type" value={filters.type} onChange={e => update('type', e.target.value)}><option value="">All types</option><option value="video">Video</option><option value="reel">Reel</option><option value="ad">Ad</option></Select></div>
        <div className="cm-content-filter-field"><label htmlFor="content-order">Sort by</label><Select id="content-order" value={filters.order} onChange={e => update('order', e.target.value)}><option value="desc">Newest published</option><option value="asc">Oldest published</option></Select></div>
      </div>
      <div className="cm-content-filter-more">
        <Checkbox label="Analysed only" checked={filters.analyzed} onChange={e => update('analyzed', e.target.checked)} />
        <details><summary>Publication dates{filters.from || filters.to ? ' · Filtered' : ''}</summary><div className="cm-content-dates">
          <label>Published from (UTC)<Input type="date" value={filters.from} max={filters.to || '9999-12-31'} aria-invalid={invalidDates} aria-describedby={invalidDates ? 'content-date-error' : undefined} onChange={e => update('from', e.target.value)} /></label>
          <label>Published to (UTC)<Input type="date" value={filters.to} min={filters.from || undefined} max="9999-12-31" aria-invalid={invalidDates} aria-describedby={invalidDates ? 'content-date-error' : undefined} onChange={e => update('to', e.target.value)} /></label>
        </div></details>
        {filtered && <Button variant="ghost" onClick={reset}>Clear filters</Button>}
      </div>
      {invalidDates && <Alert tone="danger" id="content-date-error">Choose an end date on or after the start date.</Alert>}
    </Panel>
    {!invalidDates && <div aria-busy={result.status === 'loading'}>
      {actionError && <Alert tone="danger" role="alert">{actionError}</Alert>}
      {(limit || quotaReached) && <LimitNotice code="analysis_limit_reached" billing={billing.state.data} onUpgrade={() => { window.location.hash = 'settings'; }} />}
      {result.status === 'loading' && <LoadingState label="Loading company content…" />}
      {result.status === 'error' && <Alert tone="danger"><p>{contentError(result.error)}</p><Button onClick={() => revise(v => v + 1)}>Retry content</Button></Alert>}
      {result.data && (result.data.items.length ? <>
        {completeUnfilteredPage && (noAnalysis || processing || failed) && <div className="cm-content-guidance">
          <h2>{processing ? 'Analysis is in progress' : failed ? 'Some analysis needs attention' : 'Analyze content to inform your ideas'}</h2>
          <p>{processing ? 'Some content is queued or being processed. Check the status below before using it to generate ideas.' : failed ? 'Some items could not be analyzed. You can refresh their status; failed items are not ready as idea sources.' : 'ContentMetric needs analyzed content to understand what performs and how your content is structured. Review the item statuses below.'}</p>
          {(processing || failed) && <Button onClick={() => revise(v => v + 1)}>Refresh analysis status</Button>}
        </div>}
        <div className="cm-content-results"><p role="status">Showing {offset + 1}–{offset + result.data.items.length}{filtered ? ' matching items' : ' items'}</p><span>Published date · Analysis status</span></div>
        <ContentList items={result.data.items} onAnalyze={activeCompany?.role === 'owner' ? id => { void startAnalysis(id); } : undefined} analyzing={analyzing} />
        <nav className="cm-content-pagination" aria-label="Content pagination"><Button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous content</Button><span>Page {Math.floor(offset / 20) + 1}</span><Button disabled={result.data.next_offset === null} onClick={() => setOffset(result.data!.next_offset!)}>Next content</Button></nav>
      </> : <EmptyState title={filtered ? 'No matching content' : !publishingLinked ? 'Connect your content source' : 'No content here yet'} icon={filtered ? <Search size={28} /> : <Library size={28} />}
        action={filtered ? <Button onClick={reset}>Clear filters</Button> : <a className="cm-feature-link cm-feature-link--primary" href="#settings">{publishingLinked ? 'Review linked accounts' : 'Go to Settings'} <ArrowRight size={16} aria-hidden="true" /></a>}>
        <p>{filtered ? 'Try a different search or clear your filters to see more content.' : !publishingLinked ? 'Link an Instagram or Facebook account in Settings so ContentMetric can load its published content.' : 'Published content from your linked accounts will appear here after discovery. Check your account setup in Settings if you expected to see posts.'}</p>
      </EmptyState>)}
    </div>}
  </PageLayout>;
}
