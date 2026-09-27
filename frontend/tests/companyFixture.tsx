import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CompanyShell } from '../src/CompanyShell';
import { useCompanySwitchGuard } from '../src/CompanySwitchGuard';
import type { CompanyUIProps, Company } from '../src/companyUI';
import '../src/style.css';
function Work() {
  const [unsavedEdits, setDirty] = useState(false);
  const [generationInProgress, setGenerating] = useState(false);
  useCompanySwitchGuard({ unsavedEdits, generationInProgress });
  return <section><h2>Workspace content</h2><label><input type="checkbox" checked={unsavedEdits} onChange={e => setDirty(e.target.checked)} />Unsaved edits</label><label><input type="checkbox" checked={generationInProgress} onChange={e => setGenerating(e.target.checked)} />Generation in progress</label></section>;
}
function Fixture() {
  const mode = new URLSearchParams(location.search).get('mode');
  const [companies, setCompanies] = useState<Company[]>(mode === 'none' ? [] : [
    { id: 'a', name: 'Alpha', role: "owner", archived: false, hasLinkedAccounts: mode !== 'empty' },
    { id: 'b', name: 'Beta', role: "owner", archived: false, hasLinkedAccounts: true },
    { id: 'c', name: 'Old company', role: "owner", archived: true, hasLinkedAccounts: true },
  ]);
  const [activeCompanyId, setActive] = useState<string | null>(mode === 'none' ? null : 'a');
  const [inspected, setInspected] = useState<string | null>(null);
  const [status, setStatus] = useState<CompanyUIProps['status']>(mode === 'loading' ? 'loading' : mode === 'error' ? 'error' : 'ready');
  const [events, setEvents] = useState<string[]>([]);
  const [accounts, setAccounts] = useState<CompanyUIProps['accounts']>([
    { id: 'raw-meta-fb', name: 'Facebook Page', kind: 'facebook', linkedCompanyIds: [] },
    { id: 'raw-meta-ig', name: 'Instagram Business', kind: 'instagram', linkedCompanyIds: [] },
    { id: 'raw-meta-ads', name: 'Ads Business', kind: 'ads', linkedCompanyIds: [] },
  ]);
  const [adsContent, setAds] = useState<CompanyUIProps['adsContent']>([{ id: 'raw-ad', name: 'Summer video ad', accountId: 'raw-meta-ads', assignedCompanyIds: [] }]);
  const record = (s: string) => setEvents(e => [...e, s]);
  const update = (id: string, patch: Partial<Company>) => setCompanies(cs => cs.map(c => c.id === id ? { ...c, ...patch } : c));
  const props: CompanyUIProps = {
    companies, activeCompanyId, status, accounts, adsContent, discoveryCompanyId: inspected, discoveryStatus: mode === 'discovery-error' ? 'error' : 'ready', metaConnected: true,
    onInspect: setInspected, onAdsReassign: async () => {},
    onRetry: () => setStatus('ready'), onRetryDiscovery: () => record('retry-discovery'),
    onSwitch: async id => { record(`switch:${id}`); if (mode === 'switch-error') throw Error(); setActive(id); },
    onCreate: async name => { record(`create:${name}`); const company = { id: 'new', name, role: "owner", archived: false, hasLinkedAccounts: false }; setCompanies(cs => [...cs, company]); return company; },
    onRename: async (id, name) => update(id, { name }), onArchive: async id => update(id, { role: "owner", archived: true }), onRestore: async id => update(id, { role: "owner", archived: false }),
    onAccountLink: async (companyId, id, linked) => setAccounts(as => as.map(a => a.id === id ? { ...a, linkedCompanyIds: linked ? [...a.linkedCompanyIds, companyId] : a.linkedCompanyIds.filter(c => c !== companyId) } : a)),
    onAdsAssignment: async (companyId, id, assigned) => setAds(as => as.map(a => a.id === id ? { ...a, assignedCompanyIds: assigned ? [...a.assignedCompanyIds, companyId] : a.assignedCompanyIds.filter(c => c !== companyId) } : a)),
    onConnectMeta: () => record('connect'),
  };
  return <main><CompanyShell companyUI={props}><Work key={activeCompanyId} /></CompanyShell><output aria-label="Calls">{events.join('|')}</output></main>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
