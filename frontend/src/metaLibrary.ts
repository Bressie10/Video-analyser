/** Wire types mirror the authenticated FastAPI Meta library, not the old discovery API. */
export type Platform = "facebook" | "instagram" | "meta_ads";
export type AnalysisState = "discovered" | "deferred" | "queued" | "processing" | "completed" | "failed" | "unavailable" | "unsupported";
export type Asset = {
  id: string; account_id: string; platform: Platform; content_type: "video" | "reel" | "ad";
  label: string; published_at: string | null; analysis_state: AnalysisState;
  analysis_error: string | null; analysis_version: number | null; video_id: string | null;
  metrics_state: string; metrics_error: string | null;
};
export type Performance = {
  item_id: string; fetched_at: string; attribution: "organic" | "ad" | "shared_ad";
  snapshot: { performance_source: Platform; performance_metrics: Record<string, unknown> };
};
export type LibraryItem = Asset & {
  account_label: string; account_platform: Platform; performance: Performance[]; assets?: Asset[];
};
export type Source = { id: string; platform: Platform; name: string };
export type Job = {
  id: string; kind: string; state: "running" | "blocked" | "completed" | "partial_failure";
  counts: Record<string, number>; items: { id: string; item_id: string | null; kind: string; state: string; error: string | null }[];
};
export type Idea = { concept: string | null; script: string | null; response: string; usedCount: number };
export const RECOMMENDATION_LIMIT = 20;
export const isUUID = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const nullableText = (value: unknown) => value === null || typeof value === "string";
const platforms = ["facebook", "instagram", "meta_ads"];
const states = ["discovered", "deferred", "queued", "processing", "completed", "failed", "unavailable", "unsupported"];
const invalid = () => new ServiceError(502, "We couldn’t read the latest update. Please try again.");

