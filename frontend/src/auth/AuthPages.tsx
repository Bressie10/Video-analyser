import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { authClient, authError } from './authClient';
import { useAuth } from './AuthProvider';
import { Button, Input } from '../ui/controls';
import { LoadingState } from '../ui/layout';
import './auth.css';
const entry = new URL(window.location.href);
const callbackError = entry.searchParams.has('error') || new URLSearchParams(entry.hash.slice(1)).has('error');
const callbackCredentials = entry.searchParams.has('code') || new URLSearchParams(entry.hash.slice(1)).has('access_token');
export function AuthLayout({ children }: { children: ReactNode }) {
  return <main className="auth-layout"><a className="auth-brand" href="/login"><span className="app-brand-mark" aria-hidden="true">C</span>ContentMetric</a><div className="auth-panel">{children}</div><nav className="auth-legal" aria-label="Legal"><a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/data-deletion">Data deletion</a></nav></main>;
}
export function AuthLoading() { return <AuthLayout><LoadingState label="Opening your workspace…" /></AuthLayout>; }
export function Redirect({ to }: { to: string }) { useEffect(() => { window.location.replace(to); }, [to]); return <AuthLoading />; }
export function AuthPage({ path }: { path: string }) {
  const { session, recovery, loading } = useAuth();
  const [email, setEmail] = useState(''), [password, setPassword] = useState(''), [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [success, setSuccess] = useState(false);
  const signup = path === '/signup', forgot = path === '/forgot-password', callback = path === '/auth/callback';
  const reset = callback && (recovery || entry.searchParams.get('recovery') === '1');
  useEffect(() => { if (callback && !loading) window.history.replaceState(null, '', '/auth/callback'); }, [callback, loading]);
  if (loading) return <AuthLoading />;
  if (callback && (callbackError || !session || (reset && !recovery) || (!reset && !callbackCredentials))) return <AuthLayout><h1>Link unavailable</h1><p>This link is invalid or has expired. Please request a new one.</p><a href="/forgot-password">Request a password reset</a><p><a href="/login">Back to sign in</a></p></AuthLayout>;
  if (session && !reset && !success) return <Redirect to="/" />;
  const title = reset ? 'Set a new password' : signup ? 'Create your account' : forgot ? 'Reset your password' : 'Welcome back';
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('');
    if ((signup || reset) && password.length < 8) { setError('Use at least 8 characters for your password.'); return; }
    if ((signup || reset) && password !== confirm) { setError('Passwords do not match.'); return; }
    setBusy(true);
    try {
      if (reset) { await authClient.updatePassword(password); setSuccess(true); }
      else if (forgot) { await authClient.requestReset(email.trim()); setSuccess(true); }
      else if (signup) { const signedIn = await authClient.signUp(email.trim(), password); if (!signedIn) setSuccess(true); }
      else await authClient.signIn(email.trim(), password);
    } catch (caught) { setError(reset ? 'Unable to update your password. The link may have expired; request a new reset link.' : authError(caught)); }
    finally { setBusy(false); }
  }
  async function google() { setBusy(true); setError(''); try { await authClient.google(); } catch (caught) { setError(authError(caught)); } finally { setBusy(false); } }
  return <AuthLayout><h1>{success ? reset ? 'Password updated' : 'Check your email' : title}</h1>
    {success ? <div role="status"><p>{reset ? 'Your new password is ready. You can return to your workspace.' : forgot ? 'If an account exists for that email, you’ll receive a password reset link shortly.' : 'Check your inbox for a confirmation link before signing in.'}</p><a href={reset ? '/' : '/login'}>{reset ? 'Continue to workspace' : 'Back to sign in'}</a></div> : <>
      <p className="auth-intro">{reset ? 'Choose a strong password to keep your account secure.' : signup ? 'Turn your content into your next good idea.' : forgot ? 'Enter your email and we’ll send you a reset link.' : 'Sign in to your ContentMetric workspace.'}</p>
      {!authClient.configured && <p role="alert">Sign-in is not configured yet. Please contact the workspace administrator.</p>}
      {error && <p className="auth-error" id="auth-error" role="alert">{error}</p>}
      <form onSubmit={submit} aria-busy={busy}>
        {!reset && <label htmlFor="auth-email">Email<Input id="auth-email" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} disabled={busy} aria-describedby={error ? 'auth-error' : undefined} aria-invalid={!!error} /></label>}
        {!forgot && <label htmlFor="auth-password">{reset ? 'New password' : 'Password'}<Input id="auth-password" type="password" autoComplete={signup || reset ? 'new-password' : 'current-password'} required minLength={signup || reset ? 8 : undefined} value={password} onChange={e => setPassword(e.target.value)} disabled={busy} aria-describedby={error ? 'auth-error' : signup || reset ? 'password-help' : undefined} aria-invalid={!!error} /></label>}
        {(signup || reset) && <><p id="password-help" className="auth-hint">Use at least 8 characters.</p><label htmlFor="auth-confirm">Confirm password<Input id="auth-confirm" type="password" autoComplete="new-password" required value={confirm} onChange={e => setConfirm(e.target.value)} disabled={busy} aria-describedby={error ? 'auth-error' : undefined} aria-invalid={!!error} /></label></>}
        <Button type="submit" variant="primary" disabled={busy || !authClient.configured}>{busy ? 'Please wait…' : reset ? 'Update password' : signup ? 'Create account' : forgot ? 'Send reset link' : 'Sign in'}</Button>
        {busy && <span role="status" className="auth-hint">Completing your request…</span>}
      </form>
      {!forgot && !reset && <><div className="auth-divider">or</div><Button className="auth-google" onClick={google} disabled={busy || !authClient.configured}>Continue with Google</Button></>}
      <p className="auth-links">{reset ? <a href="/forgot-password">Request a new reset link</a> : forgot ? <a href="/login">Back to sign in</a> : signup ? <>Already have an account? <a href="/login">Sign in</a></> : <><a href="/forgot-password">Forgot password?</a><span>New to ContentMetric? <a href="/signup">Create an account</a></span></>}</p>
    </>}
  </AuthLayout>;
}
