import { beginMetaAuthorization } from './auth/metaAuthorization';
import { AuthProvider } from './auth/AuthProvider';
import { AuthGate } from './auth/AuthGate';
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

import { PrivacyPage } from './pages/PrivacyPage';
import { TermsPage } from './pages/TermsPage';
import { DataDeletionPage } from './pages/DataDeletionPage';
import { AppShell } from './shell/AppShell';
import { navigate, useAppPage } from './shell/navigation';
import { WorkspaceOverview } from './shell/WorkspaceOverview';

export function App() {
  const page = useAppPage();
  const previousWorkflow = useRef<Exclude<typeof page, 'settings'>>('overview');
  if (page !== 'settings') previousWorkflow.current = page;
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
  return <CompanyShell companyUI={model} allowUnlinkedWorkspace showOnboarding={page === 'overview'}
    managementPage={page === 'settings'} onManagementChange={open => navigate(open ? 'settings' : previousWorkflow.current)}
    layout={(selector, content) => <AppShell page={page} companySelector={selector}>{content}</AppShell>}
    settings={<><MetaConnection beginAuthorization={beginMetaAuthorization} onSyncStarted={() => {}} disconnected={false} disabled={false} onConnectionChange={connectionChanged} connectAction={connect} /><ProfileRefresh /></>}>
    {onSetup => <>
      <div hidden={page !== 'overview'}><WorkspaceOverview /></div>
      <div hidden={page !== 'content'}><CompanyContent /></div>
      <div hidden={page !== 'generate'}><GenerateIdea onSetup={onSetup} onSaved={() => refreshHistory(v => v + 1)} /></div>
      <div hidden={page !== 'ideas'}><IdeasPage refreshToken={historyRevision} /></div>
    </>}
  </CompanyShell>;
}
const root = document.getElementById('root');
if (!root) throw new Error('Application root element is missing.');
// Resolve public informational routes before mounting providers that load workspace data.
// Plain anchors preserve browser history and direct navigation without a routing dependency.
const pathname = window.location.pathname.replace(/\/+$/, '') || '/';
const legalPage = pathname === '/privacy' ? <PrivacyPage />
  : pathname === '/terms' ? <TermsPage />
  : pathname === '/data-deletion' ? <DataDeletionPage /> : null;
createRoot(root).render(<StrictMode>{legalPage ?? <AuthProvider><AuthGate><CompanyProvider><App /></CompanyProvider></AuthGate></AuthProvider>}</StrictMode>);
