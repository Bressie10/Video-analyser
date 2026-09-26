import { isUUID, ServiceError } from "../metaLibrary";

export type Company = Readonly<{ id: string; name: string; archived: boolean }>;
export type MetaAccount = Readonly<{ id: string; name: string; platform: "facebook" | "instagram" | "meta_ads" }>;
export type AdsContent = Readonly<{ id: string; label: string; companyId: string | null }>;
export type Page<T> = { items: T[]; nextCursor: string | null };
/** Internal UUIDs only. Provider account identifiers never identify a company. */
export interface CompanyApi {
  listCompanies(signal: AbortSignal): Promise<Company[]>;
  createCompany(name: string, signal: AbortSignal): Promise<Company>;
  renameCompany(id: string, name: string, signal: AbortSignal): Promise<Company>;
  archiveCompany(id: string, signal: AbortSignal): Promise<Company>;
  restoreCompany(id: string, signal: AbortSignal): Promise<Company>;
  listAvailableMetaAccounts(signal: AbortSignal): Promise<MetaAccount[]>;
  linkAccount(companyId: string, accountId: string, signal: AbortSignal): Promise<void>;
  unlinkAccount(companyId: string, accountId: string, signal: AbortSignal): Promise<void>;
  listAssignableAdsContent(signal: AbortSignal, cursor?: string): Promise<Page<AdsContent>>;
  assignAdsContent(contentId: string, companyId: string, signal: AbortSignal): Promise<void>;
  unassignAdsContent(contentId: string, companyId: string, signal: AbortSignal): Promise<void>;
  reassignAdsContent(contentId: string, fromCompanyId: string, toCompanyId: string, signal: AbortSignal): Promise<void>;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const invalid = () => new ServiceError(502, "Invalid company service response.");
export function companyRecord(v: unknown): Company {
  if (!object(v) || !isUUID(v.id) || typeof v.name !== "string" || typeof v.archived !== "boolean") throw invalid();
  return Object.freeze({ id: v.id.toLowerCase(), name: v.name, archived: v.archived });
}
function account(v: unknown): MetaAccount {
  if (!object(v) || !isUUID(v.id) || typeof v.name !== "string" || !["facebook", "instagram", "meta_ads"].includes(String(v.platform))) throw invalid();
  return { id: v.id, name: v.name, platform: v.platform as MetaAccount["platform"] };
}
function ad(v: unknown): AdsContent {
  if (!object(v) || !isUUID(v.id) || typeof v.label !== "string" || !(v.company_id === null || isUUID(v.company_id))) throw invalid();
  return { id: v.id, label: v.label, companyId: v.company_id };
}
function page<T>(v: unknown, parse: (value: unknown) => T): Page<T> {
  if (!object(v) || !Array.isArray(v.items) || !(v.next_cursor === null || typeof v.next_cursor === "string")) throw invalid();
  return { items: v.items.map(parse), nextCursor: v.next_cursor };
}
function uuid(id: string) {
  if (!isUUID(id)) throw new TypeError("Expected an internal UUID.");
  return encodeURIComponent(id.toLowerCase());
}
/** Provisional wire contract: change paths, bodies and parsers here during integration. */
export function createCompanyApi(fetcher: typeof fetch = (...args) => fetch(...args)): CompanyApi {
  const base = "/api/companies";
  async function request(path: string, signal: AbortSignal, method = "GET", body?: unknown): Promise<unknown> {
    const response = await fetcher(path, { method, signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]),
      credentials: "same-origin", cache: "no-store",
      ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
    if (!response.ok) throw new ServiceError(response.status, "The company request failed. Please try again.");
    if (response.status === 204) return undefined;
    try { return await response.json(); } catch { throw invalid(); }
  }
  async function all<T>(path: string, signal: AbortSignal, parse: (v: unknown) => T): Promise<T[]> {
    const items: T[] = [], seen = new Set<string>();
    let cursor: string | null = null;
    do {
      const result: Page<T> = page(await request(`${path}${cursor ? `?after=${encodeURIComponent(cursor)}` : ""}`, signal), parse);
      items.push(...result.items);
      cursor = result.nextCursor;
      if (cursor && seen.has(cursor)) throw invalid();
      if (cursor) seen.add(cursor);
    } while (cursor);
    return items;
  }
  const companyPath = (id: string) => `${base}/${uuid(id)}`;
  const assignmentPath = (id: string) => `${base}/ads-content/${uuid(id)}/assignment`;
  return {
    listCompanies: (signal) => all(base, signal, companyRecord),
    createCompany: async (name, signal) => companyRecord(await request(base, signal, "POST", { name })),
    renameCompany: async (id, name, signal) => companyRecord(await request(companyPath(id), signal, "PATCH", { name })),
    archiveCompany: async (id, signal) => companyRecord(await request(`${companyPath(id)}/archive`, signal, "POST")),
    restoreCompany: async (id, signal) => companyRecord(await request(`${companyPath(id)}/restore`, signal, "POST")),
    listAvailableMetaAccounts: (signal) => all(`${base}/available-meta-accounts`, signal, account),
    linkAccount: async (id, accountId, signal) => { await request(`${companyPath(id)}/accounts/${uuid(accountId)}`, signal, "PUT"); },
    unlinkAccount: async (id, accountId, signal) => { await request(`${companyPath(id)}/accounts/${uuid(accountId)}`, signal, "DELETE"); },
    listAssignableAdsContent: async (signal, cursor) => page(await request(`${base}/ads-content${cursor ? `?after=${encodeURIComponent(cursor)}` : ""}`, signal), ad),
    assignAdsContent: async (id, companyId, signal) => { uuid(companyId); await request(assignmentPath(id), signal, "PUT", { company_id: companyId }); },
    unassignAdsContent: async (id, companyId, signal) => { uuid(companyId); await request(assignmentPath(id), signal, "DELETE", { company_id: companyId }); },
    reassignAdsContent: async (id, from, to, signal) => { uuid(from); uuid(to); await request(assignmentPath(id), signal, "PATCH", { from_company_id: from, to_company_id: to }); },
  };
}
export const companyApi = createCompanyApi();
