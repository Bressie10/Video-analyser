import { authClient } from './authClient';

let lifetime = new AbortController();
let revision = 0;
let refresh: Promise<Awaited<ReturnType<typeof authClient.getSession>>> | null = null;
const expiredListeners = new Set<() => void>();
export function onSessionExpired(listener: () => void) { expiredListeners.add(listener); return () => { expiredListeners.delete(listener); }; }
export function clearAuthRequests() { revision++; lifetime.abort(); lifetime = new AbortController(); refresh = null; }
function expired() { clearAuthRequests(); expiredListeners.forEach(listener => listener()); }
/** Only same-origin application APIs receive credentials. Never replay a mutation. */
export const apiFetch: typeof fetch = async (input, init) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, typeof window === 'undefined' ? 'http://localhost' : window.location.origin);
  const origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin;
  if (url.origin !== origin || !url.pathname.startsWith('/api/')) throw new Error('Application API origin required.');
  const version = revision;
  const signal = AbortSignal.any([lifetime.signal, ...(init?.signal ? [init.signal] : input instanceof Request ? [input.signal] : [])]);
  const session = await authClient.getSession();
  signal.throwIfAborted();
  if (!session) { expired(); return new Response(null, { status: 401 }); }
  const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
  headers.set('Authorization', `Bearer ${session.access_token}`);
  const options = { ...init, headers, signal, cache: 'no-store' as const, redirect: 'error' as const };
  const response = await fetch(input, options);
  signal.throwIfAborted();
  if (response.status !== 401) return response;
  // A single shared refresh; 403 never changes the authentication session.
  const pending = refresh ??= authClient.refreshSession().catch(() => null);
  const renewed = await pending;
  if (refresh === pending) refresh = null;
  if (version !== revision) { signal.throwIfAborted(); return response; }
  if (!renewed || renewed.user.id !== session.user.id) { expired(); return response; }
  const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
  if (!['GET', 'HEAD'].includes(method)) return response;
  headers.set('Authorization', `Bearer ${renewed.access_token}`);
  const retried = await fetch(input, options);
  signal.throwIfAborted();
  if (retried.status === 401) expired();
  return retried;
};
