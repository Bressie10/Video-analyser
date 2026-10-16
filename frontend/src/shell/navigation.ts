import { useSyncExternalStore } from 'react';
import { House, SquarePlay, Lightbulb, PencilLine, Settings2, ChartNoAxesCombined } from 'lucide-react';

export const navigation = [
  { id: 'overview', label: 'Home', icon: House, description: 'Your company workspace.' },
  { id: 'content', label: 'Content', icon: SquarePlay, description: 'Browse the content in your company library.' },
  { id: 'intelligence', label: 'Creative Intelligence', icon: ChartNoAxesCombined, description: 'Compare ad performance and observed creative differences.' },
  { id: 'generate', label: 'Generate', icon: PencilLine, description: 'Build your next idea from analysed content.' },
  { id: 'ideas', label: 'Ideas', icon: Lightbulb, description: 'Review, refine and use your saved ideas.' },
  { id: 'settings', label: 'Settings', icon: Settings2, description: 'Manage workspace, connections, billing, analysis and account.' },
] as const;
export type AppPage = typeof navigation[number]['id'] | 'creative' | 'content-detail';
export const settingsSections = ['general', 'workspace', 'connections', 'billing', 'analysis', 'account'] as const;
export type SettingsSection = typeof settingsSections[number];
export function settingsSection(): SettingsSection | null {
  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  if (path === '/settings') return 'general';
  const match = /^\/settings\/([^/]+)$/.exec(path);
  return settingsSections.find(section => section === match?.[1]) ?? null;
}
export function pageHref(page: AppPage, itemId?: string) { return page === 'settings' ? '/settings' : page === 'content-detail' ? `/#content${itemId ? `/${itemId}` : ''}` : page === 'creative' ? `/#creative${itemId ? `/${itemId}` : ''}` : `/#${page}`; }
const uuid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
function currentPage(): AppPage {
  const hash = window.location.hash.slice(1);
  if (new RegExp(`^content/${uuid}$`, 'i').test(hash)) return 'content-detail';
  if (/^creative\/[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(hash)) return 'creative';
  const hashed = navigation.find(item => item.id === hash)?.id;
  return hashed ?? (settingsSection() ? 'settings' : 'overview');
}
function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  window.addEventListener('popstate', listener);
  return () => { window.removeEventListener('hashchange', listener); window.removeEventListener('popstate', listener); };
}
export function navigate(page: AppPage, itemId?: string) {
  window.history.pushState(null, '', pageHref(page, itemId));
  window.dispatchEvent(new PopStateEvent('popstate'));
}
export function navigateSettings(section: SettingsSection) {
  window.history.pushState(null, '', `/settings/${section}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}
export function useAppPage() { return useSyncExternalStore(subscribe, currentPage, () => 'overview' as const); }
export function useSettingsSection() { return useSyncExternalStore(subscribe, settingsSection, () => null); }
export function useCreativeRef() { return useAppPage() === 'creative' ? window.location.hash.slice('#creative/'.length) : null; }
export function useContentItemId() { return useAppPage() === 'content-detail' ? window.location.hash.slice('#content/'.length) : null; }