export class ServiceError extends Error {
  constructor(public status: number, message: string, public affectedIds: string[] = []) { super(message); }
}
export function friendlyError(status: number, context: "library" | "generation" | "accounts" = "library") {
  if (status === 401) return "Your Meta connection has expired. Reconnect Meta to continue.";
  if (status === 403) return "Some content isn’t shared with us. Reconnect Meta and allow access to the accounts you want to use.";
  if (status === 409) return "Some selected videos need to be prepared again. Your previous idea is still here.";
  if (status === 413) return "These videos contain too much material for one idea. Select fewer videos and try again.";
  if (status === 422) return "Choose up to 20 ready videos and try again.";
  if (status === 404) return "Some content is no longer available. Refresh your library and select available videos.";
  if (status === 429) return "There have been too many requests. Give it a moment, then try again.";
  if (context === "generation") return "We couldn’t generate your idea. Your content and previous idea are still here. Please try again.";
  if (context === "accounts") return "We couldn’t check your accounts. Please try connecting again.";
  if (status === 503) return "Your video library is temporarily unavailable. Please try again later.";
  return "We couldn’t update your library. Any videos already loaded are still here. Please try again.";
}
export const errorMessage = (error: unknown, context: "library" | "generation" | "accounts" = "library") => error instanceof ServiceError ? error.message : friendlyError(0, context);
async function request(path: string, signal: AbortSignal, method = "GET", body?: unknown, context: "library" | "generation" = "library"): Promise<unknown> {
  const response = await fetch(path, {
    method, credentials: "same-origin", cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(context === "generation" ? 90000 : 20000)]),
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = object(data) && object(data.detail) ? data.detail : null;
    const ids = detail && Array.isArray(detail.video_ids) ? detail.video_ids.filter(isUUID) : [];
    throw new ServiceError(response.status, friendlyError(response.status, context), ids);
  }
  return data;
}
function validAsset(value: unknown): value is Asset {
  return object(value) && isUUID(value.id) && isUUID(value.account_id) && platforms.includes(String(value.platform))
    && ["video", "reel", "ad"].includes(String(value.content_type)) && typeof value.label === "string"
    && nullableText(value.published_at) && states.includes(String(value.analysis_state))
    && nullableText(value.analysis_error) && (value.video_id === null || isUUID(value.video_id))
    && (value.analysis_version === null || (Number.isInteger(value.analysis_version) && Number(value.analysis_version) > 0))
    && typeof value.metrics_state === "string" && nullableText(value.metrics_error);
}
function validPerformance(value: unknown): value is Performance {
  return object(value) && isUUID(value.item_id) && typeof value.fetched_at === "string"
    && ["organic", "ad", "shared_ad"].includes(String(value.attribution)) && object(value.snapshot)
    && platforms.includes(String(value.snapshot.performance_source)) && object(value.snapshot.performance_metrics);
}
function validItem(value: unknown): value is LibraryItem {
  return object(value) && typeof value.account_label === "string"
    && platforms.includes(String(value.account_platform)) && Array.isArray(value.performance) && value.performance.every(validPerformance)
    && (value.content_type !== "ad" || (Array.isArray(value.assets) && value.assets.every(validAsset))) && validAsset(value);
}
function pageData(data: unknown): { items: unknown[]; next_cursor: string | null } {
  if (!object(data) || !Array.isArray(data.items) || !(data.next_cursor === null || isUUID(data.next_cursor))) throw invalid();
  return { items: data.items, next_cursor: data.next_cursor };
}
export async function readLibrary(signal: AbortSignal, onPage?: (items: LibraryItem[]) => void): Promise<LibraryItem[]> {
  const items = new Map<string, LibraryItem>();
  const seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const data = pageData(await request(`/api/meta/library?limit=100${cursor ? `&after=${encodeURIComponent(cursor)}` : ""}`, signal));
    for (const item of data.items) {
      if (!validItem(item)) throw invalid();
      items.set(item.id, item);
    }
    onPage?.([...items.values()]);
    cursor = data.next_cursor;
    if (cursor && seen.has(cursor)) throw invalid();
    if (cursor) seen.add(cursor);
  } while (cursor);
  return [...items.values()];
}
async function jobRequest(path: string, signal: AbortSignal, body?: unknown): Promise<string> {
  const data = await request(path, signal, "POST", body);
  if (!object(data) || !isUUID(data.job_id)) throw invalid();
  return data.job_id;
}
export const syncLibrary = (signal: AbortSignal) => jobRequest("/api/meta/sync", signal);
export const prepareVideos = (ids: string[], signal: AbortSignal) => jobRequest("/api/meta/library/analyze", signal, { item_ids: ids });
export async function readJob(id: string, signal: AbortSignal): Promise<Job> {
  let cursor: string | null = null;
  let job: Job | null = null;
  const items = new Map<string, Job["items"][number]>();
  const seen = new Set<string>();
  do {
    const raw = await request(`/api/meta/jobs/${encodeURIComponent(id)}?limit=100${cursor ? `&after=${encodeURIComponent(cursor)}` : ""}`, signal);
    const page = pageData(raw);
    if (!object(raw) || raw.id !== id || typeof raw.kind !== "string"
      || !["running", "blocked", "completed", "partial_failure"].includes(String(raw.state)) || !object(raw.counts)
      || !Object.values(raw.counts).every((count) => Number.isInteger(count) && Number(count) >= 0)) throw invalid();
    for (const item of page.items) {
      if (!object(item) || !isUUID(item.id) || !(item.item_id === null || isUUID(item.item_id))
        || typeof item.kind !== "string" || typeof item.state !== "string" || !nullableText(item.error)) throw invalid();
      items.set(item.id, item as Job["items"][number]);
    }
    job = { id, kind: raw.kind, state: raw.state as Job["state"], counts: raw.counts as Job["counts"], items: [...items.values()] };
    cursor = page.next_cursor;
    if (cursor && seen.has(cursor)) throw invalid();
    if (cursor) seen.add(cursor);
  } while (cursor);
  return job!;
}

