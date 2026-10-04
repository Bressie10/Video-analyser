import { apiFetch } from '../auth/apiFetch';
import { isUUID, ServiceError } from '../metaLibrary';

export type Plan = 'free' | 'pro';
export type Billing = {
  plan: Plan; effective_plan: Plan; subscription_status: string | null;
  cancel_at_period_end: boolean; grace_until: string | null;
  entitlements: { organic_account_limit: number; analysis_limit: number; idea_generation_limit: number };
  usage: { analyses: number; idea_generations: number };
  period: { starts_at: string; ends_at: string }; can_manage_billing: boolean;
};
export const limitCodes = ['free_workspace_limit_reached', 'organic_account_limit_reached', 'analysis_limit_reached', 'idea_generation_limit_reached'] as const;
export type LimitCode = typeof limitCodes[number];
export class PlanLimitError extends Error {
  constructor(public code: LimitCode) { super(code); }
}
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const date = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
const count = (value: unknown): value is number => Number.isInteger(value) && Number(value) >= 0;
const validPlan = (value: unknown): value is Plan => value === 'free' || value === 'pro';
export function limitCode(value: unknown): LimitCode | null {
  const detail = record(value) && record(value.detail) ? value.detail : value;
  const code = record(detail) ? detail.code : null;
  return limitCodes.find(candidate => candidate === code) ?? null;
}
export async function billingError(response: Response): Promise<Error> {
  if (response.status === 402) {
    const code = limitCode(await response.clone().json().catch(() => null));
    if (code) return new PlanLimitError(code);
  }
  return new ServiceError(response.status, 'Billing request failed.');
}
export function billingMessage(error: unknown): string {
  if (error instanceof ServiceError) {
    if (error.status === 403 || error.status === 404) return 'This workspace is unavailable to your account. Refresh workspaces and try again.';
    if (error.status === 401) return 'Your session has expired. Please sign in again.';
  }
  return 'Billing is temporarily unavailable. Please retry.';
}
function parseBilling(value: unknown): Billing {
  if (!record(value) || !validPlan(value.plan) || !validPlan(value.effective_plan) ||
    !(value.subscription_status === null || typeof value.subscription_status === 'string') ||
    typeof value.cancel_at_period_end !== 'boolean' || !(value.grace_until === null || date(value.grace_until)) ||
    !record(value.entitlements) || !count(value.entitlements.organic_account_limit) || !count(value.entitlements.analysis_limit) || !count(value.entitlements.idea_generation_limit) ||
    !record(value.usage) || !count(value.usage.analyses) || !count(value.usage.idea_generations) ||
    !record(value.period) || !date(value.period.starts_at) || !date(value.period.ends_at) ||
    typeof value.can_manage_billing !== 'boolean') throw new ServiceError(502, 'Invalid billing response.');
  return value as Billing;
}
function path(id: string) {
  if (!isUUID(id)) throw new TypeError('Expected a company UUID.');
  return `/api/companies/${encodeURIComponent(id)}/billing`;
}
export function createBillingApi(fetcher: typeof fetch = (...args) => apiFetch(...args)) {
  return {
    async read(id: string, signal: AbortSignal): Promise<Billing> {
      const response = await fetcher(path(id), { signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]), cache: 'no-store' });
      if (!response.ok) throw await billingError(response);
      return parseBilling(await response.json().catch(() => null));
    },
    async destination(id: string, kind: 'checkout' | 'portal', signal: AbortSignal): Promise<string> {
      const response = await fetcher(`${path(id)}/${kind}`, { method: 'POST', signal: AbortSignal.any([signal, AbortSignal.timeout(20000)]), cache: 'no-store' });
      if (!response.ok) throw await billingError(response);
      const body: unknown = await response.json().catch(() => null);
      const url = record(body) && typeof body.url === 'string' ? new URL(body.url) : null;
      if (!url || url.protocol !== 'https:' || url.hostname !== (kind === 'checkout' ? 'checkout.stripe.com' : 'billing.stripe.com')) throw new ServiceError(502, 'Invalid billing destination.');
      return url.href;
    },
  };
}
export const billingApi = createBillingApi();
