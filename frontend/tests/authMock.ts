// Test-only auth boundary, installed through Vite aliases. Never imported by production.
const listeners = new Set<(event: string, session: any) => void>();
const defaultSession = { access_token: 'test-access-token', user: { id: '10000000-0000-4000-8000-000000000001', email: 'test@example.com' } };
const state = typeof window === 'undefined' ? {} : ((window as any).__authMock ??= {});
let session = typeof window !== 'undefined' && sessionStorage.getItem('test-signed-out') ? null : state.session === undefined ? defaultSession : state.session;
export const authClient = {
  configured: true,
  async getSession() { if (state.delay) await new Promise(r => setTimeout(r, state.delay)); return session; },
  async refreshSession() { state.refreshes = (state.refreshes ?? 0) + 1; return state.refreshInvalid ? null : session; },
  subscribe(fn: any) { listeners.add(fn); queueMicrotask(() => fn(state.recovery ? 'PASSWORD_RECOVERY' : 'INITIAL_SESSION', session)); return () => listeners.delete(fn); },
  async signIn(email: string, password: string) { state.login = { email, password }; if (state.badCredentials) throw { code: 'invalid_credentials' }; session = { ...defaultSession, user: { ...defaultSession.user, email } }; listeners.forEach(fn => fn('SIGNED_IN', session)); },
  async signUp(email: string, password: string) { state.signup = { email, password }; return null; },
  async google() { state.google = true; },
  async signOut() { if (typeof window !== 'undefined') sessionStorage.setItem('test-signed-out', '1'); session = null; listeners.forEach(fn => fn('SIGNED_OUT', null)); },
  async requestReset(email: string) { state.resetEmail = email; },
  async updatePassword(password: string) { state.newPassword = password; },
};
if (typeof window !== 'undefined') (window as any).__changeAuth = (next: any) => { session = next; listeners.forEach(fn => fn(next ? 'SIGNED_IN' : 'SIGNED_OUT', next)); };
export function authError(error: any) { return error?.code === 'invalid_credentials' ? 'Email or password is incorrect.' : 'We couldn’t complete that request. Please try again.'; }
