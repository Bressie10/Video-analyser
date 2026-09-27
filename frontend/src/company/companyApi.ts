import { apiFetch } from "../auth/apiFetch";
import { isUUID, ServiceError } from "../metaLibrary";

export type MetaAccount = Readonly<{ id: string; name: string; platform: "facebook" | "instagram" | "meta_ads" }>;
export type Company = Readonly<{ id: string; name: string; archived: boolean; role?: "owner" | "member"; accounts: readonly MetaAccount[] }>;
export type AvailableAccount = MetaAccount & { organicOwner: { id: string; name: string; archived: boolean } | null };
export type AdsContent = Readonly<{ id: string; label: string; assigned: boolean }>;
export interface CompanyApi {
  listCompanies(signal: AbortSignal): Promise<Company[]>;
  getCompany(id: string, signal: AbortSignal): Promise<Company>;
  createCompany(name: string, signal: AbortSignal): Promise<Company>;
  renameCompany(id: string, name: string, signal: AbortSignal): Promise<Company>;
  archiveCompany(id: string, signal: AbortSignal): Promise<Company>;
  restoreCompany(id: string, signal: AbortSignal): Promise<Company>;
  listAvailableMetaAccounts(signal: AbortSignal): Promise<AvailableAccount[]>;
  linkAccount(companyId: string, accountId: string, signal: AbortSignal): Promise<Company>;
  unlinkAccount(companyId: string, accountId: string, signal: AbortSignal): Promise<Company>;
  listAssignableAdsContent(companyId: string, accountId: string, signal: AbortSignal): Promise<AdsContent[]>;
  assignAdsContent(contentId: string, companyId: string, signal: AbortSignal): Promise<void>;
  unassignAdsContent(contentId: string, companyId: string, signal: AbortSignal): Promise<void>;
  reassignAdsContent(contentId: string, fromCompanyId: string, toCompanyId: string, signal: AbortSignal): Promise<void>;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const invalid = () => new ServiceError(502, "Invalid company service response.");
function account(v: unknown): MetaAccount {
  if (!object(v) || !isUUID(v.id) || typeof v.name !== "string" || !["facebook", "instagram", "meta_ads"].includes(String(v.platform))) throw invalid();
  return Object.freeze({ id: v.id.toLowerCase(), name: v.name, platform: v.platform as MetaAccount["platform"] });
}
/** Validate normalized store records too; never retain unknown server fields. */
export function companyRecord(v: unknown): Company {
  if (!object(v) || !isUUID(v.id) || typeof v.name !== "string" || typeof v.archived !== "boolean" || !Array.isArray(v.accounts)) throw invalid();
  return Object.freeze({ id: v.id.toLowerCase(), name: v.name, archived: v.archived, role: v.role === "owner" ? "owner" : "member", accounts: Object.freeze(v.accounts.map(account)) });
}
function wireAccount(v: unknown): MetaAccount {
  if (!object(v)) throw invalid();
  return account({ id: v.account_id, name: v.display_name, platform: v.platform });
}
function wireCompany(v: unknown): Company {
  if (!object(v) || !Array.isArray(v.accounts)) throw invalid();
  return companyRecord({ id: v.company_id, name: v.name, archived: v.archived, role: v.role, accounts: v.accounts.map(wireAccount) });
}
function available(v: unknown): AvailableAccount {
  if (!object(v)) throw invalid();
  const owner = v.organic_owner;
  if (owner !== null && (!object(owner) || !isUUID(owner.company_id) || typeof owner.name !== "string" || typeof owner.archived !== "boolean")) throw invalid();
  return { ...wireAccount(v), organicOwner: owner === null ? null : { id: String(owner.company_id).toLowerCase(), name: String(owner.name), archived: Boolean(owner.archived) } };
}
function ad(v: unknown): AdsContent {
  if (!object(v) || !isUUID(v.ad_item_id) || typeof v.display_name !== "string" || typeof v.assigned !== "boolean") throw invalid();
  return { id: v.ad_item_id.toLowerCase(), label: v.display_name, assigned: v.assigned };
}
function list<T>(v: unknown, key: string, parse: (value: unknown) => T): T[] {
  if (!object(v) || !Array.isArray(v[key])) throw invalid();
  return v[key].map(parse);
}
function uuid(id: string) {
  if (!isUUID(id)) throw new TypeError("Expected an internal UUID.");
  return encodeURIComponent(id.toLowerCase());
}
export function companyError(error: unknown): string {
  if (error instanceof ServiceError) {
    if (error.status === 401) return "Your session has expired. Please sign in again.";
    if (error.status === 403) return "You do not have access to this company. Reload companies to continue.";
    if (error.status === 404) return "This company or resource is unavailable or archived. Reload companies and try again.";
    if (error.status === 409) return error.message;
    if (error.status === 422) return "Check the company name (1–200 characters) and try again.";
    return "The company service is unavailable. Please retry.";
  }
  return "Could not complete the company action. Check your connection and try again.";
}
export function createCompanyApi(fetcher: typeof fetch = (...args) => apiFetch(...args)): CompanyApi {
  async function request(path: string, signal: AbortSignal, method = "GET", body?: unknown): Promise<unknown> {
    const response = await fetcher(path, { method, signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]), credentials: "same-origin", cache: "no-store",
      ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
    if (!response.ok) {
      // Use operation-specific safe copy; never render arbitrary provider/database error text.
      const message = response.status !== 409 ? "The company request failed." : method === "DELETE" && path.includes("/accounts/")
        ? "This Ads account still has assigned ads. Unassign or reassign them before unlinking the account."
        : method === "PUT" && path.includes("/accounts/") ? "This organic account already belongs to another company. Unlink it there before linking it here."
        : "This ad has an ownership conflict, or the destination company is not linked to its Ads account. Reload assignments and check the destination; no ownership was changed.";
      throw new ServiceError(response.status, message);
    }
    try { return await response.json(); } catch { throw invalid(); }
  }
  const companyPath = (id: string) => `/api/companies/${uuid(id)}`;
  const adPath = (companyId: string, id: string) => `${companyPath(companyId)}/ads/${uuid(id)}`;
  async function ok(path: string, signal: AbortSignal, method: string, body?: unknown) {
    const result = await request(path, signal, method, body);
    if (!object(result) || result.ok !== true) throw invalid();
  }
  return {
    listCompanies: async signal => list(await request("/api/companies?include_archived=true", signal), "companies", wireCompany),
    getCompany: async (id, signal) => wireCompany(await request(companyPath(id), signal)),
    createCompany: async (name, signal) => wireCompany(await request("/api/companies", signal, "POST", { name })),
    renameCompany: async (id, name, signal) => wireCompany(await request(companyPath(id), signal, "PATCH", { name })),
    archiveCompany: async (id, signal) => wireCompany(await request(`${companyPath(id)}/archive`, signal, "POST")),
    restoreCompany: async (id, signal) => wireCompany(await request(`${companyPath(id)}/restore`, signal, "POST")),
    listAvailableMetaAccounts: async signal => list(await request("/api/meta/accounts", signal), "accounts", available),
    linkAccount: async (id, accountId, signal) => wireCompany(await request(`${companyPath(id)}/accounts/${uuid(accountId)}`, signal, "PUT")),
    unlinkAccount: async (id, accountId, signal) => wireCompany(await request(`${companyPath(id)}/accounts/${uuid(accountId)}`, signal, "DELETE")),
    listAssignableAdsContent: async (id, accountId, signal) => list(await request(`${companyPath(id)}/accounts/${uuid(accountId)}/ads`, signal), "ads", ad),
    assignAdsContent: (id, companyId, signal) => ok(adPath(companyId, id), signal, "PUT"),
    unassignAdsContent: (id, companyId, signal) => ok(adPath(companyId, id), signal, "DELETE"),
    reassignAdsContent: (id, from, to, signal) => ok(`${adPath(from, id)}/reassign`, signal, "POST", { target_company_id: uuid(to) }),
  };
}
export const companyApi = createCompanyApi();
