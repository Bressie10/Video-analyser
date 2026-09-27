import { apiFetch } from "../auth/apiFetch";
import { useEffect, useRef, useState } from 'react';
import { CompanyScopeBoundary, useCompany, useCompanyStore } from './CompanyProvider';
import { ServiceError } from '../metaLibrary';
import { companyError } from './companyApi';
import { Button } from '../ui/controls';
import '../settings.css';
export function ProfileRefresh() { return <CompanyScopeBoundary><Refresh /></CompanyScopeBoundary>; }
function Refresh() {
  const { activeCompany } = useCompany(); const store = useCompanyStore();
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState(''); const [error, setError] = useState('');
  const [tracking, setTracking] = useState(false); const [status, setStatus] = useState('');
  const [statusError, setStatusError] = useState(''); const [check, setCheck] = useState(0);
  const lock = useRef(false); const key = useRef<string | undefined>(undefined); const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  useEffect(() => {
    if (!tracking) return;
    const scope = store.captureScope(); if (!scope) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const current = () => scope.isCurrent() && !controller.signal.aborted;
    async function poll() {
      try {
        // The list endpoint omits the profile document and immutable evidence.
        const response = await apiFetch(`/api/companies/${scope!.companyId}/profiles`, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.any([scope!.signal, controller.signal, AbortSignal.timeout(20000)]) });
        if (!response.ok) throw new ServiceError(response.status, 'Refresh status unavailable.');
        const result = await response.json();
        const profile = Array.isArray(result.profiles) ? result.profiles.find((p: { scope: string }) => p.scope === 'shared') : null;
        const state = profile?.job?.state;
        if (!['queued', 'running', 'completed', 'failed'].includes(state)) throw new Error('Invalid refresh status.');
        if (!current()) return;
        setStatusError('');
        if (state === 'failed') { setStatus(''); setError('Company intelligence refresh failed. Try again.'); setTracking(false); }
        else if (state === 'completed') {
          setStatus(profile.freshness === 'fresh' ? 'Company intelligence refreshed.' : 'Refresh completed. Company intelligence is awaiting updated source profiles.'); setTracking(false);
        } else {
          setStatus(state === 'queued' ? 'Company intelligence refresh queued.' : 'Company intelligence refresh in progress.');
          timer = setTimeout(() => void poll(), 1000);
        }
      } catch (caught) { if (current()) { setStatus(''); setStatusError(companyError(caught)); } }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [tracking, check, store]);
  async function refresh() {
    const scope = store.captureScope(); if (!scope || lock.current || activeCompany?.archived) return;
    lock.current = true; setBusy(true); setMessage(''); setError(''); setStatus(''); setStatusError(''); key.current ??= crypto.randomUUID();
    const signal = AbortSignal.any([scope.signal, lifetime.current.signal, AbortSignal.timeout(20000)]);
    try {
      const response = await apiFetch(`/api/companies/${scope.companyId}/profiles/shared/refresh`, { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal, headers: { 'Idempotency-Key': key.current } });
      if (!response.ok) throw new ServiceError(response.status, 'Refresh unavailable.');
      if (scope.isCurrent() && !lifetime.current.signal.aborted) { setMessage('Refresh requested.'); setTracking(true); key.current = undefined; }
    } catch (caught) { if (scope.isCurrent() && !lifetime.current.signal.aborted) setError(companyError(caught)); }
    finally { lock.current = false; if (scope.isCurrent() && !lifetime.current.signal.aborted) setBusy(false); }
  }
  return <section className="settings-analysis" aria-labelledby="settings-analysis"><h2 id="settings-analysis" tabIndex={-1}>AI &amp; Analysis</h2><p>Keep the company knowledge used for new ideas up to date.</p><details className="profile-refresh"><summary>Company intelligence · {activeCompany?.name}</summary><p>Refresh the shared intelligence used for new ideas in the active company.</p><Button disabled={busy || tracking || activeCompany?.archived} onClick={() => void refresh()}>{busy ? 'Requesting refresh…' : 'Refresh company intelligence'}</Button>{message && <p role="status">{message}</p>}{status && <p role="status">{status}</p>}{error && <p role="alert">{error}</p>}{statusError && <div role="alert"><p>{statusError}</p><Button onClick={() => { setStatusError(''); setCheck(v => v + 1); }}>Retry refresh status</Button></div>}</details></section>;
}
