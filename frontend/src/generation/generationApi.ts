import { apiFetch } from "../auth/apiFetch";
import { isUUID, ServiceError } from '../metaLibrary';
import { billingError } from '../billing/billingApi';

export type TargetPlatform = 'instagram' | 'facebook';
export type SourceItem = { id: string; title: string; platform: TargetPlatform | 'meta_ads'; publishedAt: string | null };
export type PersistedIdea = { id: string; companyId: string; title: string; concept: string; script: string; targetPlatforms: TargetPlatform[] };
export type GenerationInput = { companyId: string; sourceIds: string[]; brief?: string; targetPlatforms: TargetPlatform[]; idempotencyKey: string };
export interface GenerationApi {
  listSources(companyId: string, signal: AbortSignal, manual?: boolean): Promise<SourceItem[]>;
  generate(input: GenerationInput, signal: AbortSignal): Promise<PersistedIdea>;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const invalid = () => new ServiceError(502, 'Invalid generation service response.');
const uuid = (id: string) => { if (!isUUID(id)) throw new ServiceError(422, 'Invalid identifier.'); return encodeURIComponent(id); };
// Company-authorized backend contracts; default resolution is exactly one page.
export const generationPaths = {
  sources: (id: string) => `/api/companies/${uuid(id)}/content`,
  generate: (id: string) => `/api/meta/companies/${uuid(id)}/recommendations`,
};
export function latestSources(items: readonly SourceItem[]): SourceItem[] {
  return [...items].sort((a, b) => (b.publishedAt ? Date.parse(b.publishedAt) : -Infinity) - (a.publishedAt ? Date.parse(a.publishedAt) : -Infinity) || b.id.localeCompare(a.id)).slice(0, 20);
}
export function generationError(error: unknown): string {
  if (error instanceof ServiceError) {
    if (error.status === 401) return 'Your session has expired. Reconnect Meta and select your company again.';
    if (error.status === 404) return 'This company or source content is no longer available. Reload companies and try again.';
    if (error.status === 409) return 'Generation could not complete because the request or source content has changed. Retry, or reload sources and review your selection.';
    if ([400, 422].includes(error.status)) return 'Check your sources, brief and target platforms, then try again.';
    return 'The generation service is unavailable. Please try again shortly.';
  }
  return 'Could not reach the service. Check your connection and retry.';
}
export function createGenerationApi(fetcher: typeof fetch = (...args) => apiFetch(...args)): GenerationApi {
  async function request(path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
    const response = await fetcher(path, { method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
      signal: AbortSignal.any([signal, AbortSignal.timeout(body ? 180000 : 20000)]),
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw response.status === 402 ? await billingError(response) : new ServiceError(response.status, 'Generation request failed.');
    try { return await response.json(); } catch { throw invalid(); }
  }
  return {
    async listSources(companyId, signal, manual = false) {
      const items = new Map<string, SourceItem>();
      let offset: number | null = 0;
      do {
        const query = new URLSearchParams({ analyzed_only: 'true', limit: '20', order: 'desc' });
        if (offset) query.set('offset', String(offset));
        const page = await request(`${generationPaths.sources(companyId)}?${query}`, signal);
        if (!object(page) || !Array.isArray(page.items) || !(page.next_offset === null || (Number.isInteger(page.next_offset) && Number(page.next_offset) > offset))) throw invalid();
        for (const value of page.items) {
          if (!object(value)) throw invalid();
          if (value.analyzed !== true) continue;
          if (!isUUID(value.library_item_id) || typeof value.display_title !== 'string' || !['instagram', 'facebook', 'meta_ads'].includes(String(value.platform)) || !(value.published_at === null || (typeof value.published_at === 'string' && Number.isFinite(Date.parse(value.published_at))))) throw invalid();
          // video_ids in the generation body means library IDs, never nullable video_id.
          items.set(value.library_item_id, { id: value.library_item_id, title: value.display_title || 'Untitled content', platform: value.platform as SourceItem['platform'], publishedAt: value.published_at as string | null });
        }
        offset = page.next_offset as number | null;
      } while (manual && offset !== null);
      return [...items.values()];
    },
    async generate(input, signal) {
      if (input.sourceIds.length < 1 || input.sourceIds.length > 20 || new Set(input.sourceIds).size !== input.sourceIds.length || !input.sourceIds.every(isUUID) || !isUUID(input.idempotencyKey) || !input.targetPlatforms.length || input.targetPlatforms.some(p => !['instagram', 'facebook'].includes(p)) || new Set(input.targetPlatforms).size !== input.targetPlatforms.length || (input.brief?.length ?? 0) > 10000) throw new ServiceError(422, 'Invalid generation input.');
      const result = await request(generationPaths.generate(input.companyId), signal, {
        request_id: input.idempotencyKey, video_ids: input.sourceIds,
        generation_brief: input.brief?.trim() || null, target_platforms: input.targetPlatforms,
      });
      if (!object(result) || !isUUID(result.id) || result.company_id !== input.companyId || !['title', 'concept', 'script'].every(k => typeof result[k] === 'string' && (result[k] as string).trim()) || !Array.isArray(result.target_platforms) || !result.target_platforms.length || result.target_platforms.some(p => p !== 'instagram' && p !== 'facebook')) throw invalid();
      return { id: result.id, companyId: input.companyId, title: result.title as string, concept: result.concept as string, script: result.script as string, targetPlatforms: result.target_platforms as TargetPlatform[] };
    },
  };
}
export const generationApi = createGenerationApi();
