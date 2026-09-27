import type { HTMLAttributes, ReactNode } from 'react';

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';
export function Badge({ tone = 'neutral', className = '', ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={`ui-badge ui-tone--${tone} ${className}`} {...props} />;
}
export function Panel({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`ui-panel ${className}`} {...props} />;
}
type HeaderProps = { title: string; description?: ReactNode; actions?: ReactNode; id?: string };
export function PageHeader({ title, description, actions, id }: HeaderProps) {
  return <header className="ui-page-header"><div><h1 id={id}>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="ui-actions">{actions}</div>}</header>;
}
export function SectionHeader({ title, description, actions, id }: HeaderProps) {
  return <header className="ui-section-header"><div><h2 id={id}>{title}</h2>{description && <p>{description}</p>}</div>{actions && <div className="ui-actions">{actions}</div>}</header>;
}
export function EmptyState({ title, children, icon, action }: { title: string; children: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  return <div className="ui-empty-state">{icon && <div className="ui-empty-icon" aria-hidden="true">{icon}</div>}<h2>{title}</h2><div className="ui-empty-description">{children}</div>{action}</div>;
}
export function Divider() { return <hr className="ui-divider" />; }
export function Alert({ tone = 'info', className = '', ...props }: HTMLAttributes<HTMLDivElement> & { tone?: Tone }) {
  return <div role={tone === 'danger' ? 'alert' : 'status'} className={`ui-alert ui-tone--${tone} ${className}`} {...props} />;
}
export function Skeleton({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={`ui-skeleton ${className}`} {...props} />;
}
export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <div className="ui-loading" role="status"><Skeleton /><span>{label}</span></div>;
}
export function PageLayout({ width = 'wide', className = '', ...props }: HTMLAttributes<HTMLDivElement> & { width?: 'wide' | 'reading' | 'form' }) {
  return <div className={`ui-page-layout ui-page-layout--${width} ${className}`} {...props} />;
}
export function TableContainer({ label, className = '', ...props }: HTMLAttributes<HTMLDivElement> & { label: string }) {
  return <div role="region" aria-label={label} tabIndex={0} className={`ui-table-container ${className}`} {...props} />;
}
