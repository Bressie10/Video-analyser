import { beginMetaAuthorization } from './auth/metaAuthorization';
import { AuthProvider } from './auth/AuthProvider';
import { AuthGate } from './auth/AuthGate';
import { StrictMode, useCallback, useEffect, useRef, useState } from 'react';
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
import { OnboardingProvider, useOnboarding } from './onboarding/OnboardingProvider';
import { OnboardingScreen } from './onboarding/OnboardingScreen';

function OnboardingMount() {
  const store = useCompanyStore();
  const refreshAccess = useCallback(() => store.refreshCompanies(), [store]);
  return <OnboardingProvider onAccessError={refreshAccess}><App /></OnboardingProvider>;
}

export function App() {
  const page = useAppPage();
  const previousWorkflow = useRef<Exclude<typeof page, 'settings'>>('overview');
  if (page !== 'settings') previousWorkflow.current = page;
  const [connected, setConnected] = useState(false);
  const [historyRevision, refreshHistory] = useState(0);
  const store = useCompanyStore();
  const onboarding = useOnboarding();
  const connect = useRef<() => void>(() => {});
  const previous = useRef(false);
  const connectionChanged = useCallback((value: boolean) => {
    setConnected(value);
    if (value !== previous.current && store.getSnapshot().status === 'ready') void store.refreshCompanies();
    if (value !== previous.current) void onboarding.refresh();
    previous.current = value;
  }, [store, onboarding.refresh]);
  useEffect(() => { void onboarding.refresh(); }, [page]);
  const model = useCompanyUI(connected, () => connect.current());
  return <CompanyShell companyUI={model} allowUnlinkedWorkspace showOnboarding={page === 'overview' && onboarding.mode === 'normal'}
    onCompanyCreated={id => { void onboarding.selectCompany(id); }} onAccountLinked={() => { void onboarding.refresh(); }}
    managementPage={page === 'settings'} onManagementChange={open => navigate(open ? 'settings' : previousWorkflow.current)}
    layout={(selector, content, switchCompany, manage) => <AppShell page={page} companySelector={selector} setup={onboarding.data && !onboarding.data.complete && onboarding.data.welcome_seen ? { progress: onboarding.data.progress, onResume: () => { navigate('overview'); onboarding.resume(); } } : undefined}>
      <OnboardingScreen page={page} onManage={manage} onSwitchCompany={switchCompany} onConnect={() => connect.current()} />
      <div hidden={page === 'overview' && (onboarding.mode === 'welcome' || onboarding.mode === 'guided' || onboarding.mode === 'complete')}>{content}</div>
    </AppShell>}
    settings={<><MetaConnection beginAuthorization={beginMetaAuthorization} onSyncStarted={() => {}} disconnected={false} disabled={false} onConnectionChange={connectionChanged} connectAction={connect} /><ProfileRefresh /></>}>
    {onSetup => <>
      <div hidden={page !== 'overview'}><WorkspaceOverview /></div>
      <div hidden={page !== 'content'}><CompanyContent /></div>
      <div hidden={page !== 'generate'}><GenerateIdea onSetup={onSetup} onSaved={() => { refreshHistory(v => v + 1); void onboarding.refresh(); }} /></div>
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
createRoot(root).render(<StrictMode>{legalPage ?? <AuthProvider><AuthGate><CompanyProvider><OnboardingMount /></CompanyProvider></AuthGate></AuthProvider>}</StrictMode>);
