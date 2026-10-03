import { apiFetch } from "../auth/apiFetch";
import { isUUID, ServiceError } from '../metaLibrary';

export type ContentItem = {
  library_item_id: string; display_title: string; platform: string; content_type: string;
  published_at: string | null; analysis_state: string; analyzed: boolean;
  summary?: { duration_seconds: number | null; width: number | null; height: number | null } | null;
};
export type ContentPage = { items: ContentItem[]; next_offset: number | null };
export type ContentFilters = { search: string; platform: string; type: string; analyzed: boolean; from: string; to: string; order: string };
export const defaultFilters: ContentFilters = { search: '', platform: '', type: '', analyzed: false, from: '', to: '', order: 'desc' };
export async function loadContent(company: string, signal: AbortSignal, filters = defaultFilters, offset = 0, limit = 20): Promise<ContentPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset), order: filters.order, analyzed_only: String(filters.analyzed) });
  for (const [key, value] of Object.entries({ search: filters.search.trim(), platform: filters.platform, content_type: filters.type,
    published_from: filters.from ? `${filters.from}T00:00:00.000Z` : '', published_to: filters.to ? `${filters.to}T23:59:59.999Z` : '' })) {
    if (value) query.set(key, value);
  }
  const response = await apiFetch(`/api/companies/${company}/content?${query}`, { signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]), credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) throw new ServiceError(response.status, 'Content request failed.');
  const page = await response.json();
  if (!page || !Array.isArray(page.items) || !(page.next_offset === null || (Number.isInteger(page.next_offset) && page.next_offset > offset)) ||
    page.items.some((item: ContentItem) => !item || !isUUID(item.library_item_id) || typeof item.display_title !== 'string' || typeof item.analyzed !== 'boolean')) {
    throw new ServiceError(502, 'Invalid content response.');
  }
  return page;
}
export async function analyzeContent(company: string, itemId: string, signal: AbortSignal): Promise<void> {
  const response = await apiFetch(`/api/companies/${company}/content/analyze`, {
    method: 'POST', signal, credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item_id: itemId }),
  });
  if (!response.ok) throw new ServiceError(response.status, 'Analysis could not be started.');
}
export const platformLabel = (value: string) => ({ instagram: 'Instagram', facebook: 'Facebook', meta_ads: 'Meta Ads' })[value] ?? 'Social content';
export const typeLabel = (value: string) => ({ reel: 'Reel', video: 'Video', ad: 'Ad' })[value] ?? 'Content';
export function publicationDate(value: string | null) {
  return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'Date unavailable';
}
export function analysisStatus(item: ContentItem): { label: string; tone: 'success' | 'info' | 'danger' | 'neutral' } {
  if (item.analyzed) return { label: 'Analysed', tone: 'success' };
  if (['queued', 'pending', 'processing', 'running', 'downloading', 'analyzing'].includes(item.analysis_state)) return { label: 'Processing', tone: 'info' };
  if (['unavailable', 'unsupported'].includes(item.analysis_state)) return { label: 'Analysis unavailable', tone: 'neutral' };
  if (item.analysis_state === 'failed') return { label: 'Analysis failed', tone: 'danger' };
  return { label: 'Not yet analysed', tone: 'neutral' };
}
export function contentError(error: unknown) {
  if (error instanceof ServiceError && error.status === 401) return 'Your session has expired. Reconnect Meta in Settings, then try again.';
  return 'Content could not be loaded. Check your connection and try again.';
}
