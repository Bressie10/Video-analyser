import { apiFetch } from '../auth/apiFetch';
import { isUUID } from '../metaLibrary';

export type Step = 'workspace' | 'meta' | 'account' | 'analysis' | 'idea';
export type Onboarding = Readonly<{ company_id: string | null; welcome_seen: boolean; skipped: boolean; progress: number; complete: boolean; next_step: Step | null; steps: Record<Step, boolean> }>;
export class OnboardingError extends Error { constructor(readonly status: number) { super('Onboarding request failed.'); } }
const steps: Step[] = ['workspace', 'meta', 'account', 'analysis', 'idea'];
function parse(value: unknown): Onboarding {
  if (!value || typeof value !== 'object') throw new Error('Invalid onboarding response.');
  const data = value as Record<string, unknown>;
  const flags = data.steps as Record<string, unknown> | null;
  if ((data.company_id !== null && !isUUID(data.company_id)) || typeof data.welcome_seen !== 'boolean' ||
    typeof data.skipped !== 'boolean' || typeof data.complete !== 'boolean' || typeof data.progress !== 'number' ||
    !Number.isInteger(data.progress) || data.progress < 0 || data.progress > 100 ||
    (data.next_step !== null && !steps.includes(data.next_step as Step)) || !flags ||
    steps.some(step => typeof flags[step] !== 'boolean')) throw new Error('Invalid onboarding response.');
  return { company_id: data.company_id as string | null, welcome_seen: data.welcome_seen as boolean,
    skipped: data.skipped as boolean, progress: data.progress as number, complete: data.complete as boolean,
    next_step: data.next_step as Step | null, steps: Object.fromEntries(steps.map(step => [step, flags[step]])) as Record<Step, boolean> };
}
async function request(path: string, init: RequestInit = {}) {
  const response = await apiFetch(path, { cache: 'no-store', ...init });
  if (!response.ok) throw new OnboardingError(response.status);
  return response;
}
export const onboardingApi = {
  async get(signal?: AbortSignal) { return parse(await (await request('/api/me/onboarding', { signal })).json()); },
  async welcome(signal?: AbortSignal) { await request('/api/me/onboarding/welcome', { method: 'POST', signal }); },
  async skip(signal?: AbortSignal) { await request('/api/me/onboarding/skip', { method: 'POST', signal }); },
  async company(id: string, signal?: AbortSignal) { await request('/api/me/onboarding/company', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ company_id: id }), signal }); },
};
