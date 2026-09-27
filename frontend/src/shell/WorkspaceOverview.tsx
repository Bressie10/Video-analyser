import { useCallback, useState } from 'react';
import { ArrowRight, BookOpen, Library, Sparkles } from 'lucide-react';
import { CompanyScopeBoundary, useCompany, useCompanyQuery } from '../company/CompanyProvider';
import { useAppPage } from './navigation';
import { Button } from '../ui/controls';
import { Alert, Badge, EmptyState, LoadingState, PageLayout, Panel, SectionHeader } from '../ui/layout';
import { defaultFilters, loadContent, platformLabel, publicationDate } from '../content/contentApi';
import { ContentList } from '../content/ContentList';
import { emptyFilters, ideaApi } from '../ideas/ideaApi';
import '../content/content.css';
import './overview.css';

export function WorkspaceOverview() {
  const page = useAppPage();
  const { activeCompany } = useCompany();
  // The shell owns no-company and account-linking onboarding. Fetch only on this destination.
  if (page !== 'overview' || !activeCompany?.accounts.length) return null;
  return <CompanyScopeBoundary><Overview /></CompanyScopeBoundary>;
}
function Overview() {
  const { activeCompany } = useCompany();
  const [revision, revise] = useState(0);
  const recentLoad = useCallback((company: string, signal: AbortSignal) => loadContent(company, signal, defaultFilters, 0, 4), []);
  const analysedLoad = useCallback((company: string, signal: AbortSignal) => loadContent(company, signal, { ...defaultFilters, analyzed: true }), []);
  const ideasLoad = useCallback((company: string, signal: AbortSignal) => ideaApi.history(company, emptyFilters, null, signal), []);
  const recent = useCompanyQuery(`overview-recent:${revision}`, recentLoad);
  const analysed = useCompanyQuery(`overview-analysed:${revision}`, analysedLoad);
  const ideas = useCompanyQuery(`overview-ideas:${revision}`, ideasLoad);
  const platforms = [...new Set(activeCompany!.accounts.map(account => account.platform))];
  const hasSources = Boolean(analysed.data?.items.length);
  const retry = <Button onClick={() => revise(value => value + 1)}>Refresh overview</Button>;
  return <PageLayout className="cm-overview">
    <SectionHeader title="Your workspace at a glance" description={`Content and creative activity for ${activeCompany!.name}.`}
      actions={<a className="cm-feature-link cm-feature-link--primary" href="#generate"><Sparkles size={18} aria-hidden="true" />Generate idea</a>} />
    <div className="cm-overview-summary">
      <Panel><h3>Linked platforms</h3><div className="cm-overview-platforms">{platforms.map(platform => <Badge key={platform} tone="neutral">{platformLabel(platform)}</Badge>)}</div>
        <p>{activeCompany!.accounts.length} linked {activeCompany!.accounts.length === 1 ? 'account' : 'accounts'}</p><a href="#settings">Manage connections <ArrowRight size={14} aria-hidden="true" /></a></Panel>
      <Panel><h3>Ready for new ideas</h3>
        {analysed.status === 'loading' && <LoadingState label="Checking analysed content…" />}
        {analysed.status === 'error' && <Alert tone="danger"><p>Analysed content is unavailable.</p>{retry}</Alert>}
        {analysed.data && <><p className="cm-overview-count"><strong>{analysed.data.items.length}{analysed.data.next_offset !== null ? '+' : ''}</strong> analysed {analysed.data.items.length === 1 ? 'video' : 'videos'}</p>
          <p>{analysed.data.next_offset !== null ? 'At least 20 videos are ready to use as sources.' : hasSources ? 'Ready to inform your next idea and script.' : 'Analysed videos will become sources for new ideas.'}</p><a href="#content">Explore content <ArrowRight size={14} aria-hidden="true" /></a></>}
      </Panel>
    </div>
    <div className="cm-overview-section" role="region" aria-label="Recent content">
      <SectionHeader title="Recent content" description="The latest published items in your library." actions={<a className="cm-feature-link" href="#content">View library <ArrowRight size={16} aria-hidden="true" /></a>} />
      {recent.status === 'loading' && <LoadingState label="Loading recent content…" />}
      {recent.status === 'error' && <Alert tone="danger"><p>Recent content could not be loaded.</p>{retry}</Alert>}
      {recent.data && (recent.data.items.length ? <ContentList items={recent.data.items} compact /> : <Panel><EmptyState title="Waiting for your first content" icon={<Library size={28} />} action={<a className="cm-feature-link" href="#settings">Review linked accounts <ArrowRight size={16} aria-hidden="true" /></a>}><p>Your accounts are linked. Content will appear here when it is available in your library.</p></EmptyState></Panel>)}
    </div>
    {analysed.data && !hasSources && Boolean(recent.data?.items.length) && <Panel className="cm-overview-next"><Library size={22} aria-hidden="true" /><div><h3>Your content is here. Analysis is next.</h3><p>Browse the library to see which videos are processing or still awaiting analysis.</p></div><a className="cm-feature-link" href="#content">View analysis status <ArrowRight size={16} aria-hidden="true" /></a></Panel>}
    <div className="cm-overview-section" role="region" aria-label="Recent ideas">
      <SectionHeader title="Recent ideas" description="Pick up a saved idea and continue shaping it." actions={<a className="cm-feature-link" href="#ideas">View ideas <ArrowRight size={16} aria-hidden="true" /></a>} />
      {ideas.status === 'loading' && <LoadingState label="Loading recent ideas…" />}
      {ideas.status === 'error' && <Alert tone="danger"><p>Recent ideas could not be loaded.</p>{retry}</Alert>}
      {ideas.data && (ideas.data.items.length ? <ul className="cm-overview-ideas" aria-label="Saved ideas">{ideas.data.items.slice(0, 3).map(idea => <li key={idea.id}>
        <BookOpen size={20} aria-hidden="true" /><div><h3>{idea.title.trim() || 'Untitled idea'}</h3><p>Created {publicationDate(idea.createdAt)}</p></div><Badge tone={idea.status === 'published' ? 'success' : 'neutral'}>{({ draft: 'Draft', used: 'Used', published: 'Published', discarded: 'Discarded' })[idea.status]}</Badge>
      </li>)}</ul> : <Panel><EmptyState title={hasSources ? 'Turn your content into a new idea' : 'Your ideas will live here'} icon={<Sparkles size={28} />}
        action={hasSources ? <a className="cm-feature-link cm-feature-link--primary" href="#generate">Generate your first idea <ArrowRight size={16} aria-hidden="true" /></a> : <a className="cm-feature-link" href="#content">Explore your content <ArrowRight size={16} aria-hidden="true" /></a>}>
        <p>{hasSources ? 'Your analysed videos are ready. Use what you’ve learned to create your next concept and script.' : 'Once you generate an idea, it will be saved here for you to revisit.'}</p>
      </EmptyState></Panel>)}
    </div>
  </PageLayout>;
}
