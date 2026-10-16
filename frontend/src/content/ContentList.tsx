import { useState } from 'react';
import { Clapperboard, Film, Megaphone } from 'lucide-react';
import { Badge } from '../ui/layout';
import { Button } from '../ui/controls';
import { analysisStatus, platformLabel, publicationDate, typeLabel, type ContentItem } from './contentApi';

function Preview({ item, companyId }: { item: ContentItem; companyId?: string }) {
  const [failed, setFailed] = useState(false);
  const Icon = item.content_type === 'reel' ? Clapperboard : item.content_type === 'ad' ? Megaphone : Film;
  return <div className="cm-content-format">
    {companyId && item.content_type !== 'ad' && !failed
      ? <img src={`/api/companies/${companyId}/content/${item.library_item_id}/preview`}
          alt="" loading="lazy" onError={() => setFailed(true)} />
      : <><Icon size={25} strokeWidth={1.5} aria-hidden="true" /><span>Preview unavailable</span></>}
  </div>;
}

export function ContentList({ items, companyId, compact = false, onAnalyze, analyzing }: { items: ContentItem[]; companyId?: string; compact?: boolean; onAnalyze?: (id: string) => void; analyzing?: string | null }) {
  return <ul className={`cm-content-list${compact ? ' cm-content-list--compact' : ''}`} aria-label="Content items">
    {items.map(item => {
      const status = analysisStatus(item);
      const duration = item.summary?.duration_seconds;
      const width = item.summary?.width, height = item.summary?.height;
      const href = `#content/${item.library_item_id}`;
      return <li key={item.library_item_id} className={`cm-content-row${item.analyzed ? ' is-inspectable' : ''}`}>
        {item.analyzed && <a className="cm-content-row-link" href={href} aria-label={`Open analysis for ${item.display_title}`} />}
        <Preview item={item} companyId={companyId} />
        <div className="cm-content-copy"><h3>{item.display_title.trim() || `${platformLabel(item.platform)} ${typeLabel(item.content_type).toLowerCase()}`}</h3>
          <p className="cm-content-meta"><span>{platformLabel(item.platform)}</span><span>{typeLabel(item.content_type)}</span>
            {typeof duration === 'number' && Number.isFinite(duration) && duration >= 0 && <span>{duration.toFixed(1)} sec</span>}
            {!compact && typeof width === 'number' && width > 0 && typeof height === 'number' && height > 0 && <span>{width} × {height}</span>}
          </p>
        </div>
        <div className="cm-content-date">{publicationDate(item.published_at)}</div>
        <div className="cm-content-status"><Badge tone={status.tone}>{status.label}</Badge>
          {!compact && onAnalyze && item.content_type !== 'ad' && !item.analyzed && !['queued', 'processing'].includes(item.analysis_state) &&
            <Button disabled={Boolean(analyzing)} onClick={event => { event.stopPropagation(); onAnalyze(item.library_item_id); }}>{analyzing === item.library_item_id ? 'Starting…' : item.analysis_state === 'failed' ? 'Retry analysis' : 'Analyze'}</Button>}
        </div>
      </li>;
    })}
  </ul>;
}
