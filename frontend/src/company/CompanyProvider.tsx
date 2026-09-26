import { createContext, Fragment, useContext, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { companyApi } from "./companyApi";
import { CompanyStore } from "./companyStore";

const Context = createContext<CompanyStore | null>(null);
function browserStore() {
  let storage: Storage | null = null;
  try { storage = window.localStorage; } catch { /* Blocked storage: session-only state. */ }
  return new CompanyStore(companyApi, storage);
}
export function CompanyProvider({ children, store: supplied }: { children: ReactNode; store?: CompanyStore }) {
  const [store] = useState(() => supplied ?? browserStore());
  useEffect(() => {
    let disposed = false;
    // StrictMode replays setup/cleanup before this microtask; avoid an unused request.
    queueMicrotask(() => { if (!disposed) void store.refreshCompanies(); });
    return () => { disposed = true; store.cancelPending(); };
  }, [store]);
  return <Context.Provider value={store}>{children}</Context.Provider>;
}
export function useCompanyStore() {
  const store = useContext(Context);
  if (!store) throw new Error("CompanyProvider is required.");
  return store;
}
export function useCompany() {
  const store = useCompanyStore();
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  return { ...snapshot, activeCompany: snapshot.companies.find((c) => c.id === snapshot.activeCompanyId) ?? null,
    setActiveCompany: store.setActiveCompany, refreshCompanies: store.refreshCompanies, acceptCompany: store.acceptCompany,
    invalidateCompanyScope: store.invalidateCompanyScope };
}
/** Mount company-specific UI inside this boundary. Key changes reset all local selections. */
export function CompanyScopeBoundary({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  const { status, activeCompanyId, scopeVersion } = useCompany();
  return status === "ready" && activeCompanyId
    ? <Fragment key={`${activeCompanyId}:${scopeVersion}`}>{children}</Fragment> : <>{fallback}</>;
}
export type CompanyQuery<T> = { status: "idle" | "loading" | "success" | "error"; data: T | undefined; error: unknown };
/** Memoize load with useCallback. Changing it refetches; include filters in queryKey. */
export function useCompanyQuery<T>(queryKey: string, load: (companyId: string, signal: AbortSignal) => Promise<T>): CompanyQuery<T> {
  const store = useCompanyStore();
  const { status, activeCompanyId, scopeVersion } = useCompany();
  const [result, setResult] = useState<{ version: number; key: string; load: typeof load; value: CompanyQuery<T> }>();
  const sequence = useRef(0);
  useEffect(() => {
    const scope = store.captureScope();
    const request = ++sequence.current;
    if (!scope) return;
    const controller = new AbortController();
    const signal = AbortSignal.any([scope.signal, controller.signal]);
    const current = () => !signal.aborted && scope.isCurrent() && sequence.current === request;
    const commit = (value: CompanyQuery<T>) => { if (current()) setResult({ version: scope.version, key: queryKey, load, value }); };
    commit({ status: "loading", data: undefined, error: null });
    void Promise.resolve().then(() => {
      if (!current()) return;
      return load(scope.companyId, signal).then((data) => commit({ status: "success", data, error: null }));
    }).catch((error: unknown) => {
      if (!current()) return;
      commit({ status: "error", data: undefined, error });
      void store.handleScopeError(scope, error);
    });
    return () => controller.abort();
  }, [store, status, activeCompanyId, scopeVersion, queryKey, load]);
  // Render-time guard closes the interval before effect cleanup on a switch.
  if (status !== "ready" || !activeCompanyId) return { status: "idle", data: undefined, error: null };
  return result?.version === scopeVersion && result.key === queryKey && result.load === load
    ? result.value : { status: "loading", data: undefined, error: null };
}
