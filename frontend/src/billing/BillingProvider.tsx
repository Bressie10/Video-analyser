import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useCompany, useCompanyStore } from '../company/CompanyProvider';
import { billingApi, type Billing } from './billingApi';

const RETURN_KEY = 'contentmetric.billing-return';
export type BillingState = { status: 'idle' | 'loading' | 'success' | 'error'; data?: Billing; error?: unknown };
type BillingContext = { state: BillingState; refresh(): void; markReturn(kind: 'checkout' | 'portal', companyId: string): void; returning: 'checkout' | 'portal' | null };
const Context = createContext<BillingContext | null>(null);
// Standalone company component fixtures have no authenticated workspace provider.
const standalone: BillingContext = { state: { status: 'idle' }, refresh() {}, markReturn() {}, returning: null };
function pendingReturn(companyId: string): 'checkout' | 'portal' | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(RETURN_KEY) ?? 'null');
    return value?.companyId === companyId && Date.now() - value.at < 15 * 60_000 && (value.kind === 'checkout' || value.kind === 'portal') ? value.kind : null;
  } catch { return null; }
}
export function BillingProvider({ children }: { children: ReactNode }) {
  const { activeCompanyId, scopeVersion, status } = useCompany();
  const store = useCompanyStore();
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<{ key: string; state: BillingState }>();
  const sequence = useRef(0);
  const [returnState, setReturnState] = useState<{ companyId: string; kind: 'checkout' | 'portal' } | null>(null);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  const key = `${activeCompanyId}:${scopeVersion}:${revision}`;
  useEffect(() => {
    if (status !== 'ready' || !activeCompanyId) return;
    const scope = store.captureScope();
    if (!scope) return;
    const controller = new AbortController();
    const signal = AbortSignal.any([scope.signal, controller.signal]);
    const request = ++sequence.current;
    const current = () => !signal.aborted && scope.isCurrent() && sequence.current === request;
    void billingApi.read(activeCompanyId, signal).then(data => {
      if (current()) setResult({ key, state: { status: 'success', data } });
    }).catch(error => {
      if (current()) setResult({ key, state: { status: 'error', error } });
    });
    return () => controller.abort();
  }, [store, status, activeCompanyId, scopeVersion, revision, key]);
  const returning = returnState?.companyId === activeCompanyId ? returnState.kind : null;
  useEffect(() => {
    if (!activeCompanyId) return;
    const kind = pendingReturn(activeCompanyId);
    if (!kind) return;
    setReturnState({ companyId: activeCompanyId, kind });
    // Checkout's return URL is the same for success and cancellation. Only the read can establish Pro.
    const timers = kind === 'checkout' ? [1200, 3000, 6000].map(ms => setTimeout(refresh, ms)) : [1200].map(ms => setTimeout(refresh, ms));
    const done = setTimeout(() => { setReturnState(null); try { sessionStorage.removeItem(RETURN_KEY); } catch { /* storage can be unavailable */ } }, kind === 'checkout' ? 6500 : 1800);
    return () => { timers.forEach(clearTimeout); clearTimeout(done); };
  }, [activeCompanyId, refresh]);
  const markReturn = useCallback((kind: 'checkout' | 'portal', companyId: string) => {
    try { sessionStorage.setItem(RETURN_KEY, JSON.stringify({ kind, companyId, at: Date.now() })); } catch { /* normal billing read still works */ }
  }, []);
  const state: BillingState = status !== 'ready' || !activeCompanyId ? { status: 'idle' }
    : result?.key === key ? result.state : { status: 'loading' };
  return <Context.Provider value={{ state, refresh, markReturn, returning }}>{children}</Context.Provider>;
}
export function useBilling() {
  return useContext(Context) ?? standalone;
}
