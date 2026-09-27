import { useCallback, useState } from 'react';
import { CompanyScopeBoundary, useCompanyQuery } from './CompanyProvider';
import { isUUID, ServiceError } from '../metaLibrary';
import { generationError } from '../generation/generationApi';

type Card = { library_item_id: string; display_title: string; platform: string; content_type: string; published_at: string | null; analysis_state: string; analyzed: boolean; summary: { duration_seconds: number | null; width: number | null; height: number | null } };
type Page = { items: Card[]; next_offset: number | null };
export function CompanyContent() { return <CompanyScopeBoundary><Content /></CompanyScopeBoundary>; }
function Content() {
  const [search, setSearch] = useState(''); const [platform, setPlatform] = useState('');
  const [analyzed, setAnalyzed] = useState(false); const [offset, setOffset] = useState(0); const [revision, revise] = useState(0);
  const load = useCallback(async (company: string, signal: AbortSignal): Promise<Page> => {
    const query = new URLSearchParams({ limit: '20', offset: String(offset), order: 'desc', analyzed_only: String(analyzed) });
    if (search.trim()) query.set('search', search.trim());
    if (platform) query.set('platform', platform);
    const response = await fetch(`/api/companies/${company}/content?${query}`, { signal, credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new ServiceError(response.status, 'Content request failed.');
    const page = await response.json();
    if (!Array.isArray(page.items) || !(page.next_offset === null || (Number.isInteger(page.next_offset) && page.next_offset > offset)) || page.items.some((item: Card) => !isUUID(item.library_item_id) || typeof item.display_title !== 'string')) throw new ServiceError(502, 'Invalid content response.');
    return page;
  }, [search, platform, analyzed, offset]);
  const result = useCompanyQuery(`content:${revision}`, load);
  return <section className="company-content" aria-label="Company content library"><h2>Content library</h2>
    <div className="generation-filters"><label>Search content<input type="search" maxLength={200} value={search} onChange={e => { setSearch(e.target.value); setOffset(0); }} /></label>
      <label>Content platform<select value={platform} onChange={e => { setPlatform(e.target.value); setOffset(0); }}><option value="">All platforms</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="meta_ads">Meta Ads</option></select></label>
      <label><input type="checkbox" checked={analyzed} onChange={e => { setAnalyzed(e.target.checked); setOffset(0); }} />Analyzed only</label></div>
    {result.status === 'loading' && <p role="status">Loading company content…</p>}
    {result.status === 'error' && <div role="alert"><p>{generationError(result.error)}</p><button onClick={() => revise(v => v + 1)}>Retry content</button></div>}
    {result.data && <>{!result.data.items.length && <p>No content matches this company and these filters. Link accounts in company settings to get started.</p>}
      <ul className="idea-list">{result.data.items.map(item => <li key={item.library_item_id}><strong>{item.display_title}</strong><p>{item.platform} · {item.content_type} · {item.published_at ? new Date(item.published_at).toLocaleDateString() : 'Date unavailable'}</p><p>{item.analyzed ? 'Analyzed — ready as a source' : `Analysis: ${item.analysis_state}`}</p>
        {item.summary && <p className="muted">{item.summary.duration_seconds != null && `${item.summary.duration_seconds.toFixed(1)} seconds `}{item.summary.width != null && item.summary.height != null && ` · ${item.summary.width} × ${item.summary.height}`}</p>}</li>)}</ul>
      <div className="idea-actions"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous content</button><button disabled={result.data.next_offset === null} onClick={() => setOffset(result.data!.next_offset!)}>Next content</button></div></>}
    <p className="muted">Media preview, sync and analysis controls are unavailable in this company view.</p>
  </section>;
}
