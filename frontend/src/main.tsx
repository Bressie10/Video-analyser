import { beginMetaAuthorization } from './auth/metaAuthorization';
import { AuthProvider } from './auth/AuthProvider';
import { AuthGate } from './auth/AuthGate';
import { StrictMode, useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MetaConnection, type MetaConnectionStatus } from './MetaConnection';
import { CompanyProvider, useCompanyStore } from './company/CompanyProvider';
import { useCompanyUI } from './company/useCompanyUI';
import { CompanyShell } from './CompanyShell';
import { GenerateIdea } from './generation/GenerateIdea';
import './style.css';
import { CompanyContent } from './company/CompanyContent';
import { ProfileRefresh } from './company/ProfileRefresh';
import { IdeasPage } from './ideas/IdeasPage';
import { IntelligencePage } from './intelligence/IntelligencePage';
import { CreativeAnalysisPage } from './creativeAnalysis/CreativeAnalysisPage';
import { ContentAnalysisPage } from './content/ContentAnalysisPage';

import { PrivacyPage } from './pages/PrivacyPage';
import { TermsPage } from './pages/TermsPage';
import { DataDeletionPage } from './pages/DataDeletionPage';
import { AppShell } from './shell/AppShell';
import { navigate, navigateSettings, settingsSections, useAppPage, useCreativeRef, useContentItemId } from './shell/navigation';
import { WorkspaceOverview } from './shell/WorkspaceOverview';
import { OnboardingProvider, useOnboarding } from './onboarding/OnboardingProvider';
import { OnboardingScreen } from './onboarding/OnboardingScreen';
import { BillingProvider, useBilling } from './billing/BillingProvider';

function OnboardingMount() {
  const store = useCompanyStore();
  const refreshAccess = useCallback(() => store.refreshCompanies(), [store]);
  return <OnboardingProvider onAccessError={refreshAccess}><BillingProvider><App /></BillingProvider></OnboardingProvider>;
}

export function App() {
  const page = useAppPage();
  const creativeRef = useCreativeRef();
  const contentItemId = useContentItemId();
  useEffect(() => {
    const followSettingsLink = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target;
      const anchor = target instanceof Element ? target.closest<HTMLAnchorElement>('a[href^="/settings/"]') : null;
      if (!anchor || anchor.target || anchor.hasAttribute('download')) return;
      const section = anchor.getAttribute('href')?.slice('/settings/'.length);
      const match = settingsSections.find(candidate => candidate === section);
      if (!match) return;
      event.preventDefault();
      navigateSettings(match);
    };
    document.addEventListener('click', followSettingsLink);
    return () => document.removeEventListener('click', followSettingsLink);
  }, []);
  const previousWorkflow = useRef<{ page: Exclude<typeof page, 'settings'>; itemId?: string }>({ page: 'overview' });
  if (page !== 'settings') previousWorkflow.current = { page, itemId: contentItemId ?? creativeRef ?? undefined };
  const [connected, setConnected] = useState(false);
  const [metaStatus, setMetaStatus] = useState<MetaConnectionStatus>('checking');
  const [historyRevision, refreshHistory] = useState(0);
  const [analysisRevision, refreshAnalysisSources] = useState(0);
  const store = useCompanyStore();
  const onboarding = useOnboarding();
  const billing = useBilling();
  const connect = useRef<() => void>(() => {});
  const previous = useRef(false);
  const connectionChanged = useCallback((value: boolean) => {
    setConnected(value);
    if (value !== previous.current && store.getSnapshot().status === 'ready') void store.refreshCompanies();
    if (value !== previous.current) { void onboarding.refresh(); billing.refresh(); }
    previous.current = value;
  }, [store, onboarding.refresh, billing.refresh]);
  useEffect(() => { void onboarding.refresh(); }, [page]);
  const model = useCompanyUI(connected, () => connect.current());
  return <CompanyShell companyUI={model} allowUnlinkedWorkspace showOnboarding={page === 'overview' && onboarding.mode === 'normal'}
    onCompanyCreated={id => { if (onboarding.mode === 'guided') void onboarding.selectCompany(id); else void onboarding.refresh(); billing.refresh(); }} onAccountLinked={() => { void onboarding.refresh(); billing.refresh(); }}
    managementPage={page === 'settings'} onManagementChange={open => open ? navigateSettings('workspace') : navigate(previousWorkflow.current.page, previousWorkflow.current.itemId)}
    layout={(selector, content, switchCompany, manage) => <AppShell page={page} companySelector={selector} setup={onboarding.data && !onboarding.data.complete && onboarding.data.welcome_seen ? { progress: onboarding.data.progress, onResume: () => { navigate('overview'); onboarding.resume(); } } : undefined}>
      <OnboardingScreen page={page} onManage={manage} onSwitchCompany={switchCompany} onConnect={() => connect.current()} />
      <div hidden={page === 'overview' && (onboarding.mode === 'welcome' || onboarding.mode === 'guided' || onboarding.mode === 'complete')}>{content}</div>
    </AppShell>}
    settings={{ connections: <MetaConnection beginAuthorization={beginMetaAuthorization} onSyncStarted={() => {}} disconnected={false} disabled={false} onConnectionChange={connectionChanged} onStatusChange={setMetaStatus} connectAction={connect} />, analysis: <ProfileRefresh /> }}>
    {onSetup => <>
      <div hidden={page !== 'overview'}>{onboarding.mode === 'normal' && <WorkspaceOverview metaStatus={metaStatus} />}</div>
      <div hidden={page !== 'content'}><CompanyContent onAnalysisChange={() => { refreshAnalysisSources(v => v + 1); void onboarding.refresh(); billing.refresh(); }} /></div>
      <div hidden={page !== 'intelligence'}><IntelligencePage /></div>
      {page === 'creative' && creativeRef && <CreativeAnalysisPage creativeRef={creativeRef} />}
      {page === 'content-detail' && contentItemId && <ContentAnalysisPage itemId={contentItemId} />}
      <div hidden={page !== 'generate'}><GenerateIdea onSetup={onSetup} refreshToken={analysisRevision} onSaved={() => { refreshHistory(v => v + 1); void onboarding.refresh(); billing.refresh(); }} /></div>
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
