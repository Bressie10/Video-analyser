import { useCallback, useState } from 'react';
import { ArrowRight, ChevronRight } from 'lucide-react';
import { CompanyScopeBoundary, useCompany, useCompanyQuery } from '../company/CompanyProvider';
import { useAppPage } from './navigation';
import { Button } from '../ui/controls';
import { Alert, LoadingState, PageLayout } from '../ui/layout';
import { analysisStatus, defaultFilters, loadContent, publicationDate, typeLabel } from '../content/contentApi';
import { emptyFilters, ideaApi } from '../ideas/ideaApi';
import type { MetaConnectionStatus } from '../MetaConnection';
import './overview.css';

export function WorkspaceOverview({ metaStatus = 'checking' }: { metaStatus?: MetaConnectionStatus }) {
  const page = useAppPage();
  const { activeCompany } = useCompany();
  if (page !== 'overview' || !activeCompany) return null;
  return <CompanyScopeBoundary><Overview metaStatus={metaStatus} /></CompanyScopeBoundary>;
}

function Overview({ metaStatus }: { metaStatus: MetaConnectionStatus }) {
  const { activeCompany } = useCompany();
  const [revision, revise] = useState(0);
  const recentLoad = useCallback((company: string, signal: AbortSignal) => loadContent(company, signal, defaultFilters, 0, 4), []);
  const analysedLoad = useCallback((company: string, signal: AbortSignal) => loadContent(company, signal, { ...defaultFilters, analyzed: true }), []);
  const ideasLoad = useCallback((company: string, signal: AbortSignal) => ideaApi.history(company, emptyFilters, null, signal), []);
  const recent = useCompanyQuery(`overview-recent:${revision}`, recentLoad);
  const analysed = useCompanyQuery(`overview-analysed:${revision}`, analysedLoad);
  const ideas = useCompanyQuery(`overview-ideas:${revision}`, ideasLoad);
  const accounts = activeCompany!.accounts;
  const metaConnected = metaStatus === 'connected';
  const canManage = activeCompany!.role === 'owner';
  const publishing = accounts.some(account => account.platform === 'facebook' || account.platform === 'instagram');
  const ads = accounts.some(account => account.platform === 'meta_ads');
  const content = recent.data?.items ?? [];
  const savedIdeas = ideas.data?.items ?? [];
  const hasAnalysis = Boolean(analysed.data?.items.length);
  const hasWork = content.length + savedIdeas.length > 0;
  const processing = content.some(item => ['queued', 'pending', 'processing', 'running', 'downloading', 'analyzing'].includes(item.analysis_state));
  const failed = content.some(item => item.analysis_state === 'failed');
  const readiness = hasAnalysis ? { label: 'READY TO CREATE', message: 'Analysed videos are available as idea sources', href: '#content', action: 'Review content' }
    : metaStatus === 'error' ? { label: 'CONNECTION ISSUE', message: 'Meta connection status is unavailable. Review the connection in Settings.', href: '#settings', action: 'Review connection' }
    : metaStatus === 'checking' || metaStatus === 'connecting' ? { label: 'CHECKING CONNECTION', message: 'Checking whether Meta is connected', href: '#settings', action: 'Review connection' }
    : !metaConnected ? { label: 'CONNECT META', message: canManage ? 'Connect Meta to bring your content into this workspace' : 'A workspace owner needs to connect Meta', href: '#settings', action: 'Review connection' }
    : !publishing ? { label: 'LINK CONTENT', message: canManage ? 'Link a publishing account to see your content' : 'A workspace owner needs to link a publishing account', href: '#settings', action: 'Review accounts' }
    : processing ? { label: 'ANALYSIS RUNNING', message: 'Some videos are still being analysed', href: '#content', action: 'Review content' }
    : failed ? { label: 'NEEDS ATTENTION', message: 'Some videos need an analysis retry', href: '#content', action: 'Review content' }
    : { label: 'BUILD YOUR LIBRARY', message: content.length ? 'Analyse a video to make it an idea source' : 'Your connected content will appear here', href: '#content', action: 'Review content' };
  const work = [
    ...savedIdeas.slice(0, 3).map(idea => ({ id: idea.id, title: idea.title.trim() || 'Untitled idea', meta: `Idea · ${idea.status} · ${publicationDate(idea.createdAt)}`, date: idea.createdAt, href: '#ideas' })),
    ...content.map(item => ({ id: item.library_item_id, title: item.display_title.trim() || `${typeLabel(item.content_type)} video`, meta: `${typeLabel(item.content_type)} · ${analysisStatus(item).label} · ${publicationDate(item.published_at)}`, date: item.published_at, href: '#content' })),
  ].sort((a, b) => Date.parse(b.date || '') - Date.parse(a.date || '')).slice(0, 4);
  const primaryLabel = hasAnalysis ? 'Create an idea' : metaStatus === 'error' ? 'Review connection'
    : metaStatus === 'checking' || metaStatus === 'connecting' ? 'Review setup'
      : !metaConnected || !publishing ? canManage ? 'Connect content' : 'Review setup' : 'Review content';
  const primaryHref = hasAnalysis ? '#generate' : metaStatus === 'error' || !metaConnected || !publishing ? '#settings' : '#content';
  const retry = <Button onClick={() => revise(value => value + 1)}>Refresh Home</Button>;
  return <PageLayout className="cm-home">
    <div className="cm-home-heading"><div><h1>Home</h1><p>Today in {activeCompany!.name}</p></div><a className="cm-feature-link cm-feature-link--primary" href={primaryHref}>{primaryLabel}</a></div>
    <div className="cm-home-readiness"><div><strong>{readiness.label}</strong><p>{readiness.message}</p></div><a href={readiness.href}>{readiness.action} <ArrowRight size={18} aria-hidden="true" /></a></div>
    <div className="cm-home-columns"><section className="cm-home-work" aria-labelledby="home-work-title"><header><h2 id="home-work-title">Recent work</h2><a href={savedIdeas.length ? '#ideas' : '#content'}>View all <ArrowRight size={18} aria-hidden="true" /></a></header>
      {(recent.status === 'loading' || ideas.status === 'loading') && <LoadingState label="Loading recent work…" />}
      {(recent.status === 'error' || ideas.status === 'error') && <Alert tone="danger"><p>Recent work could not be loaded.</p>{retry}</Alert>}
      {recent.status !== 'loading' && ideas.status !== 'loading' && work.length > 0 && <ul>{work.map(item => <li key={`${item.href}:${item.id}`}><a href={item.href}><span><strong>{item.title}</strong><small>{item.meta}</small></span><ChevronRight size={20} aria-hidden="true" /></a></li>)}</ul>}
      {recent.status !== 'loading' && ideas.status !== 'loading' && !hasWork && recent.status !== 'error' && ideas.status !== 'error' && <div className="cm-home-empty"><p>Your first content and ideas will appear here.</p><a href={publishing ? '#content' : '#settings'}>{publishing ? 'Open content' : 'Review connections'} <ArrowRight size={16} aria-hidden="true" /></a></div>}
    </section><section className="cm-home-setup" aria-labelledby="home-setup-title"><header><div><h2 id="home-setup-title">Workspace setup</h2><p>{activeCompany!.name}</p></div></header>
      <ul><li><a href="#settings"><span><strong>Meta authorization</strong><small>{metaConnected ? 'Connected' : metaStatus === 'error' ? 'Connection issue' : metaStatus === 'checking' || metaStatus === 'connecting' ? 'Checking' : 'Needs connection'}</small></span><i className={metaConnected ? 'is-ready' : 'is-needed'} aria-hidden="true" /><ChevronRight size={17} aria-hidden="true" /></a></li>
        <li><a href="#settings"><span><strong>Publishing account</strong><small>{publishing ? 'Linked' : 'Needs linking'}</small></span><i className={publishing ? 'is-ready' : 'is-needed'} aria-hidden="true" /><ChevronRight size={17} aria-hidden="true" /></a></li>
        <li><a href="#settings"><span><strong>Ads account</strong><small>{ads ? 'Linked' : 'Needs linking'}</small></span><i className={ads ? 'is-ready' : 'is-needed'} aria-hidden="true" /><ChevronRight size={17} aria-hidden="true" /></a></li></ul>
      {(!metaConnected || !publishing || !ads) && <p className="cm-home-setup-action"><a href="#settings">{canManage ? !metaConnected ? 'Connect Meta' : !publishing ? 'Link publishing account' : 'Link Ads account' : 'Review setup'} <ArrowRight size={18} aria-hidden="true" /></a><small>{!canManage ? 'A workspace owner manages connections.' : !ads && metaConnected && publishing ? 'Required before ad comparisons can run.' : 'Continue setup in Settings.'}</small></p>}
      {analysed.status === 'error' && <Alert tone="danger"><p>Analysis readiness is unavailable.</p>{retry}</Alert>}
    </section></div>
  </PageLayout>;
}
