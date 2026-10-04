import { useEffect, useRef, useState, type ReactNode } from 'react';
import { CompanyManagement } from './CompanyManagement';
import { CompanySelector } from './CompanySelector';
import { CompanySwitchGuardProvider, useCompanySwitchReasons } from './CompanySwitchGuard';
import { companyError } from './company/companyApi';
import { Building2 } from 'lucide-react';
import { Button } from './ui/controls';
import { EmptyState, LoadingState } from './ui/layout';
import type { CompanyUIProps } from './companyUI';
import { PlanLimitError, type LimitCode } from './billing/billingApi';
import { useBilling } from './billing/BillingProvider';
import { LimitNotice } from './billing/BillingUI';

export function CompanyEmptyState({ name, onManage, onSkip, skipped, canManage = true }: { canManage?: boolean; name: string; onManage(): void; onSkip(): void; skipped: boolean }) {
  return <section className="welcome" aria-labelledby="company-empty-title">
    <h2 id="company-empty-title">{name} is ready</h2>
    <p>{canManage ? "Your company workspace exists. No accounts are linked yet. You can set up your company now or return later." : "No accounts are linked yet. Ask a company owner to link accounts; you can use the workspace when content is available."}</p>
    {canManage && <button className="primary" onClick={onManage}>Connect/link Meta accounts</button>}{!skipped && <button onClick={onSkip}>Skip for now</button>}
    {skipped && <p>You can link accounts later in Manage companies.</p>}
  </section>;
}
type ShellProps = {
  companyUI: CompanyUIProps;
  children: ReactNode | ((onManage: () => void) => ReactNode);
  allowUnlinkedWorkspace?: boolean;
  settings?: ReactNode;
  managementPage?: boolean;
  onManagementChange?: (open: boolean) => void;
  layout?: (selector: ReactNode, content: ReactNode, switchCompany: (id: string) => void, manage: () => void) => ReactNode;
  showOnboarding?: boolean;
  onCompanyCreated?: (id: string) => void;
  onAccountLinked?: () => void;
};
export function CompanyShell(props: ShellProps) {
  return <CompanySwitchGuardProvider><Shell {...props} /></CompanySwitchGuardProvider>;
}
function Shell({ companyUI: model, children, settings, allowUnlinkedWorkspace = false, managementPage, onManagementChange, layout, showOnboarding = true, onCompanyCreated, onAccountLinked }: ShellProps) {
  const [localManagement, setLocalManagement] = useState(false);
  const management = managementPage ?? localManagement;
  const setManagement = (open: boolean) => { setLocalManagement(open); onManagementChange?.(open); };
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const created = useRef<{ name: string; id: string } | null>(null);
  const [error, setError] = useState('');
  const [limit, setLimit] = useState<LimitCode | null>(null);
  const billing = useBilling();
  const [pending, setPending] = useState<(() => Promise<void>) | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const dialog = useRef<HTMLDialogElement>(null);
  const focusReturn = useRef<HTMLElement | null>(null);
  const reasons = useCompanySwitchReasons();
  const active = model.companies.find(c => c.id === model.activeCompanyId);
  useEffect(() => {
    if (pending) { focusReturn.current = document.activeElement as HTMLElement; dialog.current?.showModal(); }
    else if (dialog.current?.open) { dialog.current.close(); focusReturn.current?.focus(); }
  }, [pending]);
  useEffect(() => { if (management) document.getElementById('companies-title')?.focus(); }, [management]);
  const run = async (action: () => Promise<void> | void) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(''); setLimit(null);
    try { await action(); } catch (caught) { if (caught instanceof PlanLimitError) { setLimit(caught.code); billing.refresh(); } else setError(companyError(caught)); }
    finally { lock.current = false; setBusy(false); }
  };
  const guarded = (action: () => Promise<void>) => {
    if (reasons.unsavedEdits || reasons.generationInProgress) setPending(() => action);
    else void run(action);
  };
  const manage = () => setManagement(true);
  const selector = <CompanySelector companies={model.companies} activeCompanyId={model.activeCompanyId} status={model.status} onRetry={model.onRetry} busy={busy}
      onManage={manage} onSelect={id => { if (id === model.activeCompanyId) return; guarded(async () => { await model.onSwitch(id); if (management) setManagement(false); }); }} />;
  const content = <>
    {model.error && <p className="notice error" role="alert">{model.error}</p>}
    {error && <p className="notice error" role="alert">{error}</p>}
    {limit && <LimitNotice code={limit} billing={billing.state.data} onUpgrade={() => { setManagement(true); requestAnimationFrame(() => document.getElementById('settings-billing')?.scrollIntoView()); }} />}
    {busy && <p role="status">Saving company changes…</p>}
    {management ? <CompanyManagement {...model} busy={busy} run={run} onBack={() => setManagement(false)} onAccountLinked={onAccountLinked} onCreateAndEnter={(name, ownGuard) => {
      // Submitting this create form consumes its own edits; other pending work still requires confirmation.
      const create = async () => {
        if (!created.current || created.current.name !== name) { const company = await model.onCreate(name); created.current = { name, id: company.id }; }
        await model.onSwitch(created.current.id); onCompanyCreated?.(created.current.id); created.current = null; setManagement(false);
      };
      if (reasons.excluding(ownGuard).some(g => g.unsavedEdits || g.generationInProgress)) setPending(() => create); else void run(create);
    }} />
      : model.status === 'loading' ? <LoadingState label="Loading your workspace…" />
      : model.status === 'error' ? <p>Your workspace will appear when companies can be loaded.</p>
      : !active ? <EmptyState title="No company selected" icon={<Building2 size={32} />} action={<Button variant="primary" onClick={manage}>Manage companies</Button>}><p>Create or select a company to start your workspace.</p></EmptyState>
      : active.archived ? <section className="welcome"><h2>{active.name} is archived</h2><p>Restore it in Manage companies or select another company.</p><button onClick={manage}>Manage companies</button></section>
      : !active.hasLinkedAccounts && showOnboarding ? <CompanyEmptyState canManage={active.role === 'owner'} name={active.name} onManage={manage} skipped={skipped.includes(active.id)} onSkip={() => setSkipped(current => [...current, active.id])} /> : null}
    <div hidden={!management}>{settings}</div>
    {(model.status === 'ready' && active && !active.archived && (active.hasLinkedAccounts || allowUnlinkedWorkspace)) && <div hidden={management}>{typeof children === 'function' ? children(manage) : children}</div>}
    <dialog className="company-confirm" ref={dialog} aria-labelledby="company-confirm-title" onCancel={event => { event.preventDefault(); setPending(null); }}>
      <h2 id="company-confirm-title">Switch company?</h2>
      {reasons.unsavedEdits && <p>You have unsaved edits. Switching may discard those edits.</p>}
      {reasons.generationInProgress && <p>A generation is in progress. Switching may interrupt it.</p>}
      <button autoFocus onClick={() => setPending(null)}>Stay here</button>
      <button className="primary" onClick={() => { const action = pending; setPending(null); if (action) void run(action); }}>Continue and switch</button>
    </dialog>
  </>;
  return layout ? layout(selector, content, id => guarded(async () => { await model.onSwitch(id); }), manage) : <>{selector}{content}</>;
}
