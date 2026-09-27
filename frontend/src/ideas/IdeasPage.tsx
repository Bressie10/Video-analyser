import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { CompanyScopeBoundary, useCompany, useCompanyQuery, useCompanyStore } from '../company/CompanyProvider';
import { useCompanySwitchGuard } from '../CompanySwitchGuard';
import { emptyFilters, ideaApi, ideaError, statuses, type Edit, type Filters, type Idea, type IdeaApi, type Page, type Publication, type Summary } from './ideaApi';
import { Button, Input, Select, Textarea } from '../ui/controls';
import { Alert, Badge, EmptyState, LoadingState } from '../ui/layout';
import { ThumbsUp, ThumbsDown, ArrowUpRight } from 'lucide-react';
import './ideas.css';
const label = (s: string) => s ? s[0].toUpperCase() + s.slice(1) : '';
const date = (s: string) => new Date(s).toLocaleString();
function useRead<T>(key: string, load: (company: string, signal: AbortSignal) => Promise<T>) {
  // A missing idea is not proof that the company itself is inaccessible.
  const safeLoad = useCallback(async (c: string, s: AbortSignal) => {
    try { return { data: await load(c, s), error: null }; } catch (error) { return { data: undefined, error }; }
  }, [load]);
  return useCompanyQuery(key, safeLoad);
}
function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  return <Alert tone="danger"><p>{ideaError(error)}</p>{retry && <Button onClick={retry}>Retry</Button>}</Alert>;
}
/** Cursor pages retain previous results; filters and company scope remount the chain. */
function Results<T extends { id: string }>({ load, render, empty, more, after = null, seen = [] }: {
  load: (company: string, after: string | null, signal: AbortSignal) => Promise<Page<T>>;
  render: (item: T) => ReactNode; empty: ReactNode; more: string; after?: string | null; seen?: string[];
}) {
  const [revision, revise] = useState(0); const [expanded, expand] = useState(false);
  const fetchPage = useCallback((c: string, s: AbortSignal) => load(c, after, s), [load, after]);
  const result = useRead(`${after}:${revision}`, fetchPage);
  if (!result.data) return <LoadingState label="Loading saved records…" />;
  if (result.data.error) return <ErrorNotice error={result.data.error} retry={() => revise(v => v + 1)} />;
  const page = result.data.data!;
  const items = page.items.filter(item => !seen.includes(item.id));
  const nextSeen = [...seen, ...items.map(item => item.id)];
  const next = page.nextCursor && page.nextCursor !== after ? page.nextCursor : null;
  return <>{!page.items.length && !after && <div className="idea-empty">{empty}</div>}
    <ul className="idea-list">{items.map(item => <li key={item.id}>{render(item)}</li>)}</ul>
    {next && (expanded ? <Results load={load} render={render} empty={empty} more={more} after={next} seen={nextSeen} /> : <Button className="load-more" onClick={() => expand(true)}>{more}</Button>)}
  </>;
}
export function IdeasPage({ api = ideaApi, refreshToken = 0 }: { api?: IdeaApi; refreshToken?: number }) {
  const { activeCompany, status } = useCompany();
  if (status !== 'ready') return <p role="status">Loading company…</p>;
  if (!activeCompany) return <p role="status">Select a company to see its saved ideas.</p>;
  if (activeCompany.archived) return <p role="status">This company is archived. Restore it in Manage companies to manage ideas.</p>;
  return <CompanyScopeBoundary><Workspace api={api} companyName={activeCompany.name} refreshToken={refreshToken} /></CompanyScopeBoundary>;
}
function Workspace({ api, companyName, refreshToken }: { api: IdeaApi; companyName: string; refreshToken: number }) {
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [selected, select] = useState<string | null>(null);
  const [revision, revise] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null); const previous = useRef<string | null>(null);
  useEffect(() => { if (previous.current && !selected) heading.current?.focus(); previous.current = selected; }, [selected]);
  const load = useCallback((c: string, after: string | null, s: AbortSignal) => api.history(c, filters, after, s), [api, filters]);
  const field = (key: keyof Filters, value: string) => setFilters(f => ({ ...f, [key]: value }));
  const invalidDates = !!(filters.from && filters.to && filters.from > filters.to);
  return <section className="ideas-workspace" aria-label="Saved ideas">
    {selected ? <Detail key={selected} id={selected} api={api} onBack={() => select(null)} onChanged={() => revise(v => v + 1)} /> : <>
      <header className="ideas-index-header"><div><h2 ref={heading} tabIndex={-1}>Your creative library</h2><p>Saved ideas for {companyName}. Keep shaping the work worth making.</p></div><a className="idea-generate" href="#generate">Generate idea <ArrowUpRight size={18} aria-hidden="true" /></a></header>
      <div className="idea-search"><label>Search ideas<Input type="search" placeholder="Search titles, concepts and scripts" maxLength={200} value={filters.search} onChange={e => field('search', e.target.value)} /></label></div>
      <details className="idea-filter-disclosure" open><summary>Filters {Object.values(filters).filter(Boolean).length > 0 && <Badge>{Object.values(filters).filter(Boolean).length} active</Badge>}</summary><div className="idea-filters">
        <label>Status<Select aria-label="Status" value={filters.status} onChange={e => field('status', e.target.value)}><option value="">All statuses</option>{statuses.map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></label>
        <label>Feedback<Select aria-label="Feedback" value={filters.feedback} onChange={e => field('feedback', e.target.value)}><option value="">All feedback</option>{['none', 'liked', 'disliked'].map(f => <option key={f} value={f}>{label(f)}</option>)}</Select></label>
        <label>Target platform<Select aria-label="Target platform" value={filters.platform} onChange={e => field('platform', e.target.value)}><option value="">All platforms</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option></Select></label>
        <label>Created from (UTC)<Input type="date" value={filters.from} onChange={e => field('from', e.target.value)} /></label>
        <label>Created through (UTC)<Input type="date" value={filters.to} onChange={e => field('to', e.target.value)} /></label>
      </div><Button variant="ghost" onClick={() => setFilters({ ...emptyFilters })}>Clear filters</Button></details>
      {invalidDates ? <p role="alert">The end date must be on or after the start date.</p> : <Results<Summary> key={`${JSON.stringify(filters)}:${revision}:${refreshToken}`} load={load} more="Load more ideas"
        empty={Object.values(filters).some(Boolean) ? <EmptyState title="No ideas match these filters."><p>Try another search or clear the filters to see your saved work.</p></EmptyState> : <EmptyState title="No saved ideas yet for this company."><p>Generate your first idea to start a lasting creative library.</p></EmptyState>}
        render={idea => <article className="idea-row"><div className="idea-row-content"><Button variant="ghost" className="idea-open" onClick={() => select(idea.id)}>{idea.title}</Button><p className="idea-excerpt">{idea.concept}</p><span className="idea-platforms">{idea.platforms.map(label).join(' · ') || 'No target platform'}</span></div><div className="idea-row-meta"><LifecycleBadge status={idea.status} /><span>{idea.feedback === 'none' ? 'No feedback' : label(idea.feedback)}</span><time dateTime={idea.createdAt}>{new Date(idea.createdAt).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</time></div></article>} />}
    </>}
  </section>;
}
function LifecycleBadge({ status }: { status: Summary['status'] }) {
  return <Badge tone={status === 'published' ? 'success' : status === 'used' ? 'info' : 'neutral'}>{label(status)}</Badge>;
}
function Detail({ id, api, onBack, onChanged }: { id: string; api: IdeaApi; onBack(): void; onChanged(): void }) {
  const [revision, revise] = useState(0);
  const load = useCallback((c: string, s: AbortSignal) => api.detail(c, id, s), [api, id]);
  const result = useRead(`${id}:${revision}`, load);
  if (!result.data) return <><Button onClick={onBack}>Back to history</Button><p role="status">Loading idea…</p></>;
  if (result.data.error) return <><Button onClick={onBack}>Back to history</Button><ErrorNotice error={result.data.error} retry={() => revise(v => v + 1)} /></>;
  return <Editor key={revision} initial={result.data.data!} api={api} onBack={onBack} onChanged={onChanged} onReload={() => revise(v => v + 1)} />;
}
function Editor({ initial, api, onBack, onChanged, onReload }: { initial: Idea; api: IdeaApi; onBack(): void; onChanged(): void; onReload(): void }) {
  const store = useCompanyStore(); const [idea, setIdea] = useState(initial);
  const [editing, setEditing] = useState(false); const [draft, setDraft] = useState<Edit>(initial);
  const [disliking, setDisliking] = useState(false); const [reason, setReason] = useState('');
  const [picker, setPicker] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null); const [message, setMessage] = useState('');
  const lock = useRef(false); const lifetime = useRef(new AbortController());
  const heading = useRef<HTMLHeadingElement>(null); const titleInput = useRef<HTMLInputElement>(null);
  const dirty = editing && (['title', 'concept', 'script'] as const).some(k => draft[k] !== idea[k]);
  useCompanySwitchGuard({ unsavedEdits: dirty || disliking });
  useEffect(() => { lifetime.current = new AbortController(); heading.current?.focus(); return () => lifetime.current.abort(); }, []);
  useEffect(() => { if (editing) titleInput.current?.focus(); }, [editing]);
  async function mutate(action: (company: string, signal: AbortSignal) => Promise<Idea>, after?: () => void) {
    if (lock.current) return;
    const scope = store.captureScope(); if (!scope) return;
    const signal = AbortSignal.any([scope.signal, lifetime.current.signal]);
    lock.current = true; setBusy(true); setError(null); setMessage('');
    try { const saved = await action(scope.companyId, signal);
      if (!signal.aborted && scope.isCurrent()) { setIdea(saved); onChanged(); setMessage('Saved.'); after?.(); }
    } catch (caught) { if (!signal.aborted && scope.isCurrent()) setError(caught); }
    finally { lock.current = false; if (!signal.aborted && scope.isCurrent()) setBusy(false); }
  }
  const blocked = busy || editing || disliking;
  const cancelEdit = () => { setDraft(idea); setEditing(false); setError(null); heading.current?.focus(); };
  return <>
    <Button onClick={onBack} disabled={busy || dirty || disliking}>Back to history</Button>
    {(dirty || disliking) && <p className="muted">Save or cancel your changes before returning to history.</p>}
    <header className="idea-detail-header"><div className="idea-actions"><LifecycleBadge status={idea.status} /><span className="muted">Saved idea</span></div><h2 ref={heading} tabIndex={-1}>{idea.title}</h2><p className="muted">Created {date(idea.createdAt)} · Updated {date(idea.updatedAt)}</p></header>
    {error != null && <ErrorNotice error={error} />}<p role="status" aria-live="polite">{busy ? 'Saving…' : message}</p>
    <div className="idea-detail-grid"><div className="idea-document">{editing ? <form className="idea-edit" onSubmit={e => { e.preventDefault(); void mutate((c, s) => api.edit(c, idea.id, { title: draft.title, concept: draft.concept, script: draft.script }, s), () => { setEditing(false); heading.current?.focus(); }); }}>
      <fieldset disabled={busy}><legend>Edit idea</legend>
        <label>Title<Input ref={titleInput} required maxLength={300} value={draft.title} onChange={e => setDraft(v => ({ ...v, title: e.target.value }))} /></label>
        <label>Concept<Textarea aria-label="Concept" required maxLength={10000} rows={5} value={draft.concept} onChange={e => setDraft(v => ({ ...v, concept: e.target.value }))} /></label>
        <label>Script<Textarea aria-label="Script" required maxLength={30000} rows={12} value={draft.script} onChange={e => setDraft(v => ({ ...v, script: e.target.value }))} /></label>
        <div className="idea-actions"><Button type="submit" variant="primary" disabled={!dirty || !draft.title.trim() || !draft.concept.trim() || !draft.script.trim()}>Save</Button><Button type="button" onClick={cancelEdit}>Cancel edit</Button></div>
      </fieldset></form> : <><div className="idea-actions idea-document-actions"><Button disabled={blocked} onClick={() => { setDraft(idea); setEditing(true); setMessage(''); }}>Edit</Button><Button variant="ghost" disabled={blocked} onClick={onReload}>Reload idea</Button></div><h3>Concept</h3><p className="idea-text">{idea.concept}</p><h3>Script</h3><p className="script idea-text">{idea.script}</p></>}
    </div><aside className="idea-context" aria-label="Idea organization"><div className="idea-section"><h3>Target platforms</h3><div className="idea-actions">{idea.platforms.length ? idea.platforms.map(platform => <Badge key={platform}>{label(platform)}</Badge>) : <p>Not specified</p>}</div></div>
    <fieldset className="idea-section" disabled={blocked}><legend>Lifecycle status: {label(idea.status)}</legend><p>Statuses help organize your work. You can change them at any time.</p>
      <div className="idea-actions">{statuses.filter(s => s !== 'discarded').map(status => <Button key={status} aria-pressed={idea.status === status} onClick={() => void mutate((c, s) => api.edit(c, idea.id, { status }, s))}>{label(status)}</Button>)}</div>
      <div className="idea-discard"><Button aria-pressed={idea.status === 'discarded'} onClick={() => void mutate((c, s) => api.edit(c, idea.id, { status: 'discarded' }, s))}>Discarded</Button><span className="muted">Set aside this idea. You can restore it to any status.</span></div>
    </fieldset>
    <div className="idea-section"><h3>Feedback: {label(idea.feedback)}</h3>{idea.reason && <p className="idea-text">Reason: {idea.reason}</p>}
      <div className="idea-actions"><Button disabled={blocked} aria-pressed={idea.feedback === 'liked'} onClick={() => void mutate((c, s) => api.feedback(c, idea.id, 'liked', null, s))}><ThumbsUp size={16} aria-hidden="true" /> Like</Button><Button disabled={blocked} aria-pressed={idea.feedback === 'disliked'} onClick={() => { setReason(idea.reason ?? ''); setDisliking(true); }}><ThumbsDown size={16} aria-hidden="true" /> Dislike</Button><Button disabled={blocked || idea.feedback === 'none'} onClick={() => void mutate((c, s) => api.feedback(c, idea.id, 'none', null, s))}>Clear feedback</Button></div>
      {disliking && <form onSubmit={e => { e.preventDefault(); void mutate((c, s) => api.feedback(c, idea.id, 'disliked', reason, s), () => setDisliking(false)); }}>
        <label>Dislike reason (optional)<Textarea aria-label="Dislike reason (optional)" autoFocus maxLength={2000} value={reason} disabled={busy} onChange={e => setReason(e.target.value)} /></label>
        <div className="idea-actions"><Button type="submit" variant="primary" disabled={busy}>Save dislike</Button><Button type="button" disabled={busy} onClick={() => { setDisliking(false); setReason(''); }}>Cancel feedback</Button></div></form>}
    </div>
    {idea.brief && <details className="idea-section idea-provenance"><summary>Creation brief</summary><p className="muted">The brief used when this idea was generated.</p><p className="idea-text">{idea.brief}</p></details>}
    </aside></div><div className="idea-section idea-publications"><h3>Linked publications</h3><p>Manually associate published posts with this idea. An association does not show that the idea caused a post’s performance.</p>
      {!idea.publications.length && <p>No publications linked.</p>}<ul className="idea-list">{idea.publications.map(p => <li key={p.id}><strong>{p.title}</strong>{p.platform && <p>{label(p.platform)}</p>}
        {p.available !== true && <p className="muted">{p.available === false ? 'Content unavailable for live metrics.' : 'Live availability is not verified.'} This historical association is kept.</p>}
        <Button disabled={blocked} aria-label={`Unlink ${p.title}`} onClick={() => void mutate((c, s) => api.link(c, idea.id, p.id, false, s))}>Remove link</Button></li>)}</ul>
      <Button disabled={blocked} onClick={() => setPicker(true)}>Link published content</Button>
    </div>
    {picker && <PublicationPicker api={api} linked={idea.publications.map(p => p.id)} busy={busy} error={error} onClose={() => setPicker(false)} onLink={id => void mutate((c, s) => api.link(c, idea.id, id, true, s))} />}
  </>;
}
function PublicationPicker({ api, linked, busy, error, onClose, onLink }: { api: IdeaApi; linked: string[]; busy: boolean; error: unknown; onClose(): void; onLink(id: string): void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const focus = document.activeElement as HTMLElement; const modal = dialog.current; modal?.showModal(); return () => { modal?.close(); focus?.focus(); }; }, []);
  const load = useCallback((c: string, after: string | null, s: AbortSignal) => api.publications(c, after, s), [api]);
  return <dialog ref={dialog} className="idea-picker" aria-labelledby="publication-picker-title" onCancel={e => { e.preventDefault(); onClose(); }}>
    <h2 id="publication-picker-title">Link published content</h2><p>Choose posts accessible in this company to record their association with this idea. You can link more than one.</p>
    {error != null && <ErrorNotice error={error} />}<p role="status">{busy ? 'Saving link…' : `${linked.length} linked`}</p>
    <Results<Publication> load={load} empty="No accessible published content found." more="Load more publications" render={p => <><strong>{p.title}</strong><p>{label(p.platform)}{p.publishedAt && <> · <time dateTime={p.publishedAt}>{date(p.publishedAt)}</time></>}</p><Button disabled={busy || linked.includes(p.id) || p.available === false} onClick={() => onLink(p.id)}>{linked.includes(p.id) ? 'Linked' : p.available === false ? 'Unavailable' : `Link ${p.title}`}</Button></>} />
    <Button onClick={onClose}>Done</Button>
  </dialog>;
}
