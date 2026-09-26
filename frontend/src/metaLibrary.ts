/** Proposed library contract; only authentication and discovery exist on the backend today. */
export type Platform = "facebook" | "instagram" | "meta_ads";
export type SourceRef = { platform: Platform; account_id: string; page_id?: string };
export type Source = SourceRef & { name: string };
export type VideoStatus = "new" | "analyzing" | "ready" | "unavailable" | "failed";
export type Video = {
  id: string; source: SourceRef; title: string; platform: Platform;
  content_type: "instagram_reel" | "facebook_reel" | "facebook_video" | "meta_video_ad";
  distribution: "organic" | "paid"; status: VideoStatus;
  thumbnail_url: string | null; published_at: string | null;
  metrics: { views: number | null; likes: number | null; comments: number | null; shares: number | null } | null;
};
export type Library = {
  items: Video[]; next_cursor: string | null; sync_state: "idle" | "syncing";
  summary: Record<VideoStatus | "total", number>;
  source_errors: { source: SourceRef; code: string }[];
};
export type Idea = { concept: string; script: string; used_item_ids: string[]; skipped_items: { id: string; code: string }[] };
export const sourceKey = (source: SourceRef) => JSON.stringify([source.platform, source.account_id, source.page_id ?? ""]);
export const sourceRef = ({ platform, account_id, page_id }: SourceRef): SourceRef => ({ platform, account_id, ...(page_id ? { page_id } : {}) });
const platforms = ["facebook", "instagram", "meta_ads"];
const statuses = ["new", "analyzing", "ready", "unavailable", "failed"];
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const nullableString = (value: unknown) => value === null || typeof value === "string";
const stringList = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === "string" && !!item);
const validSource = (value: unknown): value is SourceRef => object(value) && platforms.includes(String(value.platform)) && typeof value.account_id === "string" && !!value.account_id && (value.page_id === undefined || typeof value.page_id === "string");

export class ServiceError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export function friendlyError(status: number, context: "library" | "generation" | "accounts" = "library") {
  if (status === 401) return "Your Meta connection has expired. Reconnect Meta to continue.";
  if (status === 403) return "Some content isn’t shared with us. Reconnect Meta and allow access to the Pages and accounts you want to use.";
  if (status === 404 || status === 501) return context === "generation" ? "Idea generation isn’t available yet. Please try again later." : "Your video library isn’t available yet. Please try again later.";
  if (status === 429) return "There have been too many requests. Give it a moment, then try again.";
  if (context === "generation") return "We couldn’t generate your idea. Your content and previous idea are still here. Please try again.";
  if (context === "accounts") return "We couldn’t load some of your accounts. Please try again.";
  return "We couldn’t update your library. Any videos already loaded are still here. Please try again.";
}
export async function request(path: string, signal: AbortSignal, body?: unknown, context: "library" | "generation" | "accounts" = "library"): Promise<unknown> {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST", credentials: "same-origin", cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(context === "generation" ? 90000 : 20000)]),
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (!response.ok) throw new ServiceError(response.status, friendlyError(response.status, context));
  return response.json();
}
export const errorMessage = (error: unknown, context: "library" | "generation" | "accounts" = "library") => error instanceof ServiceError ? error.message : friendlyError(0, context);
function invalid() { return new ServiceError(502, "We couldn’t read the latest update. Please try again."); }

