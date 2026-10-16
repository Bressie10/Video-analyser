import { useAuth } from '../auth/AuthProvider';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { X, ChevronRight, UserRound } from 'lucide-react';
import { IconButton } from '../ui/controls';
import { PageHeader } from '../ui/layout';
import { LegalFooter } from '../pages/LegalLayout';
import { navigate, navigateSettings, navigation, pageHref, useSettingsSection, type AppPage } from './navigation';
import { comparisonScroll } from '../creativeAnalysis/handoff';
import './shell.css';
import './v9.css';

export function AppShell({ page, companySelector, children, setup }: { page: AppPage; companySelector: ReactNode; children: ReactNode; setup?: { progress: number; onResume(): void } }) {
  const { session, signOut } = useAuth();
  const [signOutError, setSignOutError] = useState(false);
  const subsection = useSettingsSection();
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const main = useRef<HTMLElement>(null);
  const previousPage = useRef(`${page}:${subsection ?? ''}`);
  const current = navigation.find(item => item.id === page) ?? { label: page === 'content-detail' ? 'Content Analysis' : 'Creative Analysis', description: '' };
  useEffect(() => {
    const location = `${page}:${subsection ?? ''}`;
    if (previousPage.current !== location) {
      const fromCreative = previousPage.current.startsWith('creative:');
      previousPage.current = location;
      setMobileOpen(false);
      main.current?.focus();
      window.scrollTo(0, page === 'intelligence' && fromCreative ? comparisonScroll() : 0);
    }
  }, [page, subsection]);
  useEffect(() => {
    if (mobileOpen) navigationRef.current?.querySelector<HTMLAnchorElement>('[aria-current="page"]')?.focus();
  }, [mobileOpen]);
  return <div className="app-shell">
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); main.current?.focus(); }}>Skip to content</a>
    <header className="app-header">
      <a className="app-brand" href="/#overview" onClick={event => { event.preventDefault(); navigate('overview'); }} aria-label="ContentMetric home"><span>Content</span><span>Metric</span></a>
      <div className="app-company">{companySelector}</div>
      <IconButton ref={menuButton} label={mobileOpen ? 'Close navigation' : 'Open navigation'} variant="ghost" className="app-menu-toggle" aria-expanded={mobileOpen} aria-controls="app-navigation" onClick={() => setMobileOpen(value => !value)}>{mobileOpen ? <X /> : <UserRound />}</IconButton>
    </header>
    <aside className={`app-sidebar ${mobileOpen ? 'is-open' : ''}`} onKeyDown={event => {
      if (event.key === 'Escape' && mobileOpen) { event.preventDefault(); setMobileOpen(false); menuButton.current?.focus(); }
    }}>
      <nav id="app-navigation" aria-label="Primary" ref={navigationRef}>
        {navigation.map(({ id, label, icon: Icon }) => <a key={id} className={`app-nav-link ${id === 'settings' ? 'app-nav-settings' : ''}`} href={pageHref(id)} aria-current={page === id || page === 'content-detail' && id === 'content' ? 'page' : undefined} onClick={event => { event.preventDefault(); setMobileOpen(false); navigate(id); if (page === id) main.current?.focus(); }}><Icon aria-hidden="true" size={20} strokeWidth={1.75} /><span>{label}</span></a>)}
      </nav>
      {setup && <button className="app-setup-link" type="button" onClick={() => { setMobileOpen(false); setup.onResume(); }}><span>Finish setup</span><strong>{setup.progress}%</strong></button>}
      <details className="app-profile" open={mobileOpen || undefined}><summary aria-label="Account menu"><span className="app-profile-avatar" aria-hidden="true">{session?.user.email?.slice(0, 2).toUpperCase() || 'CM'}</span><span className="app-profile-info"><strong>Account</strong></span><ChevronRight size={17} aria-hidden="true" /></summary><div className="app-profile-actions"><a href="/settings/account" onClick={event => { event.preventDefault(); setMobileOpen(false); navigateSettings('account'); }}>Account settings</a><button type="button" onClick={() => { void signOut().catch(() => setSignOutError(true)); }}>Sign out</button>{signOutError && <p role="alert">Couldn’t finish signing out. Please try again.</p>}</div></details>
    </aside>
    <div className="app-body">
      <main id="main-content" className="app-main" ref={main} tabIndex={-1}>
        {page !== 'creative' && page !== 'content-detail' && <PageHeader title={current.label} description={current.description} />}
        {children}
      </main>
      <LegalFooter />
    </div>
    <nav className="app-mobile-bottom-nav" aria-label="Mobile primary">
      {(['overview', 'content', 'intelligence', 'ideas', 'settings'] as const).map(id => {
        const item = navigation.find(entry => entry.id === id)!;
        const Icon = item.icon;
        return <a key={id} href={pageHref(id)} onClick={event => { event.preventDefault(); navigate(id); }} aria-current={page === id || page === 'content-detail' && id === 'content' ? 'page' : undefined}>
          <Icon size={19} strokeWidth={1.8} aria-hidden="true" /><span>{id === 'overview' ? 'Home' : item.label}</span>
        </a>;
      })}
    </nav>
  </div>;
}
