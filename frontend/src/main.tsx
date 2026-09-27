import { StrictMode, useCallback, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MetaConnection } from './MetaConnection';
import { CompanyProvider, useCompanyStore } from './company/CompanyProvider';
import { useCompanyUI } from './company/useCompanyUI';
import { CompanyShell } from './CompanyShell';
import { GenerateIdea } from './generation/GenerateIdea';
import './style.css';
import { CompanyContent } from './company/CompanyContent';
import { ProfileRefresh } from './company/ProfileRefresh';
import { IdeasPage } from './ideas/IdeasPage';

export function App() {
  const [connected, setConnected] = useState(false);
  const [historyRevision, refreshHistory] = useState(0);
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
    <CompanyShell companyUI={model} allowUnlinkedWorkspace settings={<ProfileRefresh />}>
      {onSetup => <><CompanyContent /><GenerateIdea onSetup={onSetup} onSaved={() => refreshHistory(v => v + 1)} /><IdeasPage refreshToken={historyRevision} /></>}
    </CompanyShell>
  </main>;
}
const root = document.getElementById('root');
if (!root) throw new Error('Application root element is missing.');
createRoot(root).render(<StrictMode><CompanyProvider><App /></CompanyProvider></StrictMode>);
