import { ArrowRight } from 'lucide-react';
import { useCompany } from '../company/CompanyProvider';
import { navigation } from './navigation';

/** A minimal entry point; the Overview feature agent owns the future page content. */
export function WorkspaceOverview() {
  const { activeCompany } = useCompany();
  return <div className="workspace-overview">
    <h2>{activeCompany?.name}</h2>
    <p className="muted">Explore your content, generate a new idea, or pick up a saved draft.</p>
    <div className="workspace-links">{navigation.filter(item => ['content', 'generate', 'ideas'].includes(item.id)).map(({ id, label, icon: Icon, description }) =>
      <a href={`#${id}`} key={id}><Icon size={22} aria-hidden="true" /><span><strong>{label}</strong><span>{description}</span></span><ArrowRight size={18} aria-hidden="true" /></a>
    )}</div>
  </div>;
}
