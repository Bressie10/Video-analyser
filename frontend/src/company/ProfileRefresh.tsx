import { useEffect, useRef, useState } from 'react';
import { CompanyScopeBoundary, useCompany, useCompanyStore } from './CompanyProvider';
import { ServiceError } from '../metaLibrary';
import { companyError } from './companyApi';
export function ProfileRefresh() { return <CompanyScopeBoundary><Refresh /></CompanyScopeBoundary>; }
function Refresh() {
  const { activeCompany } = useCompany(); const store = useCompanyStore();
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState(''); const [error, setError] = useState('');
  const lock = useRef(false); const key = useRef<string | undefined>(undefined); const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  async function refresh() {
    const scope = store.captureScope(); if (!scope || lock.current || activeCompany?.archived) return;
    lock.current = true; setBusy(true); setMessage(''); setError(''); key.current ??= crypto.randomUUID();
    const signal = AbortSignal.any([scope.signal, lifetime.current.signal, AbortSignal.timeout(20000)]);
    try {
      const response = await fetch(`/api/companies/${scope.companyId}/profiles/shared/refresh`, { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal, headers: { 'Idempotency-Key': key.current } });
      if (!response.ok) throw new ServiceError(response.status, 'Refresh unavailable.');
      if (scope.isCurrent() && !lifetime.current.signal.aborted) { setMessage('Refresh requested. Company intelligence will update when background processing completes.'); key.current = undefined; }
    } catch (caught) { if (scope.isCurrent() && !lifetime.current.signal.aborted) setError(companyError(caught)); }
    finally { lock.current = false; if (scope.isCurrent() && !lifetime.current.signal.aborted) setBusy(false); }
  }
  return <details className="profile-refresh"><summary>Company intelligence · {activeCompany?.name}</summary><p>Refresh the shared intelligence used for new ideas in the active company.</p><button disabled={busy || activeCompany?.archived} onClick={() => void refresh()}>{busy ? 'Requesting refresh…' : 'Refresh company intelligence'}</button>{message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}</details>;
}
