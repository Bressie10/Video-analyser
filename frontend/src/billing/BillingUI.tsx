import { useEffect, useRef, useState } from 'react';
import { Button } from '../ui/controls';
import { Alert, LoadingState } from '../ui/layout';
import { billingApi, billingMessage, type Billing, type LimitCode } from './billingApi';
import { useBilling, type BillingState } from './BillingProvider';
import './billing.css';

export function billingDate(value: string) { return new Date(value).toLocaleDateString('en-IE', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }); }
export function UsageIndicator({ label, used, limit }: { label: string; used: number; limit: number }) {
  const atLimit = used >= limit;
  return <div className="billing-usage"><div><strong>{label}</strong><span>{used} of {limit} used</span></div>
    <progress max={limit || 1} value={Math.min(used, limit)} aria-label={`${label}: ${used} of ${limit} used`} />
    {atLimit && <small>Reached for this period</small>}</div>;
}
export function LimitNotice({ code, billing, onUpgrade }: { code: LimitCode; billing?: Billing; onUpgrade?: () => void }) {
  const free = billing?.effective_plan !== 'pro';
  const title = code === 'analysis_limit_reached' ? "You've used this period's analysis allowance." : code === 'idea_generation_limit_reached' ? "You've used this period's idea allowance." : code === 'organic_account_limit_reached' ? 'Publishing account limit reached.' : 'Your Free plan includes one workspace.';
  const usage = code === 'analysis_limit_reached' ? billing && `${billing.usage.analyses} of ${billing.entitlements.analysis_limit} analyses used` : code === 'idea_generation_limit_reached' ? billing && `${billing.usage.idea_generations} of ${billing.entitlements.idea_generation_limit} ideas used` : null;
  return <Alert tone="warning" className="billing-limit"><strong>{title}</strong>
    {usage && <p>{usage}</p>}
    {code === 'free_workspace_limit_reached' && <p>Upgrade an existing workspace to Pro before creating another Free workspace.</p>}
    {code === 'organic_account_limit_reached' && <p>Existing accounts stay linked. Your plan limits new Instagram and Facebook links; Ads accounts are separate.</p>}
    {!free && billing && <p>Resets {billingDate(billing.period.ends_at)}.</p>}
    {free && billing?.can_manage_billing && onUpgrade && <Button onClick={onUpgrade}>Upgrade to Pro</Button>}
    {(!free || !billing?.can_manage_billing) && <a href="#settings">View Billing in Settings</a>}
  </Alert>;
}
export function BillingSection({ companyId, activeCompanyId }: { companyId: string; activeCompanyId: string | null }) {
  const active = useBilling();
  const [other, setOther] = useState<{ id: string; state: BillingState }>({ id: '', state: { status: 'idle' } });
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const actionController = useRef<AbortController | null>(null);
  useEffect(() => () => actionController.current?.abort(), []);
  useEffect(() => {
    if (companyId === activeCompanyId) return;
    const controller = new AbortController();
    setOther({ id: companyId, state: { status: 'loading' } });
    void billingApi.read(companyId, controller.signal).then(data => {
      if (!controller.signal.aborted) setOther({ id: companyId, state: { status: 'success', data } });
    }).catch(error => { if (!controller.signal.aborted) setOther({ id: companyId, state: { status: 'error', error } }); });
    return () => controller.abort();
  }, [companyId, activeCompanyId, retry]);
  const state = companyId === activeCompanyId ? active.state : other.id === companyId ? other.state : { status: 'loading' as const };
  const data = state.status === 'success' ? state.data : undefined;
  const act = async (kind: 'checkout' | 'portal') => {
    if (!data?.can_manage_billing || busy) return;
    setBusy(true); setActionError('');
    const controller = new AbortController();
    actionController.current = controller;
    try {
      const url = await billingApi.destination(companyId, kind, controller.signal);
      if (controller.signal.aborted) return;
      active.markReturn(kind, companyId);
      window.location.assign(url);
    } catch (error) { if (!controller.signal.aborted) { setActionError(billingMessage(error)); setBusy(false); } }
  };
  return <section className="settings-section billing-section" aria-labelledby="settings-billing">
    <h2 id="settings-billing" tabIndex={-1}>Billing</h2>
    {active.returning && companyId === activeCompanyId && <p role="status">Updating your subscription… Your plan will change here when billing confirms it.</p>}
    {state.status === 'loading' && <LoadingState label="Loading billing…" />}
    {state.status === 'error' && <Alert tone="danger"><p>{billingMessage(state.error)}</p><Button onClick={() => companyId === activeCompanyId ? active.refresh() : setRetry(v => v + 1)}>Retry billing</Button></Alert>}
    {data && <>
      <div className="billing-plan"><div><span>Plan</span><strong>{data.effective_plan === 'pro' ? 'Pro' : 'Free'}</strong><span>{data.effective_plan === 'pro' ? '€19/month per workspace' : '€0'}</span></div></div>
      {data.effective_plan === 'pro' && data.subscription_status === 'past_due' && data.grace_until && <Alert tone="warning"><strong>Payment needs attention</strong><p>Your Pro access is temporarily still active. Update your payment method before {billingDate(data.grace_until)} to avoid returning to Free limits.</p></Alert>}
      {data.effective_plan === 'free' && data.subscription_status && !['canceled'].includes(data.subscription_status) && <Alert tone="warning"><strong>Subscription needs attention</strong><p>Free limits apply until your subscription is active. You can review billing or try upgrading again.</p></Alert>}
      {data.cancel_at_period_end && data.effective_plan === 'pro' && <p className="settings-note">Your Pro subscription is scheduled to end on {billingDate(data.period.ends_at)}.</p>}
      <h3>Usage this period</h3>
      <div className="billing-usage-grid"><UsageIndicator label="Analyses" used={data.usage.analyses} limit={data.entitlements.analysis_limit} /><UsageIndicator label="Ideas" used={data.usage.idea_generations} limit={data.entitlements.idea_generation_limit} /></div>
      <p>{data.effective_plan === 'pro' && !data.cancel_at_period_end ? 'Current period ends' : 'Period resets'} {billingDate(data.period.ends_at)}</p>
      {data.effective_plan === 'free' && <p>Free includes one owned workspace.</p>}
      <p>{data.entitlements.organic_account_limit} organic Instagram/Facebook {data.entitlements.organic_account_limit === 1 ? 'account' : 'accounts'} included. Existing accounts remain visible after a downgrade.</p>
      {data.can_manage_billing && <div className="billing-actions">
        {data.effective_plan === 'free' && <Button variant="primary" disabled={busy} onClick={() => void act('checkout')}>Upgrade to Pro</Button>}
        {(data.effective_plan === 'pro' || data.subscription_status) && <Button disabled={busy} onClick={() => void act('portal')}>Manage subscription</Button>}
      </div>}
      {actionError && <Alert tone="danger">{actionError}</Alert>}
      {data.effective_plan === 'free' && <div className="billing-comparison"><h3>Pro — €19/month per workspace</h3><p>50 analyses · 150 idea generations · 5 organic publishing accounts</p></div>}
    </>}
  </section>;
}
