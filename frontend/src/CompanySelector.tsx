import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { CompanyUIProps } from './companyUI';

type Props = Pick<CompanyUIProps, 'companies' | 'activeCompanyId' | 'status' | 'onRetry'> & {
  busy: boolean; onSelect(id: string): void; onManage(): void;
};
export function CompanySelector({ companies, activeCompanyId, status, onRetry, busy, onSelect, onManage }: Props) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  const active = companies.find(c => c.id === activeCompanyId);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  useEffect(() => {
    if (!open) return;
    const listener = (event: PointerEvent) => { if (!container.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', listener);
    return () => document.removeEventListener('pointerdown', listener);
  }, [open]);
  return <nav className="company-navigation" aria-label="Company" ref={container} onKeyDown={event => {
    if (event.key === 'Escape' && open) { event.preventDefault(); close(); }
  }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <span className="company-selector-label">Workspace</span>
    <button ref={trigger} aria-expanded={open} aria-controls={id} disabled={busy || status === 'loading'} onClick={() => setOpen(!open)}>
      <span className="company-active-name" title={active?.name}>{status === 'loading' ? 'Loading companies…' : active ? `${active.name}${active.archived ? ' (archived)' : ''}` : 'Select company'}</span><ChevronDown aria-hidden="true" size={16} />
    </button>
    {status === 'error' && <p role="alert">Could not load companies. <button onClick={onRetry}>Retry companies</button></p>}
    {open && <div id={id} className="company-switcher">
      {status === 'ready' && <><p className="muted">Switch company</p>
        <ul>{companies.filter(c => !c.archived).map(company => <li key={company.id}><button aria-current={company.id === activeCompanyId ? 'true' : undefined} disabled={busy} onClick={() => { close(); onSelect(company.id); }}>{company.name}{company.id === activeCompanyId && <span> — Active</span>}</button></li>)}</ul>
        {!companies.some(c => !c.archived) && <p>No active companies yet.</p>}</>}
      <button onClick={() => { close(); onManage(); }}>Manage companies</button>
    </div>}
  </nav>;
}
