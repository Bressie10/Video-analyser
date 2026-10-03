import { Check, Circle, ArrowRight } from 'lucide-react';
import { useState } from 'react';
import { useCompany } from '../company/CompanyProvider';
import { Button, Select } from '../ui/controls';
import { Alert, Badge, Panel, SectionHeader } from '../ui/layout';
import { navigate, type AppPage } from '../shell/navigation';
import { useOnboarding } from './OnboardingProvider';
import type { Step } from './onboardingApi';
import './onboarding.css';

const sequence: { id: Step; label: string }[] = [
  { id: 'workspace', label: 'Create workspace' }, { id: 'meta', label: 'Connect Meta' },
  { id: 'account', label: 'Link Instagram or Facebook' }, { id: 'analysis', label: 'Analyze your first content' },
  { id: 'idea', label: 'Generate your first idea' },
];
function Progress({ value }: { value: number }) {
  return <div className="onboarding-progress"><div className="onboarding-progress-copy"><strong>Setup progress</strong><span>{value}% complete</span></div>
    <div className="onboarding-progress-track" role="progressbar" aria-label="Setup progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} aria-valuetext={`${value}% complete`}><span style={{ width: `${value}%` }} /></div></div>;
}
function Steps({ current, compact = false }: { current: Record<Step, boolean>; compact?: boolean }) {
  return <ol className={`onboarding-steps ${compact ? 'is-compact' : ''}`}>{sequence.map((step, index) => <li key={step.id} className={current[step.id] ? 'is-done' : ''}>
    <span className="onboarding-step-icon" aria-hidden="true">{current[step.id] ? <Check size={18} /> : <Circle size={18} />}</span>
    <span><strong>{compact ? step.label : `${index + 1}. ${step.label}`}</strong><span className="onboarding-step-status">{current[step.id] ? 'Complete' : 'To do'}</span></span>
  </li>)}</ol>;
}
export function OnboardingScreen({ page, onManage, onSwitchCompany, onConnect }: { page: AppPage; onManage(): void; onSwitchCompany(id: string): void; onConnect(): void }) {
  const onboarding = useOnboarding();
  const company = useCompany();
  const [choice, setChoice] = useState('');
  const state = onboarding.data;
  if (!state || page !== 'overview') return null;
  const available = company.companies.filter(c => !c.archived);
  const setupCompany = available.find(c => c.id === state.company_id);
  const next = sequence.find(step => step.id === state.next_step) ?? sequence.find(step => !state.steps[step.id]);
  const action = next?.id;
  const navigateTo = (destination: AppPage) => { navigate(destination); };
  const actionButton = () => {
    if (!action) return null;
    if (action === 'workspace') return <Button variant="primary" onClick={onManage}>Create workspace</Button>;
    if (!state.company_id) return <p>Choose a company above to continue setup.</p>;
    if (state.company_id && !setupCompany) return <p role="alert">Your setup company is unavailable. Choose an accessible company below.</p>;
    if (state.company_id && company.activeCompanyId !== state.company_id) return <Button variant="primary" onClick={() => onSwitchCompany(state.company_id!)}>Switch to setup workspace</Button>;
    if (action === 'meta') return <Button variant="primary" onClick={onConnect}>Connect Meta</Button>;
    if (action === 'account') return <Button variant="primary" onClick={() => navigateTo('settings')}>Link Instagram or Facebook</Button>;
    if (action === 'analysis') return <Button variant="primary" onClick={() => navigateTo('content')}>Analyze your first content</Button>;
    return <Button variant="primary" onClick={() => navigateTo('generate')}>Generate your first idea</Button>;
  };
  const companyPicker = available.length > 0 && <div className="onboarding-company-picker"><label htmlFor="onboarding-company">Choose a company for setup</label>
    <div><Select id="onboarding-company" value={choice} onChange={event => setChoice(event.target.value)} disabled={onboarding.busy}><option value="">Select a company</option>{available.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
      <Button disabled={!choice || onboarding.busy} onClick={() => void onboarding.selectCompany(choice)}>Use for setup</Button></div></div>;
  if (onboarding.mode === 'welcome') return <section className="onboarding-welcome" aria-labelledby="onboarding-title"><div className="onboarding-eyebrow">GET STARTED</div>
    <h2 id="onboarding-title">Welcome to ContentMetric</h2><p className="onboarding-lead">Turn your existing content into better ideas.</p>
    <p>Set up your workspace, connect your accounts, and give ContentMetric real content to learn from.</p><Steps current={state.steps} />
    {onboarding.error && <Alert tone="danger" id="onboarding-error">{onboarding.error}</Alert>}
    <div className="onboarding-actions"><Button variant="primary" disabled={onboarding.busy} onClick={() => void onboarding.start()} aria-describedby={onboarding.error ? 'onboarding-error' : undefined}>Start setup</Button>
      <Button variant="ghost" disabled={onboarding.busy} onClick={() => void onboarding.skip()}>Skip for now</Button></div></section>;
  if (onboarding.mode === 'complete') return <Panel className="onboarding-complete"><Badge tone="success">Setup complete</Badge><h2>You're ready to go</h2>
    <p>Your workspace is connected and ContentMetric has enough context to help you generate ideas.</p><div className="onboarding-actions"><Button variant="primary" onClick={onboarding.leave}>Go to Overview</Button>
      <Button onClick={() => navigateTo('generate')}>Generate another idea</Button></div></Panel>;
  if (state.complete) return null;
  if (onboarding.mode !== 'guided') return <Panel className="onboarding-reminder"><div><Badge tone="info">Setup</Badge><h2>Finish setting up ContentMetric</h2>
    <p>Your workspace stays available while you complete setup.</p><Progress value={state.progress} /><Steps current={state.steps} compact />
    {onboarding.error && <Alert tone="danger"><p>{onboarding.error}</p><Button onClick={() => void onboarding.refresh()}>Retry setup</Button></Alert>}</div>
    <Button variant="primary" onClick={onboarding.resume}>Continue setup <ArrowRight size={16} aria-hidden="true" /></Button></Panel>;
  return <section className="onboarding-guided" aria-labelledby="onboarding-title"><div className="onboarding-guided-heading"><div><Badge tone="info">Guided setup</Badge>
    <h2 id="onboarding-title">Set up ContentMetric</h2><p>Connect your workspace and turn published content into useful ideas. You can leave and return at any time.</p></div>
    <Button variant="ghost" disabled={onboarding.busy} onClick={() => void onboarding.skip()}>Skip for now</Button></div>
    <Progress value={state.progress} /><div className="onboarding-grid"><Panel><h3>Setup steps</h3><Steps current={state.steps} /></Panel>
      <Panel className="onboarding-current"><Badge tone="warning">Recommended next step</Badge><h3>{next?.label ?? 'Review your setup'}</h3>
        {action === 'workspace' && <p>Create a company workspace, or choose an existing accessible company for setup.</p>}
        {action === 'meta' && <p>Connect Meta securely to discover the Facebook and Instagram accounts you manage.</p>}
        {action === 'account' && <p>Link a Facebook Page or Instagram account to your setup workspace in Settings. An Ads account alone does not complete this step.</p>}
        {action === 'analysis' && <p>ContentMetric analyzes your existing content so recommendations are grounded in what you've actually published.</p>}
        {action === 'idea' && <p>Use your analyzed content to generate and save your first idea.</p>}
        {companyPicker}{onboarding.error && <Alert tone="danger" id="onboarding-error">{onboarding.error}</Alert>}
        <div className="onboarding-actions">{actionButton()}<Button onClick={() => void onboarding.refresh()} disabled={onboarding.busy}>Refresh progress</Button></div>
        {state.company_id && setupCompany && <p className="onboarding-company-note">Suggested setup workspace: <strong>{setupCompany.name}</strong></p>}
      </Panel></div></section>;
}
