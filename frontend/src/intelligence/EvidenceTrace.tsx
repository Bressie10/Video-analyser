import { type RefObject } from 'react';
import { Film, X } from 'lucide-react';
import { type Cited, type Difference, type Preview, timeLabel } from './intelligenceModel';

export function EvidenceTrace({ difference, entries, activeRef, previews, onChoose, onClose, dialogRef, labels }: {
  difference: Difference | null; entries: Cited[]; activeRef: string | null; previews: Preview[];
  onChoose(ref: string): void; onClose(): void; dialogRef: RefObject<HTMLDialogElement | null>;
  labels: Map<string, string>;
}) {
  const current = entries.find(item => item.citation.evidence_ref === activeRef) ?? entries[0];
  const preview = previews.find(item => item.video_ref === current?.citation.video_ref);
  const moment = current ? entries.filter(item => item.citation.video_ref === current.citation.video_ref &&
    item.citation.timestamp_seconds === current.citation.timestamp_seconds) : [];
  const exactFrame = moment.some(item => item.citation.evidence_type === 'frame' && preview?.frame_ref === item.citation.evidence_ref);
  const maxTime = Math.max(1, ...entries.map(item => item.citation.timestamp_seconds));
  const currentLabel = current ? labels.get(current.citation.video_ref) : undefined;
  const currentGroup = currentLabel ? 'ABC'.includes(currentLabel) ? 'higher metric group' : 'lower metric group' : 'group unavailable';
  return <dialog ref={dialogRef} className="ci-evidence-dialog" aria-labelledby="ci-evidence-title" onClose={onClose}>
    {difference && <><header className="ci-evidence-head"><div><span>EVIDENCE TRACE</span><h2 id="ci-evidence-title">{difference.description}</h2>
      <p>{difference.higher_group_support}/{difference.higher_group_size} higher · {difference.lower_group_support}/{difference.lower_group_size} lower</p></div>
      <button type="button" onClick={onClose} aria-label="Close evidence"><X size={18} /></button></header>
      {current ? <div className="ci-evidence-body">
        <div className="ci-evidence-switcher" aria-label="Cited creatives">{entries.map(item => <button type="button" key={item.citation.evidence_ref}
          className={item.role} aria-pressed={item.citation.evidence_ref === current.citation.evidence_ref} onClick={() => onChoose(item.citation.evidence_ref)}>
          {item.role === 'counterexample' ? '◆' : '●'} Creative {labels.get(item.citation.video_ref) ?? item.citation.video_ref} · {timeLabel(item.citation.timestamp_seconds)}</button>)}</div>
        <div className="ci-evidence-current"><strong>{timeLabel(current.citation.timestamp_seconds)}</strong><span>{current.role === 'counterexample' ? '◆ Counterexample' : '● Supporting citation'} · {currentGroup} · {current.citation.evidence_type}</span></div>
        {exactFrame && preview ? <figure className="ci-evidence-frame"><img src={`data:image/jpeg;base64,${preview.jpeg_base64}`} alt="Bounded sampled frame for this exact citation" /><figcaption>Source frame · {timeLabel(preview.timestamp_seconds)}</figcaption></figure>
          : preview ? <figure className="ci-evidence-frame is-preview"><img src={`data:image/jpeg;base64,${preview.jpeg_base64}`} alt="Creative preview; not the cited evidence frame" /><figcaption>Creative preview · cited frame unavailable</figcaption></figure>
            : <div className="ci-evidence-no-frame"><Film aria-hidden="true" />Frame preview unavailable for this citation</div>}
        <div className="ci-evidence-timeline"><span>0s</span><span className="ci-evidence-line"><i style={{ left: `${current.citation.timestamp_seconds / maxTime * 100}%` }} /></span><span>{timeLabel(maxTime)} latest cited</span></div>
        <div className="ci-evidence-bundle"><span className="ci-evidence-stem" aria-hidden="true" />
          <div><b>CITED MOMENT · {moment.length} {moment.length === 1 ? 'SOURCE' : 'SOURCES'}</b>
            {moment.map(item => <p key={item.citation.evidence_ref}><b>{item.citation.evidence_type.toUpperCase()}</b>{' '}
              {item.citation.excerpt ? <q>{item.citation.excerpt}</q> : item.citation.evidence_type === 'frame' ? 'Sampled source frame' : 'Validated citation; no text excerpt returned'}</p>)}</div>
          <div><b>RELATIONSHIP</b><p>{current.role === 'counterexample' ? 'This creative also contains the cited feature in the opposite metric group.' : 'This citation supports the validated observation.'}</p></div>
        </div>
        <details><summary>Reference details</summary><p>Video: <code>{current.citation.video_ref}</code></p><p>Evidence: <code>{current.citation.evidence_ref}</code></p></details>
      </div> : <div className="ci-evidence-body"><p>No inspectable citation was returned for this observation.</p></div>}
    </>}
  </dialog>;
}
