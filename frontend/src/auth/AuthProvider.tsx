import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type { Session } from '@supabase/supabase-js';
import { authClient } from './authClient';
import { clearAuthRequests, onSessionExpired } from './apiFetch';

const COMPANY_KEY = 'video-analyzer.active-company-id';
function clearSelection() { try { localStorage.removeItem(COMPANY_KEY); } catch { /* Store reports persistence failures separately. */ } }
type AuthState = { session: Session | null; loading: boolean; recovery: boolean; logoutError: boolean; signOut: () => Promise<void> };
const Context = createContext<AuthState | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState({ session: null as Session | null, loading: true, recovery: false, logoutError: false });
  const signingOut = useRef(false);
  const identity = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    let active = true;
    let eventRevision = 0;
    function accept(session: Session | null, recovery = false) {
      if (!active || (signingOut.current && session)) return;
      if (identity.current !== undefined && identity.current !== (session?.user.id ?? null)) { clearSelection(); clearAuthRequests(); }
      if (!session) clearSelection();
      identity.current = session?.user.id ?? null;
      setState(previous => ({ session, loading: false, recovery: recovery || (!!session && previous.recovery), logoutError: false }));
    }
    const unsubscribe = authClient.subscribe((event, session) => { eventRevision++; accept(session, event === 'PASSWORD_RECOVERY'); });
    const initialRevision = eventRevision;
    void authClient.getSession().then(session => { if (initialRevision === eventRevision) accept(session); }).catch(() => { if (initialRevision === eventRevision) accept(null); });
    const stop = onSessionExpired(() => { void signOut(); });
    return () => { active = false; unsubscribe(); stop(); };
  }, []);
  async function signOut() {
    // Hide and cancel private state immediately, even when network logout fails.
    signingOut.current = true;
    clearSelection(); clearAuthRequests(); identity.current = null;
    setState({ session: null, loading: true, recovery: false, logoutError: false });
    try {
      await authClient.signOut();
      signingOut.current = false;
      setState({ session: null, loading: false, recovery: false, logoutError: false });
    } catch {
      setState({ session: null, loading: false, recovery: false, logoutError: true });
    }
  }
  return <Context.Provider value={{ ...state, signOut }}>{children}</Context.Provider>;
}
export function useAuth() { const value = useContext(Context); if (!value) throw new Error('AuthProvider is required.'); return value; }
