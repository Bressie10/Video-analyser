import { AccountControl } from '../auth/AuthGate';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Menu, X } from 'lucide-react';
import { IconButton } from '../ui/controls';
import { PageHeader } from '../ui/layout';
import { LegalFooter } from '../pages/LegalLayout';
import { navigation, type AppPage } from './navigation';
import './shell.css';

export function AppShell({ page, companySelector, children }: { page: AppPage; companySelector: ReactNode; children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const main = useRef<HTMLElement>(null);
  const previousPage = useRef(page);
  const current = navigation.find(item => item.id === page)!;
  useEffect(() => {
    if (previousPage.current !== page) {
      previousPage.current = page;
      setMobileOpen(false);
      main.current?.focus();
      window.scrollTo(0, 0);
    }
  }, [page]);
  useEffect(() => {
    if (mobileOpen) navigationRef.current?.querySelector<HTMLAnchorElement>('[aria-current="page"]')?.focus();
  }, [mobileOpen]);
  return <div className="app-shell">
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); main.current?.focus(); }}>Skip to content</a>
    <header className="app-header">
      <a className="app-brand" href="#overview" aria-label="ContentMetric overview"><span className="app-brand-mark" aria-hidden="true">C</span><span>ContentMetric</span></a>
      <div className="app-company">{companySelector}</div>
      <IconButton ref={menuButton} label={mobileOpen ? 'Close navigation' : 'Open navigation'} variant="ghost" className="app-menu-toggle" aria-expanded={mobileOpen} aria-controls="app-navigation" onClick={() => setMobileOpen(value => !value)}>{mobileOpen ? <X /> : <Menu />}</IconButton>
    </header>
    <aside className={`app-sidebar ${mobileOpen ? 'is-open' : ''}`} onKeyDown={event => {
      if (event.key === 'Escape' && mobileOpen) { event.preventDefault(); setMobileOpen(false); menuButton.current?.focus(); }
    }}>
      <nav id="app-navigation" aria-label="Primary" ref={navigationRef}>
        {navigation.map(({ id, label, icon: Icon }) => <a key={id} className={`app-nav-link ${id === 'settings' ? 'app-nav-settings' : ''}`} href={`#${id}`} aria-current={page === id ? 'page' : undefined} onClick={() => { setMobileOpen(false); if (page === id) main.current?.focus(); }}><Icon aria-hidden="true" size={20} strokeWidth={1.75} /><span>{label}</span></a>)}
      </nav>
      <AccountControl />
    </aside>
    <div className="app-body">
      <main id="main-content" className="app-main" ref={main} tabIndex={-1}>
        <PageHeader title={current.label} description={current.description} />
        {children}
      </main>
      <LegalFooter />
    </div>
  </div>;
}
