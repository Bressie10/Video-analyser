import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, Film, Pin, X } from 'lucide-react';
import { apiFetch } from '../auth/apiFetch';
import { useCompany } from '../company/CompanyProvider';
import { formatMetric, metricLabel } from '../intelligence/intelligenceModel';
import { comparisonFor } from './handoff';
import { platformLabel, publicationDate, typeLabel } from '../content/contentApi';
import './creativeAnalysis.css';

type Scene = { scene_number: number; start_seconds: number; end_seconds: number };
type Text = { appearance_seconds: number; disappearance_seconds: number; text: string };
type Speech = { start_seconds: number; end_seconds: number; text: string };
type Motion = { start_seconds: number; end_seconds: number; type: string; confidence: number | null };
type Analysis = { creative_ref: string; label: string; duration_seconds: number | null;
  resolution: { width: number | null; height: number | null }; scenes: Scene[]; ocr: Text[];
  transcript: Speech[]; motion?: Motion[]; performance?: Record<string, number>;
  item?: { id: string; platform: string; content_type: string; published_at: string | null; display_title: string; analysis_state: string };
  media: { state: 'resolution_required' | 'unavailable' } };
type Moment = { id: string; lane: 'scene' | 'text' | 'speech' | 'motion' | 'signal'; start: number; end: number;
  name: string; detail?: string; evidenceRef?: string };
const laneNames = { scene: 'SCENES', text: 'TEXT', speech: 'SPEECH', motion: 'MOTION', signal: 'SIGNALS' } as const;
const laneSymbols = { scene: '▰', text: 'T', speech: '◖', motion: '↗', signal: '◆' } as const;
function motionLabel(type: string) { const labels: Record<string, string> = { camera_pan: 'Camera pan', pan: 'Camera pan', camera_zoom: 'Camera zoom', zoom: 'Camera zoom', camera_shake: 'Camera shake', shake: 'Camera shake', general_motion: 'General motion', local_motion: 'Local motion', unknown: 'Unknown motion' }; return labels[type.toLowerCase()] ?? `Unknown · ${type}`; }
const performanceLabels: Record<string, string> = { view_count: 'Views', like_count: 'Likes / reactions', comment_count: 'Comments', share_count: 'Shares', reach: 'Reach', impressions: 'Impressions' };
function stamp(seconds: number) { const minutes = Math.floor(seconds / 60); return `${String(minutes).padStart(2, '0')}:${(seconds % 60).toFixed(1).padStart(4, '0')}`; }
function validSeconds(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) && value >= 0; }
function parseDetail(value: unknown, content: boolean): Analysis {
  if (!value || typeof value !== 'object') throw Error('Invalid detail');
  const data = value as Analysis;
  if ((content ? !data.item || typeof data.item.id !== 'string' || typeof data.item.display_title !== 'string' || !Array.isArray(data.motion)
                 : typeof data.creative_ref !== 'string' || typeof data.label !== 'string') ||
      !Array.isArray(data.scenes) || !Array.isArray(data.ocr) || !Array.isArray(data.transcript) ||
      !data.media || !['resolution_required', 'unavailable'].includes(data.media.state) ||
      data.duration_seconds !== null && !validSeconds(data.duration_seconds)) throw Error('Invalid detail');
  return data;
}

