import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Library, Search } from 'lucide-react';
import { CompanyScopeBoundary, useCompany, useCompanyQuery } from './CompanyProvider';
import { Button, Checkbox, Input, Select } from '../ui/controls';
import { Alert, EmptyState, LoadingState, PageLayout, Panel, SectionHeader } from '../ui/layout';
import { ContentList } from '../content/ContentList';
import { contentError, defaultFilters, loadContent, type ContentFilters } from '../content/contentApi';
import '../content/content.css';

export function CompanyContent() { return <CompanyScopeBoundary><Content /></CompanyScopeBoundary>; }
function Content() {
  const { activeCompany } = useCompany();
  const [filters, setFilters] = useState(defaultFilters);
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [revision, revise] = useState(0);
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
      {result.status === 'loading' && <LoadingState label="Loading company content…" />}
      {result.status === 'error' && <Alert tone="danger"><p>{contentError(result.error)}</p><Button onClick={() => revise(v => v + 1)}>Retry content</Button></Alert>}
      {result.data && (result.data.items.length ? <>
        <div className="cm-content-results"><p role="status">Showing {offset + 1}–{offset + result.data.items.length}{filtered ? ' matching items' : ' items'}</p><span>Published date · Analysis status</span></div>
        <ContentList items={result.data.items} />
        <nav className="cm-content-pagination" aria-label="Content pagination"><Button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous content</Button><span>Page {Math.floor(offset / 20) + 1}</span><Button disabled={result.data.next_offset === null} onClick={() => setOffset(result.data!.next_offset!)}>Next content</Button></nav>
      </> : <EmptyState title={filtered ? 'No matching content' : 'Your content library starts here'} icon={filtered ? <Search size={28} /> : <Library size={28} />}
        action={filtered ? <Button onClick={reset}>Clear filters</Button> : <a className="cm-feature-link" href="#settings">{activeCompany?.accounts.length ? 'Review linked accounts' : 'Link Meta accounts'} <ArrowRight size={16} aria-hidden="true" /></a>}>
        <p>{filtered ? 'Try a different search or clear your filters to see more content.' : activeCompany?.accounts.length ? 'No content is available from your linked accounts yet. Check your account setup in Settings.' : 'Link your company’s Meta accounts to bring your social content together.'}</p>
      </EmptyState>)}
    </div>}
  </PageLayout>;
}
