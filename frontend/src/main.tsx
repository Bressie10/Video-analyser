import { StrictMode, useCallback, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MetaConnection } from './MetaConnection';
import { CompanyProvider, CompanyScopeBoundary, useCompanyStore } from './company/CompanyProvider';
import { useCompanyUI } from './company/useCompanyUI';
import { CompanyShell } from './CompanyShell';
import './style.css';

export function App() {
  const [connected, setConnected] = useState(false);
  const store = useCompanyStore();
  const connect = useRef<() => void>(() => {});
  const previous = useRef(false);
  const connectionChanged = useCallback((value: boolean) => {
    setConnected(value);
    if (value && !previous.current) void store.refreshCompanies();
    if (!value && previous.current) void store.refreshCompanies();
    previous.current = value;
  }, [store]);
  const model = useCompanyUI(connected, () => connect.current());
  return <main>
    <header className="page-heading"><p className="eyebrow">Your next video starts here</p><h1>Turn your content into your next idea.</h1></header>
    <MetaConnection onSyncStarted={() => {}} disconnected={false} disabled={false} onConnectionChange={connectionChanged} connectAction={connect} />
    <CompanyShell companyUI={model}>
      <CompanyScopeBoundary>
        <section className="welcome"><h2>Company workspace</h2><p>Your accounts are linked. Company-scoped content browsing will be available in the next update.</p><p>Manage accounts and individual Ads assignments in Manage companies.</p></section>
      </CompanyScopeBoundary>
    </CompanyShell>
  </main>;
}
const root = document.getElementById('root');
if (!root) throw new Error('Application root element is missing.');
createRoot(root).render(<StrictMode><CompanyProvider><App /></CompanyProvider></StrictMode>);
