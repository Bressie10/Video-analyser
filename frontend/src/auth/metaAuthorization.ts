import { apiFetch } from './apiFetch';
export async function beginMetaAuthorization(signal: AbortSignal): Promise<string> {
  const response = await apiFetch('/api/meta/connect?response_mode=json', { signal, credentials: 'same-origin' });
  if (!response.ok) throw new Error('Meta authorization unavailable.');
  const body = await response.json();
  const url = new URL(body.authorization_url);
  if (url.protocol !== 'https:' || url.hostname !== 'www.facebook.com' || !url.pathname.endsWith('/dialog/oauth')) throw new Error('Invalid Meta authorization destination.');
  return url.href;
}