type DiscoveryItem = { id: string; name: string };
async function discover(path: string, signal: AbortSignal): Promise<DiscoveryItem[]> {
  const items = new Map<string, DiscoveryItem>();
  const seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const data = await request(`/api/meta/discovery/${path}${cursor ? `?after=${encodeURIComponent(cursor)}` : ""}`, signal, undefined, "accounts");
    if (!object(data) || !Array.isArray(data.items) || !nullableString(data.next_cursor)) throw invalid();
    for (const item of data.items) {
      if (!object(item) || typeof item.id !== "string" || typeof item.name !== "string") throw invalid();
      items.set(item.id, { id: item.id, name: item.name });
    }
    cursor = data.next_cursor as string | null;
    if (cursor && seen.has(cursor)) throw invalid();
    if (cursor) seen.add(cursor);
  } while (cursor);
  return [...items.values()];
}
export async function discoverSources(signal: AbortSignal): Promise<{ sources: Source[]; errors: string[] }> {
  const sources: Source[] = [];
  const errors: string[] = [];
  const results = await Promise.allSettled([
    discover("pages", signal).then(async (pages) => {
      sources.push(...pages.map((page): Source => ({ platform: "facebook", account_id: page.id, page_id: page.id, name: page.name })));
      const accounts = await Promise.allSettled(pages.map(async (page) => {
        const linked = await discover(`pages/${encodeURIComponent(page.id)}/instagram-accounts`, signal);
        sources.push(...linked.map((account): Source => ({ platform: "instagram", account_id: account.id, page_id: page.id, name: account.name })));
      }));
      for (const result of accounts) if (result.status === "rejected") {
        if (result.reason instanceof ServiceError && result.reason.status === 401) throw result.reason;
        errors.push(errorMessage(result.reason, "accounts"));
      }
    }),
    discover("ad-accounts", signal).then((accounts) => sources.push(...accounts.map((account): Source => ({ platform: "meta_ads", account_id: account.id, name: account.name })))),
  ]);
  for (const result of results) if (result.status === "rejected") {
    if (result.reason instanceof ServiceError && result.reason.status === 401) throw result.reason;
    errors.push(errorMessage(result.reason, "accounts"));
  }
  return { sources: [...new Map(sources.map((source) => [sourceKey(source), source])).values()].sort((a, b) => a.platform.localeCompare(b.platform) || a.name.localeCompare(b.name)), errors: [...new Set(errors)] };
}
export async function readLibrary(sources: SourceRef[], cursor: string | null, signal: AbortSignal): Promise<Library> {
  const query = new URLSearchParams({ sources: JSON.stringify(sources.map(sourceRef)) });
  if (cursor) query.set("after", cursor);
  const data = await request(`/api/meta/library?${query}`, signal);
  if (!object(data) || !Array.isArray(data.items) || !nullableString(data.next_cursor) || !["idle", "syncing"].includes(String(data.sync_state)) || !object(data.summary) || !Array.isArray(data.source_errors)) throw invalid();
  if (![...statuses, "total"].every((key) => Number.isSafeInteger((data.summary as Record<string, unknown>)[key]) && Number((data.summary as Record<string, unknown>)[key]) >= 0)) throw invalid();
  const allowed = new Set(sources.map(sourceKey));
  for (const item of data.items) {
    if (!object(item) || typeof item.id !== "string" || !item.id || !validSource(item.source) || !allowed.has(sourceKey(item.source)) || typeof item.title !== "string" || !platforms.includes(String(item.platform)) || !statuses.includes(String(item.status)) || !["instagram_reel", "facebook_reel", "facebook_video", "meta_video_ad"].includes(String(item.content_type)) || !["organic", "paid"].includes(String(item.distribution)) || !nullableString(item.thumbnail_url) || !nullableString(item.published_at)) throw invalid();
    if (item.metrics !== null && (!object(item.metrics) || !["views", "likes", "comments", "shares"].every((key) => { const value = (item.metrics as Record<string, unknown>)[key]; return value === null || (Number.isSafeInteger(value) && Number(value) >= 0); }))) throw invalid();
  }
  if (!data.source_errors.every((item) => object(item) && validSource(item.source) && typeof item.code === "string")) throw invalid();
  return data as Library;
}
export async function syncLibrary(sources: SourceRef[], signal: AbortSignal) {
  const data = await request("/api/meta/library/sync", signal, { sources: sources.map(sourceRef) });
  if (!object(data) || data.accepted !== true) throw invalid();
}
export async function generateIdea(ids: string[], signal: AbortSignal): Promise<Idea> {
  const data = await request("/api/meta/library/recommendations", signal, { item_ids: ids }, "generation");
  if (!object(data) || typeof data.concept !== "string" || !data.concept.trim() || typeof data.script !== "string" || !data.script.trim() || !stringList(data.used_item_ids) || !data.used_item_ids.length || !Array.isArray(data.skipped_items)) throw invalid();
  if (!data.skipped_items.every((item) => object(item) && typeof item.id === "string" && typeof item.code === "string")) throw invalid();
  const returned = [...data.used_item_ids, ...(data.skipped_items as { id: string }[]).map((item) => item.id)];
  if (returned.length !== ids.length || new Set(returned).size !== returned.length || returned.some((id) => !ids.includes(id))) throw invalid();
  return data as Idea;
}
