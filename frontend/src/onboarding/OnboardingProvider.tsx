import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Button } from '../ui/controls';
import { Alert, LoadingState } from '../ui/layout';
import { OnboardingError, onboardingApi, type Onboarding } from './onboardingApi';

type State = { data: Onboarding | null; mode: 'normal' | 'welcome' | 'guided' | 'complete'; busy: boolean; error: string;
  refresh(): Promise<Onboarding | null>; start(): Promise<void>; skip(): Promise<void>; resume(): void; leave(): void; selectCompany(id: string): Promise<void> };
const Context = createContext<State | null>(null);
export function useOnboarding() { const value = useContext(Context); if (!value) throw new Error('OnboardingProvider is required.'); return value; }
function message(error: unknown) {
  if (error instanceof OnboardingError && error.status === 403) return 'You do not have access to this setup action. Review your available companies and try again.';
  if (error instanceof OnboardingError && error.status === 404) return 'This company is no longer available. Choose another accessible company.';
  return 'Setup could not be updated. Please try again.';
}
export function OnboardingProvider({ children, onAccessError }: { children: ReactNode; onAccessError?: () => Promise<unknown> }) {
  const [data, setData] = useState<Onboarding | null>(null);
  const [mode, setMode] = useState<State['mode']>('normal');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const revision = useRef(0);
  const mounted = useRef(true);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const refresh = useCallback(async () => {
    const request = ++revision.current;
    try {
      const next = await onboardingApi.get();
      if (!mounted.current || request !== revision.current) return null;
      setData(next); setError(''); setLoading(false);
      if (next.complete) setMode(current => current === 'guided' || current === 'complete' ? 'complete' : 'normal');
      else if (modeRef.current === 'complete') setMode('normal');
      else if (!next.welcome_seen && !next.skipped && next.progress === 0) setMode('welcome');
      return next;
    } catch (caught) {
      if (!mounted.current || request !== revision.current) return null;
      setLoading(false); setError(message(caught));
      if (caught instanceof OnboardingError && [403, 404].includes(caught.status)) void onAccessError?.();
      return null;
    }
  }, [onAccessError]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const onFocus = () => { if (document.visibilityState === 'visible') void refresh(); };
    document.addEventListener('visibilitychange', onFocus);
    return () => { mounted.current = false; ++revision.current; document.removeEventListener('visibilitychange', onFocus); };
  }, [refresh]);
  async function action(run: () => Promise<void>, destination: State['mode']) {
    if (busy) return;
    setBusy(true); setError('');
    try { await run(); const next = await refresh(); if (mounted.current && next) setMode(next.complete ? 'complete' : destination); }
    catch (caught) { if (mounted.current) { setError(message(caught)); if (caught instanceof OnboardingError && [403, 404].includes(caught.status)) void onAccessError?.(); } }
    finally { if (mounted.current) setBusy(false); }
  }
  const value: State = { data, mode, busy, error, refresh,
    start: () => action(() => onboardingApi.welcome(), 'guided'),
    skip: () => action(async () => { if (!data?.welcome_seen) await onboardingApi.welcome(); await onboardingApi.skip(); }, 'normal'),
    resume: () => { setError(''); setMode('guided'); },
    leave: () => { setError(''); setMode('normal'); },
    selectCompany: id => action(() => onboardingApi.company(id), 'guided') };
  if (loading) return <div className="onboarding-gate"><LoadingState label="Loading your setup progress…" /></div>;
  return <Context.Provider value={value}>{children}{!data && <div className="onboarding-status"><Alert tone="danger"><p>{error || 'Setup is unavailable.'}</p><Button onClick={() => { setLoading(true); void refresh(); }}>Retry setup</Button></Alert></div>}</Context.Provider>;
}
