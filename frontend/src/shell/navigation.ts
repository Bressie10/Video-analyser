import { useSyncExternalStore } from 'react';
import { House, Library, Lightbulb, PencilLine, Settings2 } from 'lucide-react';

export const navigation = [
  { id: 'overview', label: 'Overview', icon: House, description: 'Your company workspace.' },
  { id: 'content', label: 'Content', icon: Library, description: 'Browse the content in your company library.' },
  { id: 'generate', label: 'Generate', icon: PencilLine, description: 'Build your next idea from analyzed content.' },
  { id: 'ideas', label: 'Ideas', icon: Lightbulb, description: 'Review, refine and use your saved ideas.' },
  { id: 'settings', label: 'Settings', icon: Settings2, description: 'Manage your companies and integrations.' },
] as const;
export type AppPage = typeof navigation[number]['id'];
function currentPage(): AppPage {
  const hash = window.location.hash.slice(1);
  return navigation.find(item => item.id === hash)?.id ?? 'overview';
}
function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}
export function navigate(page: AppPage) { window.location.hash = page; }
export function useAppPage() { return useSyncExternalStore(subscribe, currentPage, () => 'overview' as const); }
