import { useEffect, useRef, useState, type ReactNode } from 'react';
import { CompanyManagement } from './CompanyManagement';
import { CompanySelector } from './CompanySelector';
import { CompanySwitchGuardProvider, useCompanySwitchReasons } from './CompanySwitchGuard';
import { companyError } from './company/companyApi';
import type { CompanyUIProps } from './companyUI';

export function CompanyEmptyState({ name, onManage, onSkip, skipped }: { name: string; onManage(): void; onSkip(): void; skipped: boolean }) {
  return <section className="welcome" aria-labelledby="company-empty-title">
    <h2 id="company-empty-title">{name} is ready</h2>
    <p>Your company workspace exists. No accounts are linked yet. You can set up your company now or return later.</p>
    <button className="primary" onClick={onManage}>Connect/link Meta accounts</button>{!skipped && <button onClick={onSkip}>Skip for now</button>}
    {skipped && <p>You can link accounts later in Manage companies.</p>}
  </section>;
}
export function CompanyShell({ companyUI, children }: { companyUI: CompanyUIProps; children: ReactNode | ((onManage: () => void) => ReactNode) }) {
  return <CompanySwitchGuardProvider><Shell companyUI={companyUI}>{children}</Shell></CompanySwitchGuardProvider>;
}
function Shell({ companyUI: model, children }: { companyUI: CompanyUIProps; children: ReactNode | ((onManage: () => void) => ReactNode) }) {
  const [management, setManagement] = useState(false);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const created = useRef<{ name: string; id: string } | null>(null);
  const [error, setError] = useState('');
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
    lock.current = true; setBusy(true); setError('');
    try { await action(); } catch (caught) { setError(companyError(caught)); }
    finally { lock.current = false; setBusy(false); }
  };
  const guarded = (action: () => Promise<void>) => {
    if (reasons.unsavedEdits || reasons.generationInProgress) setPending(() => action);
    else void run(action);
  };
  const manage = () => setManagement(true);
  return <>
    <CompanySelector companies={model.companies} activeCompanyId={model.activeCompanyId} status={model.status} onRetry={model.onRetry} busy={busy}
      onManage={manage} onSelect={id => { if (id === model.activeCompanyId) return; guarded(async () => { await model.onSwitch(id); setManagement(false); }); }} />
    {model.error && <p className="notice error" role="alert">{model.error}</p>}
    {error && <p className="notice error" role="alert">{error}</p>}
    {busy && <p role="status">Saving company changes…</p>}
    {management ? <CompanyManagement {...model} busy={busy} run={run} onBack={() => setManagement(false)} onCreateAndEnter={(name, ownGuard) => {
      // Submitting this create form consumes its own edits; other pending work still requires confirmation.
      const create = async () => {
        if (!created.current || created.current.name !== name) { const company = await model.onCreate(name); created.current = { name, id: company.id }; }
        await model.onSwitch(created.current.id); created.current = null; setManagement(false);
      };
      if (reasons.excluding(ownGuard).some(g => g.unsavedEdits || g.generationInProgress)) setPending(() => create); else void run(create);
    }} />
      : model.status === 'loading' ? <p role="status">Loading your workspace…</p>
      : model.status === 'error' ? <p>Your workspace will appear when companies can be loaded.</p>
      : !active ? <section className="welcome"><h2>No company selected</h2><p>Create or select a company to start your workspace.</p><button onClick={manage}>Manage companies</button></section>
      : active.archived ? <section className="welcome"><h2>{active.name} is archived</h2><p>Restore it in Manage companies or select another company.</p><button onClick={manage}>Manage companies</button></section>
      : !active.hasLinkedAccounts ? <CompanyEmptyState name={active.name} onManage={manage} skipped={skipped.includes(active.id)} onSkip={() => setSkipped(current => [...current, active.id])} /> : null}
    {(model.status === 'ready' && active && !active.archived && active.hasLinkedAccounts) && <div hidden={management}>{typeof children === 'function' ? children(manage) : children}</div>}
    <dialog className="company-confirm" ref={dialog} aria-labelledby="company-confirm-title" onCancel={event => { event.preventDefault(); setPending(null); }}>
      <h2 id="company-confirm-title">Switch company?</h2>
      {reasons.unsavedEdits && <p>You have unsaved edits. Switching may discard those edits.</p>}
      {reasons.generationInProgress && <p>A generation is in progress. Switching may interrupt it.</p>}
      <button autoFocus onClick={() => setPending(null)}>Stay here</button>
      <button className="primary" onClick={() => { const action = pending; setPending(null); if (action) void run(action); }}>Continue and switch</button>
    </dialog>
  </>;
}
