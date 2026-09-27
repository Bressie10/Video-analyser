import { isUUID, ServiceError } from '../metaLibrary';

export const statuses = ['draft', 'used', 'published', 'discarded'] as const;
export const feedbackValues = ['none', 'liked', 'disliked'] as const;
export type Status = typeof statuses[number];
export type Feedback = typeof feedbackValues[number];
export type Filters = { search: string; status: string; feedback: string; platform: string; from: string; to: string };
export const emptyFilters: Filters = { search: '', status: '', feedback: '', platform: '', from: '', to: '' };
export type Publication = { id: string; title: string; platform: string; available: boolean | null; createdAt: string | null };
export type Summary = { id: string; title: string; concept: string; status: Status; feedback: Feedback; reason: string | null; createdAt: string; updatedAt: string; platforms: string[] };
export type Idea = Summary & { companyId: string; script: string; publications: Publication[]; brief: string | null };
export type Page<T> = { items: T[]; nextCursor: string | null };
export type Edit = Pick<Idea, 'title' | 'concept' | 'script'>;
export interface IdeaApi {
  history(company: string, filters: Filters, after: string | null, signal: AbortSignal): Promise<Page<Summary>>;
  detail(company: string, id: string, signal: AbortSignal): Promise<Idea>;
  edit(company: string, id: string, changes: Edit | { status: Status }, signal: AbortSignal): Promise<Idea>;
  feedback(company: string, id: string, feedback: Feedback, reason: string | null, signal: AbortSignal): Promise<Idea>;
  publications(company: string, after: string | null, signal: AbortSignal): Promise<Page<Publication>>;
  link(company: string, id: string, publication: string, linked: boolean, signal: AbortSignal): Promise<Idea>;
}
const invalid = () => new ServiceError(502, 'Invalid ideas response.');
function record(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid(); return value as Record<string, unknown>; }
function str(value: unknown): string { if (typeof value !== 'string') throw invalid(); return value; }
function uuid(value: unknown): string { if (!isUUID(value)) throw invalid(); return value.toLowerCase(); }
function nullable(value: unknown): string | null { return value == null ? null : str(value); }
function date(value: unknown): string { const result = str(value); if (!Number.isFinite(Date.parse(result))) throw invalid(); return result; }
function list<T>(value: unknown, parse: (item: unknown) => T): T[] { if (!Array.isArray(value)) throw invalid(); return value.map(parse); }
function choice<T extends string>(value: unknown, choices: readonly T[]): T { if (!choices.includes(value as T)) throw invalid(); return value as T; }
export function parseSummary(value: unknown): Summary {
  const v = record(value); const feedback = choice(v.feedback, feedbackValues);
  return { id: uuid(v.id), title: str(v.title), concept: str(v.concept), status: choice(v.status, statuses), feedback,
    reason: feedback === 'disliked' ? nullable(v.feedback_reason) : null, createdAt: date(v.created_at), updatedAt: date(v.updated_at),
    platforms: v.target_platforms === undefined ? [] : list(v.target_platforms, str) };
}
export function parsePublication(value: unknown): Publication {
  const v = record(value);
  if (v.available != null && typeof v.available !== 'boolean') throw invalid();
  return { id: uuid(v.library_item_id), title: v.title == null ? 'Linked published content' : str(v.title), platform: v.platform == null ? '' : str(v.platform),
    available: v.available == null ? null : v.available as boolean, createdAt: v.created_at == null ? null : date(v.created_at) };
}
export function parseIdea(value: unknown, company: string): Idea {
  const v = record(value);
  if (uuid(v.company_id) !== company.toLowerCase()) throw invalid();
  return { ...parseSummary(v), companyId: uuid(v.company_id), script: str(v.script), publications: list(v.publications, parsePublication), brief: nullable(v.generation_brief) };
}
function page<T>(value: unknown, parse: (item: unknown) => T): Page<T> { const v = record(value); return { items: list(v.items, parse), nextCursor: nullable(v.next_cursor) }; }
/** Safe projections only: never request evidence or dereference historical links. */
const root = (company: string) => `/api/meta/companies/${encodeURIComponent(company)}`;
const path = (company: string, id: string) => `${root(company)}/ideas/${encodeURIComponent(id)}`;
async function request(url: string, signal: AbortSignal, method = 'GET', body?: unknown): Promise<unknown> {
  const response = await fetch(url, { method, signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]), credentials: 'same-origin', cache: 'no-store',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) throw new ServiceError(response.status, 'Ideas request failed.');
  return response.json();
}
export function historyQuery(filters: Filters, after: string | null): string {
  const q = new URLSearchParams({ limit: '25' });
  for (const [key, value] of Object.entries({ search: filters.search.trim(), status: filters.status, feedback: filters.feedback,
    target_platform: filters.platform, created_from: filters.from ? `${filters.from}T00:00:00.000Z` : '',
    created_to: filters.to ? new Date(Date.parse(`${filters.to}T00:00:00.000Z`) + 86400000).toISOString() : '', after })) if (value) q.set(key, value);
  return q.toString();
}
export const ideaApi: IdeaApi = {
  history: async (c, f, after, s) => page(await request(`${root(c)}/ideas?${historyQuery(f, after)}`, s), parseSummary),
  detail: async (c, id, s) => parseIdea(await request(path(c, id), s), c),
  edit: async (c, id, changes, s) => parseIdea(await request(path(c, id), s, 'PATCH', changes), c),
  feedback: async (c, id, feedback, reason, s) => parseIdea(await request(`${path(c, id)}/feedback`, s, 'PUT', { feedback, reason: feedback === 'disliked' ? reason?.trim() || null : null }), c),
  publications: async (c, after, s) => {
    const q = new URLSearchParams({ limit: '25' }); if (after) q.set('after', after);
    return page(await request(`${root(c)}/publication-options?${q}`, s), value => { const v = record(value); return { id: uuid(v.id), title: str(v.label), platform: str(v.platform), available: true, createdAt: null }; });
  },
  link: async (c, id, publication, linked, s) => parseIdea(await request(`${path(c, id)}/publications/${encodeURIComponent(publication)}`, s, linked ? 'PUT' : 'DELETE'), c),
};
export function ideaError(error: unknown): string {
  if (error instanceof ServiceError) {
    if (error.status === 404) return 'This company, idea or published content is unavailable. Check Manage companies to restore an archived company or select another company.';
    if (error.status === 409) return 'This change conflicts with the current saved state. Your edits are kept. Cancel editing and reload the idea before trying again.';
    if (error.status === 403) return 'This company may be archived or no longer accessible. Select another company or check Manage companies.';
    if (error.status === 401) return 'Your session has expired. Reconnect and try again.';
  }
  return 'Could not load or save ideas. Check your connection and try again.';
}
