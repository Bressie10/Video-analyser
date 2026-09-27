import { createContext, useContext, useEffect, useId, useCallback, useState, type ReactNode } from 'react';

type Guard = { unsavedEdits?: boolean; generationInProgress?: boolean };
const Context = createContext<{ guards: ReadonlyMap<string, Guard>; register(id: string, guard: Guard | null): void } | null>(null);
export function CompanySwitchGuardProvider({ children }: { children: ReactNode }) {
  const [guards, setGuards] = useState<ReadonlyMap<string, Guard>>(new Map());
  const register = useCallback((id: string, guard: Guard | null) => {
    setGuards(current => { const next = new Map(current); if (guard) next.set(id, guard); else next.delete(id); return next; });
  }, []);
  return <Context.Provider value={{ guards, register }}>{children}</Context.Provider>;
}
export function useCompanySwitchGuard({ unsavedEdits = false, generationInProgress = false }: Guard) {
  const context = useContext(Context);
  const register = context?.register;
  const id = useId();
  useEffect(() => {
    register?.(id, { unsavedEdits, generationInProgress });
    return () => register?.(id, null);
  }, [register, id, unsavedEdits, generationInProgress]);
  return id;
}
export function useCompanySwitchReasons() {
  const context = useContext(Context);
  const guards = [...(context?.guards.values() ?? [])];
  const excluding = (id?: string) => [...(context?.guards.entries() ?? [])].filter(([key]) => key !== id).map(([, guard]) => guard);
  return { excluding, unsavedEdits: guards.some(g => g.unsavedEdits), generationInProgress: guards.some(g => g.generationInProgress) };
}
