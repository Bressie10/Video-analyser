import { useEffect, useState } from 'react';
import type { Company, CompanyUIProps } from './companyUI';
import { useCompanySwitchGuard } from './CompanySwitchGuard';

type Props = CompanyUIProps & { busy: boolean; run(action: () => Promise<void> | void): void; onCreateAndEnter(name: string, ownGuard: string): void; onBack(): void };
function Rename({ company, busy, onSave }: { company: Company; busy: boolean; onSave(name: string): void }) {
  const [name, setName] = useState(company.name);
  useCompanySwitchGuard({ unsavedEdits: name !== company.name });
  return <form className="company-form" onSubmit={event => { event.preventDefault(); if (name.trim()) onSave(name.trim()); }}>
    <label>Company name<input value={name} maxLength={200} required disabled={busy || company.archived} onChange={event => setName(event.target.value)} /></label>
    <button disabled={busy || company.archived || !name.trim() || name.trim() === company.name}>Save name</button>
  </form>;
}
export function CompanyManagement(props: Props) {
  const [name, setName] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [inspectedId, setInspectedId] = useState(props.activeCompanyId);
  const company = props.companies.find(c => c.id === inspectedId);
  const createGuard = useCompanySwitchGuard({ unsavedEdits: !!name.trim() });
  useEffect(() => { props.onInspect(inspectedId); return () => props.onInspect(null); }, [inspectedId, props.onInspect]);
  const discoveryStatus = props.discoveryCompanyId === company?.id ? props.discoveryStatus : 'loading';
  const disabled = props.busy || props.status !== 'ready';
  return <section aria-labelledby="companies-title">
    <div className="section-heading"><h2 id="companies-title" tabIndex={-1}>Manage companies</h2><button disabled={props.busy} onClick={props.onBack}>Back to workspace</button></div>
    <p>Companies keep your content and ideas together. Meta is connected once; assign discovered accounts and ads to each company here.</p>
    <form className="company-form" onSubmit={event => { event.preventDefault(); if (name.trim()) props.onCreateAndEnter(name.trim(), createGuard); }}>
      <label>New company name<input required maxLength={200} value={name} disabled={disabled} onChange={event => setName(event.target.value)} /></label>
      <button className="primary" disabled={disabled || !name.trim()}>Create company</button>
    </form>
    <label className="source-choice"><input type="checkbox" checked={showArchived} onChange={event => setShowArchived(event.target.checked)} />Show archived companies</label>
    <ul className="company-list">{props.companies.filter(c => showArchived || !c.archived).map(c => <li key={c.id}>
      <button aria-pressed={company?.id === c.id} onClick={() => setInspectedId(c.id)} disabled={props.busy}>{c.name}{c.archived ? ' — Archived' : c.id === props.activeCompanyId ? ' — Active' : ''}</button>
    </li>)}</ul>
    {!props.companies.some(c => showArchived || !c.archived) && <p>No {showArchived ? '' : 'active '}companies yet. Create a company to get started.</p>}
    {props.status === 'ready' && company && <section aria-label={`Manage ${company.name}`}>
      <h3>{company.name}</h3>
      {company.archived && <p className="notice">Archived — unavailable for normal work. Restore this company to use it again.</p>}
      <Rename key={`${company.id}:${company.name}`} company={company} busy={disabled} onSave={value => props.run(() => props.onRename(company.id, value))} />
      <button disabled={disabled} onClick={() => props.run(() => company.archived ? props.onRestore(company.id) : props.onArchive(company.id))}>{company.archived ? 'Restore company' : 'Archive company'}</button>
      <h3>Linked accounts</h3>
      <button disabled={disabled || discoveryStatus === 'loading'} onClick={props.onRetryDiscovery}>Refresh available accounts</button>
      {!props.metaConnected && <p>Connect Meta once to discover accounts for all your companies. <button disabled={disabled || company.archived} onClick={() => props.run(props.onConnectMeta)}>Connect Meta</button></p>}
      {discoveryStatus === 'loading' && <p role="status">Loading available accounts and ads…</p>}
      {discoveryStatus === 'error' && <p role="alert">{props.discoveryError ?? "Could not load accounts and ads."} <button onClick={props.onRetryDiscovery}>Retry accounts</button></p>}
      {discoveryStatus === 'ready' && <>
        {(['facebook', 'instagram', 'ads'] as const).map(kind => <fieldset key={kind} disabled={disabled || company.archived || !props.metaConnected}>
          <legend>{kind === 'facebook' ? 'Facebook accounts' : kind === 'instagram' ? 'Instagram accounts' : 'Meta Ads accounts'}</legend>
          {props.accounts.filter(a => a.kind === kind).map(account => <label className="source-choice" key={account.id}>
            <input type="checkbox" checked={account.linkedCompanyIds.includes(company.id)} onChange={event => props.run(() => props.onAccountLink(company.id, account.id, event.target.checked))} />{account.name}
          </label>)}
          {!props.accounts.some(a => a.kind === kind) && <p className="muted">No available accounts.</p>}
        </fieldset>)}
        <fieldset disabled={disabled || company.archived || !props.metaConnected}>
          <legend>Assign specific Ads content</legend>
          <p className="muted">Link an Ads account to assign its content. Uncheck content to unassign it.</p>
          {props.adsContent.filter(ad => ad.assignedCompanyIds.includes(company.id) || props.accounts.some(a => a.id === ad.accountId && a.kind === 'ads' && a.linkedCompanyIds.includes(company.id))).map(ad => <div key={ad.id}><label className="source-choice">
            <input type="checkbox" checked={ad.assignedCompanyIds.includes(company.id)} onChange={event => props.run(() => props.onAdsAssignment(company.id, ad.id, event.target.checked))} />{ad.name}
          </label>{ad.assignedCompanyIds.includes(company.id) && <Reassign name={ad.name} destinations={props.companies.filter(c => !c.archived && c.id !== company.id && props.accounts.some(a => a.id === ad.accountId && a.linkedCompanyIds.includes(c.id)))} busy={disabled} onReassign={target => props.run(() => props.onAdsReassign(company.id, ad.id, target))} />}</div>)}
          {!props.adsContent.some(ad => ad.assignedCompanyIds.includes(company.id) || props.accounts.some(a => a.id === ad.accountId && a.linkedCompanyIds.includes(company.id))) && <p>No Ads content available for assignment.</p>}
        </fieldset>
      </>}
    </section>}
  </section>;
}

function Reassign({ name, destinations, busy, onReassign }: { name: string; destinations: readonly Company[]; busy: boolean; onReassign(target: string): void }) {
  const [target, setTarget] = useState('');
  return <div className="company-form"><label>Move {name} to<select value={target} disabled={busy} onChange={event => setTarget(event.target.value)}><option value="">Choose a company</option>{destinations.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label><button disabled={busy || !destinations.some(c => c.id === target)} onClick={() => onReassign(target)} aria-label={`Reassign ${name}`}>Reassign ad</button>{!destinations.length && <p>Link this Ads account to another active company before reassigning.</p>}</div>;
}
