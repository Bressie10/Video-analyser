import { useEffect, useState } from 'react';
import type { Company, CompanyUIProps } from './companyUI';
import { useCompanySwitchGuard } from './CompanySwitchGuard';
import { Button, Input, Select } from './ui/controls';
import { Badge, EmptyState } from './ui/layout';
import './settings.css';

type Props = CompanyUIProps & { busy: boolean; run(action: () => Promise<void> | void): void; onCreateAndEnter(name: string, ownGuard: string): void; onBack(): void };
function Rename({ company, busy, onSave }: { company: Company; busy: boolean; onSave(name: string): void }) {
  const [name, setName] = useState(company.name);
  useCompanySwitchGuard({ unsavedEdits: name !== company.name });
  return <form className="settings-form" onSubmit={event => { event.preventDefault(); if (name.trim()) onSave(name.trim()); }}>
    <label>Company name<Input value={name} maxLength={200} required disabled={busy || company.archived} onChange={event => setName(event.target.value)} /></label>
    <Button type="submit" variant="primary" disabled={busy || company.archived || !name.trim() || name.trim() === company.name}>Save name</Button>
  </form>;
}
export function CompanyManagement(props: Props) {
  const [name, setName] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [inspectedId, setInspectedId] = useState(props.activeCompanyId);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const company = props.companies.find(c => c.id === inspectedId);
  const createGuard = useCompanySwitchGuard({ unsavedEdits: !!name.trim() });
  useEffect(() => { if (props.activeCompanyId || !company?.archived) setInspectedId(props.activeCompanyId); }, [props.activeCompanyId]);
  useEffect(() => { setSearch(''); setFilter('all'); props.onInspect(inspectedId); return () => props.onInspect(null); }, [inspectedId, props.onInspect]);
  const discoveryStatus = props.discoveryCompanyId === company?.id ? props.discoveryStatus : 'loading';
  const disabled = props.busy || props.status !== 'ready';
  const ads = company ? props.adsContent.filter(ad => ad.assignedCompanyIds.includes(company.id) || props.accounts.some(a => a.id === ad.accountId && a.kind === 'ads' && a.linkedCompanyIds.includes(company.id))) : [];
  const visibleAds = ads.filter(ad => ad.name.toLowerCase().includes(search.toLowerCase()) && (filter === 'all' || (filter === 'assigned') === ad.assignedCompanyIds.includes(company!.id)));
  const jump = (id: string) => { const target = document.getElementById(id); target?.scrollIntoView({ block: 'start' }); target?.focus(); };
  return <div className="settings-page">
    <header className="settings-heading"><div><h2 id="companies-title" tabIndex={-1}>Manage companies</h2><p>Configure your workspace, connected accounts and content ownership.</p></div><Button variant="ghost" disabled={props.busy} onClick={props.onBack}>Back to workspace</Button></header>
    <nav className="settings-nav" aria-label="Settings sections">{[['settings-general', 'General'], ['settings-meta', 'Integrations'], ['settings-ownership', 'Content ownership'], ['settings-analysis', 'AI & Analysis'], ['settings-companies', 'Company management']].filter(([id]) => !(id === 'settings-ownership' && company?.role !== 'owner') && !(['settings-general', 'settings-ownership'].includes(id) && !company) && !(id === 'settings-analysis' && !props.activeCompanyId)).map(([id, label]) => <Button key={id} variant="ghost" onClick={() => jump(id)}>{label}</Button>)}</nav>
    {props.status === 'ready' && company ? <>
      <section className="settings-section" aria-labelledby="settings-general">
        <h2 id="settings-general" tabIndex={-1}>General</h2><h3>{company.name}</h3>
        {company.id !== props.activeCompanyId && <p>Managing this company does not change your active workspace.</p>}
        {company.archived && <p className="settings-note">Archived — unavailable for normal work. Restore this company to use it again.</p>}
        {company.role === 'owner' ? <Rename key={`${company.id}:${company.name}`} company={company} busy={disabled} onSave={value => props.run(() => props.onRename(company.id, value))} /> : <p>You are a member. A company owner manages configuration and content ownership.</p>}
      </section>
      {company.role === 'owner' && <section className="settings-section" aria-labelledby="settings-ownership">
        <div className="settings-heading"><div><h2 id="settings-ownership" tabIndex={-1}>Content ownership</h2><p>Choose the accounts and ads that belong in {company.name}.</p></div><Button disabled={disabled || !props.metaConnected || discoveryStatus === 'loading'} onClick={props.onRetryDiscovery}>Refresh available accounts</Button></div>
        {!props.metaConnected && <p className="settings-note">Connect Meta in Integrations to discover accounts for your companies.</p>}
        {props.metaConnected && discoveryStatus === 'loading' && <p role="status">Loading available accounts and ads…</p>}
        {props.metaConnected && discoveryStatus === 'error' && <p role="alert">{props.discoveryError ?? 'Could not load accounts and ads.'} <Button onClick={props.onRetryDiscovery}>Retry accounts</Button></p>}
        {props.metaConnected && discoveryStatus === 'ready' && <>
          <h3>Linked accounts</h3><p>Facebook and Instagram accounts can belong to one company at a time. Unlink an account from its current company before linking it here.</p>
          {(['facebook', 'instagram', 'ads'] as const).map(kind => <fieldset className="settings-picker" key={kind} disabled={disabled || company.archived || !props.metaConnected}>
            <legend>{kind === 'facebook' ? 'Facebook Pages' : kind === 'instagram' ? 'Instagram accounts' : 'Ads accounts'}</legend>
            {kind === 'ads' && <p>Ads accounts can be shared across companies. Linking an account does not assign its ads.</p>}
            {props.accounts.filter(a => a.kind === kind).map(account => {
              const linked = account.linkedCompanyIds.includes(company.id);
              const otherOwner = account.ownerName ?? props.companies.find(c => c.id !== company.id && account.linkedCompanyIds.includes(c.id))?.name;
              return <div className="settings-row" key={account.id}><label className="settings-check"><input type="checkbox" checked={linked} onChange={event => props.run(() => props.onAccountLink(company.id, account.id, event.target.checked))} /><span>{account.name}</span></label><Badge tone={linked ? 'success' : kind !== 'ads' && otherOwner ? 'warning' : 'neutral'}>{linked ? 'Linked' : kind !== 'ads' && otherOwner ? `Linked to ${otherOwner}` : 'Not linked'}</Badge></div>;
            })}
            {!props.accounts.some(a => a.kind === kind) && <p>No eligible accounts available.</p>}
          </fieldset>)}
          <h3>Ad assignment</h3><p>Each ad can belong to one company. Select an ad to assign it; clear its checkbox to unassign it. Move an assigned ad only to a company linked to the same Ads account.</p>
          <fieldset className="settings-picker" disabled={disabled || company.archived || !props.metaConnected}>
            <legend>Assign specific Ads content</legend>
            {ads.length > 0 && <div className="settings-filters"><label>Search ads<Input type="search" value={search} onChange={event => setSearch(event.target.value)} /></label><label>Assignment<Select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All ads</option><option value="assigned">Assigned to this company</option><option value="available">Available</option></Select></label></div>}
            {visibleAds.map(ad => { const assigned = ad.assignedCompanyIds.includes(company.id); return <div className="settings-ad" key={ad.id}><div className="settings-row"><label className="settings-check"><input type="checkbox" checked={assigned} onChange={event => props.run(() => props.onAdsAssignment(company.id, ad.id, event.target.checked))} /><span>{ad.name}</span></label><Badge tone={assigned ? 'success' : 'neutral'}>{assigned ? 'Assigned here' : ad.assignedCompanyIds.length ? 'Assigned elsewhere' : 'Available'}</Badge></div>{assigned && <Reassign name={ad.name} destinations={props.companies.filter(c => c.role === 'owner' && !c.archived && c.id !== company.id && props.accounts.some(a => a.id === ad.accountId && a.linkedCompanyIds.includes(c.id)))} busy={disabled} onReassign={target => props.run(() => props.onAdsReassign(company.id, ad.id, target))} />}</div>; })}
            {!ads.length && <p>No Ads content available for assignment. Link an Ads account above to see eligible ads.</p>}
            {ads.length > 0 && !visibleAds.length && <p>No ads match your filters.</p>}
          </fieldset>
          <p className="settings-caption">If ownership has changed, refresh available accounts and check the assignment again. Ads owned by another company must be released or moved from that company first.</p>
        </>}
      </section>}
    </> : props.status === 'ready' ? <EmptyState title="Create your company workspace"><p>Start with a name. Your new workspace is ready to use immediately; connect accounts whenever you are ready.</p></EmptyState> : <p role="status">Company settings will appear when your companies are loaded.</p>}
    <section className="settings-section" aria-labelledby="settings-companies">
      <h2 id="settings-companies" tabIndex={-1}>Company management</h2><p>Create a separate space for another business. Only a name is needed.</p>
      <form className="settings-form" onSubmit={event => { event.preventDefault(); if (name.trim()) props.onCreateAndEnter(name.trim(), createGuard); }}><label>New company name<Input required maxLength={200} value={name} disabled={disabled} onChange={event => setName(event.target.value)} /></label><Button type="submit" variant="primary" disabled={disabled || !name.trim()}>Create company</Button></form>
      <details className="settings-disclosure"><summary>Manage existing and archived companies</summary><p>Inspect a company's settings here. Use the company selector to change your active workspace.</p><label className="settings-check"><input type="checkbox" checked={showArchived} onChange={event => setShowArchived(event.target.checked)} />Show archived companies</label><ul className="settings-company-list">{props.companies.filter(c => showArchived || !c.archived).map(c => <li key={c.id}><Button aria-pressed={company?.id === c.id} disabled={props.busy} onClick={() => setInspectedId(c.id)}>{c.name}{c.archived ? ' — Archived' : c.id === props.activeCompanyId ? ' — Active' : ''}</Button></li>)}</ul></details>
    </section>
    {company?.role === 'owner' && <section className="settings-section settings-danger" aria-labelledby="settings-danger"><h2 id="settings-danger">{company.archived ? 'Restore company' : 'Danger zone'}</h2><p>{company.archived ? 'Restore this company explicitly to make its workspace available again. Restoring does not switch your active company.' : 'Archiving disables this company’s workspace. It does not release account or ad ownership. You can restore it later from Company management.'}</p><Button variant={company.archived ? 'secondary' : 'danger'} disabled={disabled} onClick={() => props.run(() => company.archived ? props.onRestore(company.id) : props.onArchive(company.id))}>{company.archived ? 'Restore company' : 'Archive company'}</Button></section>}
  </div>;
}
function Reassign({ name, destinations, busy, onReassign }: { name: string; destinations: readonly Company[]; busy: boolean; onReassign(target: string): void }) {
  const [target, setTarget] = useState('');
  return <details className="settings-reassign"><summary>Move to another company</summary><div className="settings-form"><label>Move {name} to<Select value={target} disabled={busy} onChange={event => setTarget(event.target.value)}><option value="">Choose a company</option>{destinations.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></label><Button disabled={busy || !destinations.some(c => c.id === target)} onClick={() => onReassign(target)} aria-label={`Reassign ${name}`}>Reassign ad</Button>{!destinations.length && <p>Link this Ads account to another active company before reassigning.</p>}</div></details>;
}
