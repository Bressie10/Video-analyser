import { Clapperboard, Film, Megaphone } from 'lucide-react';
import { Badge } from '../ui/layout';
import { Button } from '../ui/controls';
import { analysisStatus, platformLabel, publicationDate, typeLabel, type ContentItem } from './contentApi';

/** The company-safe API has no preview URLs. Use a format marker, never a fabricated thumbnail. */
export function ContentList({ items, compact = false, onAnalyze, analyzing }: { items: ContentItem[]; compact?: boolean; onAnalyze?: (id: string) => void; analyzing?: string | null }) {
  return <ul className={`cm-content-list${compact ? ' cm-content-list--compact' : ''}`} aria-label="Content items">
    {items.map(item => {
      const Icon = item.content_type === 'reel' ? Clapperboard : item.content_type === 'ad' ? Megaphone : Film;
      const status = analysisStatus(item);
      const duration = item.summary?.duration_seconds;
      const width = item.summary?.width, height = item.summary?.height;
      return <li key={item.library_item_id} className="cm-content-row">
        <div className="cm-content-format" aria-hidden="true"><Icon size={24} strokeWidth={1.5} /></div>
        <div className="cm-content-copy"><h3>{item.display_title.trim() || `${platformLabel(item.platform)} ${typeLabel(item.content_type).toLowerCase()}`}</h3>
          <p className="cm-content-meta"><span>{platformLabel(item.platform)}</span><span>{typeLabel(item.content_type)}</span>
            {typeof duration === 'number' && Number.isFinite(duration) && duration >= 0 && <span>{duration.toFixed(1)} sec</span>}
            {!compact && typeof width === 'number' && width > 0 && typeof height === 'number' && height > 0 && <span>{width} × {height}</span>}
          </p>
        </div>
        <div className="cm-content-date">{publicationDate(item.published_at)}</div>
        <div className="cm-content-status"><Badge tone={status.tone}>{status.label}</Badge>
          {!compact && onAnalyze && item.content_type !== 'ad' && !item.analyzed && !['queued', 'pending', 'processing', 'running', 'downloading', 'analyzing'].includes(item.analysis_state) &&
            <Button disabled={Boolean(analyzing)} onClick={() => onAnalyze(item.library_item_id)}>{analyzing === item.library_item_id ? 'Starting…' : item.analysis_state === 'failed' ? 'Retry analysis' : 'Analyze'}</Button>}
        </div>
      </li>;
    })}
  </ul>;
}