export function CreativeAnalysisPage({ creativeRef, contentItemId }: { creativeRef?: string; contentItemId?: string }) {
  const content = Boolean(contentItemId);
  const identity = contentItemId ?? creativeRef ?? '';
  const { activeCompany } = useCompany();
  const companyId = activeCompany?.id;
  const context = content ? null : comparisonFor(identity);
  const video = useRef<HTMLVideoElement>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState('');
  const [mediaReady, setMediaReady] = useState(false);
  const [mediaChecking, setMediaChecking] = useState(false);
  const [mediaFailed, setMediaFailed] = useState(false);
  const [clock, setClock] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [pinned, setPinned] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [frame, setFrame] = useState<string | null>(null);
  const requestedFrame = useRef<number | null>(null);
  const initialFocus = useRef(false);
  useEffect(() => {
    if (!companyId) return;
    const controller = new AbortController();
    setAnalysis(null); setError(''); setMediaReady(false); setMediaChecking(false); setMediaFailed(false); setSelected(null); setClock(0); setFrame(null); requestedFrame.current = null; initialFocus.current = false;
    const root = `/api/companies/${companyId}/${content ? 'content' : 'creatives'}/${identity}`;
    async function load() {
      try {
        const response = await apiFetch(`${root}/analysis`, { signal: controller.signal });
        if (!response.ok) throw Error('Stored evidence could not be loaded.');
        const data = parseDetail(await response.json(), content);
        if (controller.signal.aborted) return;
        setAnalysis(data);
        if (data.media.state === 'resolution_required') {
          setMediaChecking(true);
          try {
            const grant = await apiFetch(`${root}/media-access`, { method: 'POST', signal: controller.signal });
            if (!controller.signal.aborted) setMediaReady(grant.ok);
          } catch { if (!controller.signal.aborted) setMediaReady(false); }
          finally { if (!controller.signal.aborted) setMediaChecking(false); }
        }
      } catch { if (!controller.signal.aborted) setError(content ? 'Content analysis is unavailable.' : 'Creative analysis is unavailable.'); }
    }
    void load();
    return () => controller.abort();
  }, [companyId, identity, content]);
  const moments = useMemo(() => {
    if (!analysis) return [];
    const items: Moment[] = [
      ...analysis.scenes.filter(item => validSeconds(item.start_seconds) && validSeconds(item.end_seconds) && item.end_seconds >= item.start_seconds)
        .map((item, index) => ({ id: `scene-${index}`, lane: 'scene' as const, start: item.start_seconds, end: item.end_seconds,
          name: `Scene ${item.scene_number ?? index + 1}` })),
      ...analysis.ocr.filter(item => validSeconds(item.appearance_seconds) && validSeconds(item.disappearance_seconds) && item.disappearance_seconds >= item.appearance_seconds)
        .map((item, index) => ({ id: `text-${index}`, lane: 'text' as const, start: item.appearance_seconds, end: item.disappearance_seconds,
          name: item.text, detail: item.text })),
      ...analysis.transcript.filter(item => validSeconds(item.start_seconds) && validSeconds(item.end_seconds) && item.end_seconds >= item.start_seconds)
        .map((item, index) => ({ id: `speech-${index}`, lane: 'speech' as const, start: item.start_seconds, end: item.end_seconds,
          name: item.text, detail: item.text })),
      ...(analysis.motion ?? []).filter(item => validSeconds(item.start_seconds) && validSeconds(item.end_seconds) && item.end_seconds >= item.start_seconds)
        .map((item, index) => ({ id: `motion-${index}`, lane: 'motion' as const, start: item.start_seconds, end: item.end_seconds,
          name: motionLabel(item.type), detail: `${motionLabel(item.type)}${item.confidence == null ? '' : ` · confidence ${Math.round(item.confidence * 100)}%`}` })),
      ...(context?.citations ?? []).filter(item => validSeconds(item.citation.timestamp_seconds))
        .map((item, index) => ({ id: `signal-${index}`, lane: 'signal' as const, start: item.citation.timestamp_seconds,
          end: item.citation.timestamp_seconds, name: item.signal, detail: item.citation.excerpt,
          evidenceRef: item.citation.evidence_ref })),
    ];
    return items.sort((a, b) => a.start - b.start || a.id.localeCompare(b.id));
  }, [analysis, context]);
  useEffect(() => {
    if (!analysis || initialFocus.current) return;
    initialFocus.current = true;
    const citation = context?.citation;
    const match = citation && moments.find(item => item.lane === 'signal' && item.evidenceRef === citation.evidence_ref && item.start === citation.timestamp_seconds);
    if (match) { setSelected(match.id); setClock(match.start); setPinned(true); }
  }, [analysis, context, moments]);
  const active = selected ? moments.find(item => item.id === selected) : null;
  const at = active?.start ?? clock;
  const scene = moments.find(item => item.lane === 'scene' && item.start <= at && at < item.end);
  const aligned = moments.filter(item => item.lane !== 'scene' && (item.lane === 'signal'
    ? Math.abs(item.start - at) < 0.12 : item.start <= at && at <= item.end));
  const current = active ?? aligned[0] ?? scene;
  const duration = analysis?.duration_seconds && analysis.duration_seconds > 0 ? analysis.duration_seconds : null;
  const opening = moments.filter(item => item.start < 3 && item.lane !== 'signal').slice(0, 8);
  const isMobile = () => window.matchMedia('(max-width: 700px)').matches;
  function seekTo(source: HTMLVideoElement, seconds: number) {
    const duration = source.duration;
    const target = Number.isFinite(duration) ? Math.min(seconds, Math.max(0, duration - 0.05)) : seconds;
    requestedFrame.current = target;
    source.currentTime = target;
    // Seeking to the current decoded frame may not dispatch another seeked event.
    if (!source.seeking) capture(source);
  }
  function choose(item: Moment) {
    requestedFrame.current = null;
    setSelected(item.id); setClock(item.start); setPinned(false); setFrame(null);
    if (video.current && mediaReady && !mediaFailed) seekTo(video.current, item.start);
    if (isMobile()) setSheet(true);
  }
  function capture(source: HTMLVideoElement) {
    const requested = requestedFrame.current;
    if (requested === null || source.seeking || source.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
        !source.videoWidth || !source.videoHeight || Math.abs(source.currentTime - requested) > 0.075) return;
    try {
      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 480 / Math.max(source.videoWidth, source.videoHeight));
      canvas.width = Math.round(source.videoWidth * scale); canvas.height = Math.round(source.videoHeight * scale);
      const context = canvas.getContext('2d');
      if (!context) return;
      context.drawImage(source, 0, 0, canvas.width, canvas.height);
      if (requestedFrame.current === requested) { setFrame(canvas.toDataURL('image/jpeg', 0.7)); requestedFrame.current = null; }
    } catch { setFrame(null); }
  }
  const lanes = content ? ['scene', 'text', 'speech', 'motion'] as const : ['scene', 'text', 'speech', 'motion', 'signal'] as const;
  const performance = analysis?.performance ? Object.entries(analysis.performance).filter(([key, value]) => key in performanceLabels && Number.isFinite(value) && value >= 0) : [];
  return <section className="ca-page" aria-label={content ? 'Content Analysis' : 'Creative Analysis'}>
    <a href={content ? '#content' : '#intelligence'} className="ca-back"><ArrowLeft size={16} /> Back to {content ? 'Content' : 'Creative Intelligence'}</a>
    {error ? <p role="alert">{error}</p> : !analysis ? <p role="status">Loading stored creative evidence…</p> : <>
      <header className="ca-heading"><span>{content ? 'CONTENT ANALYSIS' : 'CREATIVE ANALYSIS'}</span><h1>{content ? analysis.item?.display_title : analysis.label === 'Analyzed creative' && context ? `Creative ${context.label}` : analysis.label}</h1>
        <p>{content && analysis.item ? `${platformLabel(analysis.item.platform)} · ${typeLabel(analysis.item.content_type)} · ` : ''}{duration ? `${stamp(duration)} total` : 'Duration unavailable'} · {analysis.resolution.width && analysis.resolution.height ? `${analysis.resolution.width} × ${analysis.resolution.height}` : 'Resolution unavailable'}{content && analysis.item ? ` · ${publicationDate(analysis.item.published_at)}` : ''}</p></header>
      {context ? <p className="ca-comparison">From comparison · {context.selectedSignal ?? `Creative ${context.label}`} · {metricLabel(context.metric)} · {context.group} numeric group{context.citation ? ` · ${stamp(context.citation.timestamp_seconds)}` : ''}</p>
        : !content && <p className="ca-no-context">Comparison focus unavailable; showing stored creative evidence from the start.</p>}
      <div className="ca-main-grid"><div className="ca-main-column">
        <div className="ca-player">
          {mediaReady && !mediaFailed && companyId ? <video ref={video} controls preload="metadata" playsInline
            src={`/api/companies/${companyId}/${content ? 'content' : 'creatives'}/${identity}/media`}
            onTimeUpdate={event => { const time = event.currentTarget.currentTime; setClock(time); if (!pinned && !event.currentTarget.paused) setSelected(null); }}
            onSeeked={event => capture(event.currentTarget)} onLoadedData={event => capture(event.currentTarget)} onPlay={() => { if (!pinned) setSelected(null); }}
            onLoadedMetadata={event => { if (active || context?.citation) seekTo(event.currentTarget, active?.start ?? context!.citation!.timestamp_seconds); }}
            onError={() => setMediaFailed(true)} aria-label={`${content ? analysis.item?.display_title : analysis.label} video`} />
            : <div className="ca-media-unavailable"><Film size={38} aria-hidden="true" /><strong>{mediaChecking ? 'Preparing video…' : 'Video currently unavailable'}</strong><span>{mediaChecking ? 'Resolving current media access.' : 'Stored evidence remains available below.'}</span></div>}
          <span className="ca-player-time">{stamp(at)}</span>
        </div>
        {context && <div className="ca-performance"><span>{context.accountName} · {context.start} – {context.stop}</span><strong>Creative {context.label} · {metricLabel(context.metric)} {formatMetric(context.metricValue, context.metric, context.currency)}</strong></div>}
        {content && performance.length > 0 && <div className="ca-performance ca-performance-metrics" aria-label="Platform performance">{performance.map(([key, value]) => <div key={key}><span>{performanceLabels[key]}</span><strong>{value.toLocaleString()}</strong></div>)}</div>}
        <section className="ca-timeline" aria-label="Analysis timeline"><div className="ca-timeline-head"><h3>Analysis timeline</h3><span>{duration ? `${stamp(duration)} total` : 'Duration unavailable · timed event list'}</span></div>
          <div className="ca-lanes" role="group" aria-label={`${lanes.length} evidence lanes`}>{lanes.map(lane => <div className="ca-lane" key={lane}>
            <span className="ca-lane-label">{laneSymbols[lane]} {laneNames[lane]}</span>
            <div className={`ca-lane-track ${duration ? '' : 'is-unscaled'}`}>{duration && <span className="ca-playhead" style={{ left: `${Math.min(100, at / duration * 100)}%` }} />}
              {moments.filter(item => item.lane === lane).length ? moments.filter(item => item.lane === lane).map(item => <button key={item.id} type="button"
                className={`ca-event ca-${lane} ${selected === item.id || !selected && item.start <= clock && (lane === 'signal' ? Math.abs(clock - item.start) < .12 : clock < item.end) ? 'is-active' : ''}`}
                style={duration ? { left: `${Math.min(98, item.start / duration * 100)}%`, width: `${Math.max(2, Math.min(100 - item.start / duration * 100, (item.end - item.start) / duration * 100))}%` } : undefined}
                onClick={() => choose(item)} aria-label={`${laneNames[lane]} ${item.name} at ${stamp(item.start)}`} title={`${item.name} · ${stamp(item.start)}`}>{laneSymbols[lane]}<span className="ca-event-copy">{item.name}</span></button>)
                : <span className="ca-empty-lane">{lane === 'signal' ? 'No validated signals for this view' : `No ${laneNames[lane].toLowerCase()} evidence returned`}</span>}
            </div></div>)}</div><p className="ca-gap-note">Empty space means no event displayed. It does not establish absence.</p></section>
        <section className="ca-opening"><h3>Opening 0–3s</h3>{opening.length ? <ul>{opening.map(item => <li key={item.id}><button type="button" onClick={() => choose(item)}>{item.lane === 'text' ? 'Text appears' : item.lane === 'speech' ? 'Speech begins' : item.lane === 'motion' ? item.name : item.start === 0 ? 'Opening scene starts' : 'Scene change'} at {stamp(item.start)}{item.lane === 'text' ? ` · ${item.name}` : ''}</button></li>)}</ul> : <p>No timed opening evidence returned.</p>}</section>
        <section className="ca-disclosures"><details><summary>Full transcript · {analysis.transcript.length} segments</summary>{analysis.transcript.length ? analysis.transcript.map((item, index) => <button key={index} onClick={() => choose(moments.find(moment => moment.id === `speech-${index}`)!)}>{stamp(item.start_seconds)} {item.text}</button>) : <p>Transcript unavailable.</p>}</details>
          <details><summary>OCR text · {analysis.ocr.length} observations</summary>{analysis.ocr.length ? analysis.ocr.map((item, index) => <button key={index} onClick={() => choose(moments.find(moment => moment.id === `text-${index}`)!)}>{stamp(item.appearance_seconds)}–{stamp(item.disappearance_seconds)} {item.text}</button>) : <p>OCR unavailable.</p>}</details>
          <details><summary>Scene boundaries · {analysis.scenes.length} ranges</summary>{analysis.scenes.length ? analysis.scenes.map((item, index) => <button key={index} onClick={() => choose(moments.find(moment => moment.id === `scene-${index}`)!)}>Scene {item.scene_number}: {stamp(item.start_seconds)}–{stamp(item.end_seconds)}</button>) : <p>Scene evidence incomplete or unavailable.</p>}</details>
          <details><summary>Motion events · {analysis.motion?.length ?? 0} observations</summary>{analysis.motion?.length ? analysis.motion.map((item, index) => <button key={index} onClick={() => choose(moments.find(moment => moment.id === `motion-${index}`)!)}>{stamp(item.start_seconds)}–{stamp(item.end_seconds)} {motionLabel(item.type)}{item.confidence == null ? '' : ` · ${Math.round(item.confidence * 100)}% confidence`}</button>) : <p>Motion evidence unavailable.</p>}</details>
        </section>
      </div><aside className="ca-rail" aria-label="Current Moment"><div className="ca-rail-inner"><span className="ca-eyebrow">CURRENT MOMENT</span><strong className="ca-timestamp">{stamp(at)}</strong>
        <h3>{current?.name ?? 'Opening evidence'}</h3><p>{current ? `${laneNames[current.lane]} · ${stamp(current.start)}` : 'Select an event or play the video to inspect timed evidence.'}</p>
        {frame && <figure><img src={frame} alt={`Captured authorized video frame at ${stamp(at)}`} /><figcaption>Video frame · {stamp(at)}</figcaption></figure>}
        {current && !frame && mediaReady && !mediaFailed && <p className="ca-frame-hint">Visual moment shown in the player at this timestamp.</p>}
        {aligned.filter(item => item.lane === 'text' || item.lane === 'speech' || item.lane === 'motion').map(item => <div className="ca-evidence-line" key={item.id}><b>{laneNames[item.lane]}</b><p>{item.detail}</p></div>)}
        {current?.lane === 'signal' && <div className="ca-evidence-line"><b>COMPARISON SIGNAL</b><p>{current.detail ?? current.name}</p><small>{current.evidenceRef}</small></div>}
        {scene && <p className="ca-secondary">Within {scene.name} · {stamp(scene.start)}–{stamp(scene.end)}</p>}
        {selected && <button className="ca-pin" type="button" onClick={() => setPinned(value => !value)} aria-pressed={pinned}><Pin size={14} /> {pinned ? 'Unpin and follow playback' : 'Pin this moment'}</button>}
      </div></aside></div>
      {sheet && <div className="ca-mobile-sheet" role="dialog" aria-label="Focused evidence"><button type="button" onClick={() => setSheet(false)} aria-label="Close focused evidence"><X size={18} /></button><strong>{stamp(at)} · {current?.name}</strong>{frame && <img src={frame} alt={`Video frame at ${stamp(at)}`} />}{aligned.map(item => <p key={item.id}><b>{laneNames[item.lane]}</b> {item.detail ?? item.name}</p>)}</div>}
    </>}
  </section>;
}
