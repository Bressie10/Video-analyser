import { createClient, type AuthChangeEvent, type Session, type SupabaseClient } from '@supabase/supabase-js';

// Authentication only: application data always goes through FastAPI.
const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
const configured = typeof url === 'string' && /^https?:\/\/[^/]+\/?$/.test(url) && typeof key === 'string' && key.startsWith('sb_publishable_');
let client: SupabaseClient | null = null;
function auth() {
  if (!configured) throw new Error('AUTH_NOT_CONFIGURED');
  client ??= createClient(url, key, { auth: { flowType: 'pkce', persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } });
  return client.auth;
}
const callback = (recovery = false) => `${window.location.origin}/auth/callback${recovery ? '?recovery=1' : ''}`;
export const authClient = {
  configured,
  async getSession() { if (!configured) return null; const { data, error } = await auth().getSession(); if (error) throw error; return data.session; },
  async refreshSession() { const { data, error } = await auth().refreshSession(); if (error) throw error; return data.session; },
  subscribe(listener: (event: AuthChangeEvent, session: Session | null) => void) {
    if (!configured) return () => {};
    const { data } = auth().onAuthStateChange(listener);
    return () => data.subscription.unsubscribe();
  },
  async signUp(email: string, password: string) {
    const { data, error } = await auth().signUp({ email, password, options: { emailRedirectTo: callback() } });
    if (error) throw error; return data.session;
  },
  async signIn(email: string, password: string) { const { error } = await auth().signInWithPassword({ email, password }); if (error) throw error; },
  async google() { const { error } = await auth().signInWithOAuth({ provider: 'google', options: { redirectTo: callback() } }); if (error) throw error; },
  async signOut() { const { error } = await auth().signOut({ scope: 'local' }); if (error) throw error; },
  async requestReset(email: string) { const { error } = await auth().resetPasswordForEmail(email, { redirectTo: callback(true) }); if (error) throw error; },
  async updatePassword(password: string) { const { error } = await auth().updateUser({ password }); if (error) throw error; },
};
export function authError(error: unknown): string {
  const code = error && typeof error === 'object' && 'code' in error ? error.code : '';
  if (code === 'invalid_credentials') return 'Email or password is incorrect.';
  if (code === 'email_not_confirmed') return 'Please verify your email before signing in.';
  if (code === 'weak_password') return 'Choose a stronger password with at least 8 characters.';
  if (code === 'over_request_rate_limit' || code === 'over_email_send_rate_limit') return 'Too many attempts. Please wait a moment and try again.';
  if (code === 'same_password') return 'Choose a different password from your current one.';
  if (error instanceof TypeError || (error && typeof error === 'object' && 'name' in error && error.name === 'AuthRetryableFetchError')) return 'Unable to connect. Check your connection and try again.';
  return 'We couldn’t complete that request. Please try again.';
}
