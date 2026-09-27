import { useEffect, useRef, useState } from 'react';
import { companyApi, companyError, type AvailableAccount, type Company } from './companyApi';
import { useCompany, useCompanyStore } from './CompanyProvider';
import { ServiceError } from '../metaLibrary';
import type { CompanyUIProps, AdsContent } from '../companyUI';

/** Bridge management presentation to the single global company store. */
export function useCompanyUI(metaConnected: boolean, onConnectMeta: () => void): CompanyUIProps {
  const state = useCompany();
  const store = useCompanyStore();
  const [inspectedId, inspect] = useState<string | null>(null);
  const [revision, revise] = useState(0);
  const [discovery, setDiscovery] = useState<{ key: string; accounts: AvailableAccount[]; ads: AdsContent[]; error: unknown }>();
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  const inspected = state.companies.find(c => c.id === inspectedId);
  const key = `${state.status}:${state.scopeVersion}:${inspectedId}:${revision}:${metaConnected}:${JSON.stringify(inspected?.accounts)}:${inspected?.archived}`;
  useEffect(() => {
    if (state.status !== 'ready' || !inspectedId) return;
    const controller = new AbortController();
    let current = true;
    void (async () => {
      try {
        const accounts = await companyApi.listAvailableMetaAccounts(controller.signal);
        const groups = inspected?.archived ? [] : await Promise.all((inspected?.accounts ?? []).filter(a => a.platform === 'meta_ads').map(async account =>
          (await companyApi.listAssignableAdsContent(inspectedId, account.id, controller.signal)).map(ad => ({ id: ad.id, name: ad.label, accountId: account.id, assignedCompanyIds: ad.assigned ? [inspectedId] : [] }))));
        if (current) setDiscovery({ key, accounts, ads: groups.flat(), error: null });
      } catch (error) {
        if (!current) return;
        setDiscovery({ key, accounts: [], ads: [], error });
        if (error instanceof ServiceError && error.status === 401) void store.refreshCompanies();
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [key, store]); // key includes inspection, scope, links and explicit refresh version
  const visible = discovery?.key === key ? discovery : undefined;
  const viewCompany = (company: Company) => ({ id: company.id, name: company.name, archived: company.archived, hasLinkedAccounts: company.accounts.length > 0 });
  async function mutate<T>(action: (signal: AbortSignal) => Promise<T>, apply: (result: T) => void): Promise<T> {
    const signal = lifetime.current.signal;
    const version = store.getSnapshot().scopeVersion;
    try {
      const result = await action(signal);
      if (!signal.aborted && version === store.getSnapshot().scopeVersion && store.getSnapshot().status === 'ready') {
        apply(result);
        revise(v => v + 1);
      }
      return result;
    } catch (error) {
      if (!signal.aborted && version === store.getSnapshot().scopeVersion && error instanceof ServiceError && [401, 404].includes(error.status)) await store.refreshCompanies();
      throw error;
    }
  }
  const invalidateAffected = (...ids: string[]) => {
    const active = store.getSnapshot().activeCompanyId;
    if (active && ids.includes(active)) store.invalidateCompanyScope();
  };
  const accept = (company: Company) => store.acceptCompany(company);
  return {
    companies: state.companies.map(viewCompany), activeCompanyId: state.activeCompanyId, status: state.status,
    error: state.error ? companyError(state.error) : state.persistenceError ? 'Company selection could not be saved in this browser. It remains available for this session.' : undefined,
    accounts: (visible?.accounts ?? []).map(account => ({ id: account.id, name: account.name, kind: account.platform === 'meta_ads' ? 'ads' : account.platform,
      linkedCompanyIds: state.companies.filter(c => c.accounts.some(a => a.id === account.id)).map(c => c.id) })),
    discoveryCompanyId: visible ? inspectedId : null,
    adsContent: visible?.ads ?? [], discoveryStatus: visible ? visible.error ? 'error' : 'ready' : 'loading',
    discoveryError: visible?.error ? companyError(visible.error) : undefined, metaConnected,
    onInspect: inspect, onRetry: () => { void store.refreshCompanies(); }, onRetryDiscovery: () => revise(v => v + 1),
    onSwitch: id => store.setActiveCompany(id),
    onCreate: async name => viewCompany(await mutate(signal => companyApi.createCompany(name, signal), company => store.acceptCompany(company, true))),
    onRename: async (id, name) => { await mutate(signal => companyApi.renameCompany(id, name, signal), accept); },
    onArchive: async id => { await mutate(signal => companyApi.archiveCompany(id, signal), accept); },
    onRestore: async id => { await mutate(signal => companyApi.restoreCompany(id, signal), accept); },
    onAccountLink: async (id, accountId, linked) => { await mutate(signal => (linked ? companyApi.linkAccount : companyApi.unlinkAccount)(id, accountId, signal), company => { accept(company); invalidateAffected(id); }); },
    onAdsAssignment: async (id, contentId, assigned) => { await mutate(signal => (assigned ? companyApi.assignAdsContent : companyApi.unassignAdsContent)(contentId, id, signal), () => invalidateAffected(id)); },
    onAdsReassign: async (id, contentId, target) => { await mutate(signal => companyApi.reassignAdsContent(contentId, id, target, signal), () => invalidateAffected(id, target)); },
    onConnectMeta,
  };
}
