/** UI-only contracts. IDs are opaque application keys, never display labels. */
export interface Company {
  id: string;
  name: string;
  archived: boolean;
  hasContent: boolean;
}
export interface CompanyAccount {
  id: string;
  name: string;
  kind: 'facebook' | 'instagram' | 'ads';
  linkedCompanyIds: readonly string[];
}
export interface AdsContent {
  id: string;
  name: string;
  accountId: string;
  assignedCompanyIds: readonly string[];
}
export interface CompanyUIProps {
  companies: readonly Company[];
  activeCompanyId: string | null;
  status: 'loading' | 'ready' | 'error';
  accounts: readonly CompanyAccount[];
  adsContent: readonly AdsContent[];
  discoveryStatus: 'loading' | 'ready' | 'error';
  metaConnected: boolean;
  onRetry(): void;
  onRetryDiscovery(): void;
  onSwitch(companyId: string): Promise<void> | void;
  onCreate(name: string): Promise<Company>;
  onRename(companyId: string, name: string): Promise<void>;
  onArchive(companyId: string): Promise<void>;
  onRestore(companyId: string): Promise<void>;
  onAccountLink(companyId: string, accountId: string, linked: boolean): Promise<void>;
  onAdsAssignment(companyId: string, contentId: string, assigned: boolean): Promise<void>;
  /** Opens the shared Meta connection flow, not per-company OAuth. */
  onConnectMeta(): Promise<void> | void;
}