export const assetsOf = (item: LibraryItem): Asset[] => item.content_type === "ad" ? item.assets ?? [] : [item];
export const isReady = (item: Asset) => item.analysis_state === "completed" && !!item.video_id;
export const needsPreparation = (item: Asset) => ["discovered", "deferred"].includes(item.analysis_state);
export const isProcessing = (item: Asset) => ["queued", "processing"].includes(item.analysis_state);
export const isSelectable = (item: LibraryItem) => assetsOf(item).some((asset) => isReady(asset) || needsPreparation(asset) || isProcessing(asset));
export function displayStatus(item: LibraryItem) {
  const assets = assetsOf(item);
  const ready = assets.filter(isReady).length;
  if (ready) return ready === assets.length ? "ready" : "partial";
  if (assets.some(isProcessing)) return "analyzing";
  if (assets.some(needsPreparation)) return "new";
  return item.analysis_state === "failed" || assets.some((asset) => asset.analysis_state === "failed") ? "failed" : "unavailable";
}
export function contentLabel(item: LibraryItem) {
  if (item.content_type === "ad") return "Meta video ad";
  return `${item.platform === "instagram" ? "Instagram" : "Facebook"} ${item.content_type === "reel" ? "Reel" : "video"}`;
}
export function displayItems(items: LibraryItem[]) {
  // Ad-only video assets are represented by their parent ad, not duplicate organic cards.
  return items.filter((item) => item.content_type === "ad" || item.account_platform !== "meta_ads");
}
export function sourcesFrom(items: LibraryItem[]): Source[] {
  return [...new Map(items.map((item) => [item.account_id, { id: item.account_id, platform: item.account_platform, name: item.account_label }])).values()]
    .sort((a, b) => a.platform.localeCompare(b.platform) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}
export function ownMetrics(item: LibraryItem) {
  const snapshot = item.performance.find((entry) => entry.item_id === item.id);
  const metrics = snapshot?.snapshot.performance_metrics;
  return (["view_count", "like_count", "comment_count", "share_count"] as const).flatMap((key) => {
    const value = metrics?.[key];
    return typeof value === "number" && Number.isFinite(value) && value >= 0 ? [{ name: { view_count: "Views", like_count: "Likes", comment_count: "Comments", share_count: "Shares" }[key], value }] : [];
  });
}
export function parseIdea(response: string, usedCount: number, labels: Map<string, string>): Idea {
  let safe = response;
  // The model receives internal references; those are never customer-facing labels.
  for (const [id, label] of labels) safe = safe.replaceAll(id, label);
  safe = safe.replace(/\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b/gi, "selected video");
  const sections: Record<string, string[]> = {};
  let current = "";
  for (const line of safe.split(/\r?\n/)) {
    const heading = line.trim().replace(/^#{1,6}\s*/, "").replace(/^\d+[.)]\s*/, "").replace(/\*\*/g, "");
    const match = /^(Performance patterns and evidence|Uncertainties|New video idea|Script)\s*(?::\s*(.*))?$/i.exec(heading);
    if (match) { current = match[1].toLowerCase(); sections[current] = match[2] ? [match[2]] : []; }
    else if (current) sections[current].push(line);
  }
  const concept = sections["new video idea"]?.join("\n").trim();
  const script = sections.script?.join("\n").trim();
  return { concept: concept && script ? concept : null, script: concept && script ? script : null, response: safe, usedCount };
}
export async function generateIdea(assets: Asset[], signal: AbortSignal): Promise<Idea> {
  const ids = [...new Set(assets.filter(isReady).map((asset) => asset.id))];
  if (!ids.length || ids.length > RECOMMENDATION_LIMIT) throw new ServiceError(422, friendlyError(422));
  const data = await request("/api/meta/recommendations", signal, "POST", { video_ids: ids }, "generation");
  if (!object(data) || typeof data.model !== "string" || typeof data.response !== "string" || !data.response.trim()) throw invalid();
  return parseIdea(data.response, ids.length, new Map(assets.flatMap((asset) => [[asset.id, asset.label || "selected video"], [asset.video_id!, asset.label || "selected video"]])));
}
