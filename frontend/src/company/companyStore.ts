import { isUUID, ServiceError } from "../metaLibrary";
import { companyRecord, type Company, type CompanyApi } from "./companyApi";

export const ACTIVE_COMPANY_KEY = "video-analyzer.active-company-id";
type Storage = Pick<globalThis.Storage, "getItem" | "setItem" | "removeItem">;
export type CompanySnapshot = Readonly<{
  status: "loading" | "ready" | "error";
  companies: readonly Company[];
  activeCompanyId: string | null;
  scopeVersion: number;
  error: unknown;
  persistenceError: unknown;
}>;
export type CompanyScope = { companyId: string; version: number; signal: AbortSignal; isCurrent: () => boolean };

export class CompanyStore {
  private state: CompanySnapshot = { status: "loading", companies: [], activeCompanyId: null, scopeVersion: 0, error: null, persistenceError: null };
  private listeners = new Set<() => void>();
  private scopeController = new AbortController();
  private loadController?: AbortController;
  private loadVersion = 0;
  private restored = false;
  private selectedId: string | null = null;
  constructor(private api: Pick<CompanyApi, "listCompanies">, private storage: Storage | null) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  /** Synchronous reset notification, also fired on invalidation/access loss. */
  subscribeScope = (listener: () => void) => {
    let version = this.state.scopeVersion;
    return this.subscribe(() => { if (version !== this.state.scopeVersion) { version = this.state.scopeVersion; listener(); } });
  };
  private publish(patch: Partial<CompanySnapshot>, invalidate = false) {
    if (invalidate) { this.scopeController.abort(); this.scopeController = new AbortController(); }
    this.state = Object.freeze({ ...this.state, ...patch, scopeVersion: this.state.scopeVersion + Number(invalidate) });
    for (const listener of this.listeners) listener();
  }
  private persist(id: string | null) {
    try {
      if (id === null) this.storage?.removeItem(ACTIVE_COMPANY_KEY);
      else this.storage?.setItem(ACTIVE_COMPANY_KEY, id);
      return null;
    } catch (error) { return error; }
  }
  /** Hides scoped data while revalidating; network errors retain only the UUID for retry. */
  refreshCompanies = async () => {
    const version = ++this.loadVersion;
    this.loadController?.abort();
    const controller = this.loadController = new AbortController();
    this.publish({ status: "loading", activeCompanyId: null, error: null }, true);
    try {
      const companies = Object.freeze((await this.api.listCompanies(controller.signal)).map(companyRecord));
      if (version !== this.loadVersion || controller.signal.aborted) return;
      let persistenceError: unknown = null;
      if (!this.restored) {
        // Never consult persisted selection before the accessible list has loaded.
        try { this.selectedId = this.storage?.getItem(ACTIVE_COMPANY_KEY) ?? null; }
        catch (error) { persistenceError = error; }
        this.restored = true;
      }
      const id = isUUID(this.selectedId) ? this.selectedId.toLowerCase() : null;
      this.selectedId = companies.some((company) => company.id === id && !company.archived) ? id : null;
      persistenceError = this.persist(this.selectedId) ?? persistenceError;
      this.publish({ status: "ready", companies, activeCompanyId: this.selectedId, error: null, persistenceError }, true);
    } catch (error) {
      if (version !== this.loadVersion || controller.signal.aborted) return;
      const denied = error instanceof ServiceError && [401, 403, 404].includes(error.status);
      if (denied) { this.selectedId = null; this.restored = true; }
      this.publish({ status: "error", companies: [], activeCompanyId: null, error,
        persistenceError: denied ? this.persist(null) : this.state.persistenceError }, true);
    }
  };
  setActiveCompany = (id: string | null) => {
    if (this.state.status !== "ready") throw new Error("Companies must be validated before selection.");
    const normalized = id === null ? null : isUUID(id) ? id.toLowerCase() : "";
    if (normalized !== null && !this.state.companies.some((c) => c.id === normalized && !c.archived)) throw new Error("Company is unavailable.");
    if (normalized === this.state.activeCompanyId) return;
    this.selectedId = normalized;
    this.publish({ activeCompanyId: normalized, persistenceError: this.persist(normalized) }, true);
  };
  /** Pass a successful create/rename/archive/restore response, never a speculative record. */
  acceptCompany = (value: Company, select = false) => {
    const company = companyRecord(value);
    if (select && company.archived) throw new Error("Archived companies cannot be selected.");
    if (this.state.status !== "ready") throw new Error("Reload companies before applying a mutation.");
    const companies = Object.freeze([...this.state.companies.filter((c) => c.id !== company.id), company]);
    const nextId = select ? company.id : company.archived && this.selectedId === company.id ? null : this.selectedId;
    const changed = nextId !== this.selectedId;
    this.selectedId = nextId;
    this.publish({ companies, activeCompanyId: nextId, persistenceError: this.persist(nextId) }, changed);
  };
  invalidateCompanyScope = () => this.publish({}, true);
  captureScope = (): CompanyScope | null => {
    const { status, activeCompanyId, scopeVersion } = this.state;
    if (status !== "ready" || !activeCompanyId) return null;
    const signal = this.scopeController.signal;
    return { companyId: activeCompanyId, version: scopeVersion, signal,
      isCurrent: () => !signal.aborted && this.state.status === "ready" && this.state.scopeVersion === scopeVersion && this.state.activeCompanyId === activeCompanyId };
  };
  /** Only report failures for the captured scope; stale failures cannot clear a new company. */
  handleScopeError = async (scope: CompanyScope, error: unknown) => {
    if (!scope.isCurrent() || !(error instanceof ServiceError)) return;
    if ([401, 403, 404].includes(error.status)) {
      ++this.loadVersion; this.loadController?.abort(); this.selectedId = null; this.restored = true;
      this.publish({ status: "error", companies: [], activeCompanyId: null, error, persistenceError: this.persist(null) }, true);
    }
  };
  cancelPending = () => { ++this.loadVersion; this.loadController?.abort(); this.scopeController.abort(); };
}
