import { AccountControl } from '../auth/AuthGate';
import { useAuth } from '../auth/AuthProvider';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { X, ChevronRight, UserRound } from 'lucide-react';
import { IconButton } from '../ui/controls';
import { PageHeader } from '../ui/layout';
import { LegalFooter } from '../pages/LegalLayout';
import { navigation, type AppPage } from './navigation';
import { comparisonScroll } from '../creativeAnalysis/handoff';
import './shell.css';
import './v9.css';

export function AppShell({ page, companySelector, children, setup }: { page: AppPage; companySelector: ReactNode; children: ReactNode; setup?: { progress: number; onResume(): void } }) {
  const { session } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const main = useRef<HTMLElement>(null);
  const previousPage = useRef(page);
  const current = navigation.find(item => item.id === page) ?? { label: 'Creative Analysis', description: '' };
  useEffect(() => {
    if (previousPage.current !== page) {
      const fromCreative = previousPage.current === 'creative';
      previousPage.current = page;
      setMobileOpen(false);
      main.current?.focus();
      window.scrollTo(0, page === 'intelligence' && fromCreative ? comparisonScroll() : 0);
    }
  }, [page]);
  useEffect(() => {
    if (mobileOpen) navigationRef.current?.querySelector<HTMLAnchorElement>('[aria-current="page"]')?.focus();
  }, [mobileOpen]);
  return <div className="app-shell">
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); main.current?.focus(); }}>Skip to content</a>
    <header className="app-header">
      <a className="app-brand" href="#overview" aria-label="ContentMetric home"><span>Content</span><span>Metric</span></a>
      <div className="app-company">{companySelector}</div>
      <IconButton ref={menuButton} label={mobileOpen ? 'Close navigation' : 'Open navigation'} variant="ghost" className="app-menu-toggle" aria-expanded={mobileOpen} aria-controls="app-navigation" onClick={() => setMobileOpen(value => !value)}>{mobileOpen ? <X /> : <UserRound />}</IconButton>
    </header>
    <aside className={`app-sidebar ${mobileOpen ? 'is-open' : ''}`} onKeyDown={event => {
      if (event.key === 'Escape' && mobileOpen) { event.preventDefault(); setMobileOpen(false); menuButton.current?.focus(); }
    }}>
      <nav id="app-navigation" aria-label="Primary" ref={navigationRef}>
        {navigation.map(({ id, label, icon: Icon }) => <a key={id} className={`app-nav-link ${id === 'settings' ? 'app-nav-settings' : ''}`} href={`#${id}`} aria-current={page === id ? 'page' : undefined} onClick={() => { setMobileOpen(false); if (page === id) main.current?.focus(); }}><Icon aria-hidden="true" size={20} strokeWidth={1.75} /><span>{label}</span></a>)}
      </nav>
      {setup && <button className="app-setup-link" type="button" onClick={() => { setMobileOpen(false); setup.onResume(); }}><span>Finish setup</span><strong>{setup.progress}%</strong></button>}
      <details className="app-profile" open={mobileOpen || undefined}><summary aria-label="Account menu"><span className="app-profile-avatar" aria-hidden="true">{session?.user.email?.slice(0, 2).toUpperCase() || 'CM'}</span><span className="app-profile-info"><strong>{session?.user.email?.split('@')[0] || 'Account'}</strong><small>Account</small></span><ChevronRight size={17} aria-hidden="true" /></summary><div className="app-profile-actions"><a href="#settings">Account settings</a><AccountControl /></div></details>
    </aside>
    <div className="app-body">
      <main id="main-content" className="app-main" ref={main} tabIndex={-1}>
        {page !== 'creative' && <PageHeader title={current.label} description={current.description} />}
        {children}
      </main>
      <LegalFooter />
    </div>
    <nav className="app-mobile-bottom-nav" aria-label="Mobile primary">
      {(['overview', 'intelligence', 'content', 'ideas'] as const).map(id => {
        const item = navigation.find(entry => entry.id === id)!;
        const Icon = item.icon;
        return <a key={id} href={`#${id}`} aria-current={page === id ? 'page' : undefined}>
          <Icon size={19} strokeWidth={1.8} aria-hidden="true" /><span>{id === 'overview' ? 'Home' : item.label}</span>
        </a>;
      })}
    </nav>
  </div>;
}
