import { useSyncExternalStore } from 'react';
import { House, SquarePlay, Lightbulb, PencilLine, Settings2, ChartNoAxesCombined } from 'lucide-react';

export const navigation = [
  { id: 'overview', label: 'Home', icon: House, description: 'Your company workspace.' },
  { id: 'intelligence', label: 'Creative Intelligence', icon: ChartNoAxesCombined, description: 'Compare ad performance and observed creative differences.' },
  { id: 'content', label: 'Content', icon: SquarePlay, description: 'Browse the content in your company library.' },
  { id: 'ideas', label: 'Ideas', icon: Lightbulb, description: 'Review, refine and use your saved ideas.' },
  { id: 'generate', label: 'Generate', icon: PencilLine, description: 'Build your next idea from analysed content.' },
  { id: 'settings', label: 'Settings', icon: Settings2, description: 'Manage your companies and integrations.' },
] as const;
export type AppPage = typeof navigation[number]['id'] | 'creative';
function currentPage(): AppPage {
  const hash = window.location.hash.slice(1);
  if (/^creative\/[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(hash)) return 'creative';
  return navigation.find(item => item.id === hash)?.id ?? 'overview';
}
function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}
export function navigate(page: AppPage) { window.location.hash = page; }
export function useAppPage() { return useSyncExternalStore(subscribe, currentPage, () => 'overview' as const); }
export function useCreativeRef() { return useAppPage() === 'creative' ? window.location.hash.slice('#creative/'.length) : null; }
