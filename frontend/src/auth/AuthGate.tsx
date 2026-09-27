import { useEffect, useState, type ReactNode } from 'react';
import { useAuth } from './AuthProvider';
import { AuthLayout, AuthLoading, AuthPage, Redirect } from './AuthPages';
import { apiFetch } from './apiFetch';
import { isUUID } from '../metaLibrary';
import { Button } from '../ui/controls';
function AccessibleWorkspace({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [attempt, retry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await apiFetch('/api/me/companies', { signal: controller.signal });
        if (!response.ok) throw new Error('Companies unavailable');
        const body: unknown = await response.json();
        if (!body || typeof body !== 'object' || !('companies' in body) || !Array.isArray(body.companies)) throw new Error('Invalid companies');
        const companies = body.companies as { id: unknown; archived_at: unknown }[];
        if (companies.some(c => !c || !isUUID(c.id) || !('archived_at' in c))) throw new Error('Invalid companies');
        controller.signal.throwIfAborted();
        try {
          const stored = localStorage.getItem('video-analyzer.active-company-id');
          if (!companies.some(c => c.id === stored?.toLowerCase() && c.archived_at === null)) localStorage.removeItem('video-analyzer.active-company-id');
        } catch { /* CompanyStore reports blocked persistence separately. */ }
        setStatus('ready');
      } catch { if (!controller.signal.aborted) setStatus('error'); }
    })();
    return () => controller.abort();
  }, [attempt]);
  if (status === 'loading') return <AuthLoading />;
  if (status === 'error') return <AuthLayout><h1>Workspace unavailable</h1><p role="alert">We couldn’t load your companies. Please try again.</p><Button onClick={() => { setStatus('loading'); retry(v => v + 1); }}>Retry companies</Button><AccountControl /></AuthLayout>;
  return <>{children}</>;
}
export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  if (auth.loading) return <AuthLoading />;
  if (auth.logoutError) return <AuthLayout><h1>Finish signing out</h1><p role="alert">We couldn’t finish signing out. Check your connection and try again.</p><AccountControl /></AuthLayout>;
  if (['/login', '/signup', '/forgot-password', '/auth/callback'].includes(path)) return <AuthPage path={path} />;
  if (!auth.session) return <Redirect to="/login" />;
  if (auth.recovery) return <Redirect to="/auth/callback?recovery=1" />;
  return <AccessibleWorkspace key={auth.session.user.id}>{children}</AccessibleWorkspace>;
}
export function AccountControl() {
  const { session, signOut } = useAuth();
  const [error, setError] = useState(false);
  return <div className="auth-account"><p>{session?.user.email}</p><Button variant="ghost" onClick={() => { void signOut().catch(() => setError(true)); }}>Sign out</Button>{error && <p role="alert">Couldn’t finish signing out. Please try again.</p>}</div>;
}
