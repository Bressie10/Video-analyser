import { useEffect, useRef, useState } from 'react';
import { ArrowRight, ChevronDown, Film } from 'lucide-react';
import { EvidenceTrace } from './EvidenceTrace';
import { openCreative } from '../creativeAnalysis/handoff';
import { type Cited, type Citation, type Difference, type Hypothesis, type IntelligenceResult, type Member, type Metric, type Preview,
  citations, formatMetric, formatPercentile, formatRatio, metricLabel, timeLabel } from './intelligenceModel';

function reasonText(result: IntelligenceResult) {
  const reasons = result.abstentions;
  if (reasons.includes('source_media_unavailable')) return 'Source video could not be accessed for this comparison. Performance remains available.';
  if (reasons.includes('insufficient_source_video_coverage')) return 'There isn’t enough analyzed video evidence yet to compare creative differences.';
  if (reasons.includes('content_model_or_validation_failed') || reasons.includes('malformed_stored_evidence')) return 'Creative evidence could not be completed for this comparison. Performance remains available.';
  if (reasons.includes('no_actionable_content_differences')) return 'No validated creative difference was returned for these six ads.';
  return 'There isn’t enough analyzed video evidence yet to compare creative differences.';
}

function PerformanceStrip({ result, metric }: { result: IntelligenceResult; metric: Metric }) {
  const facts = result.performance?.metric_facts;
  if (!facts) return null;
  const groups = result.cohort.content_groups;
  const all = groups ? [...groups.higher, ...groups.lower] : [];
  const range = [...all.map(item => Number(item.metric_value)), Number(facts.median), Number(facts.target_value)];
  const min = Math.min(...range), max = Math.max(...range);
  const place = (value: number) => `${max === min ? 50 : 8 + (value - min) / (max - min) * 84}%`;
  return <section className="ci-performance" aria-labelledby="ci-performance-title">
    <div className="ci-performance-facts">
      <div><span id="ci-performance-title">{metricLabel(metric)} · reference</span><strong title={facts.target_value}>{formatMetric(facts.target_value, metric, result.cohort.currency)}</strong></div>
      <div><span>Peer median</span><strong title={facts.median}>{formatMetric(facts.median, metric, result.cohort.currency)}</strong></div>
      {facts.ratio !== null && <div><span>Vs median</span><strong>{formatRatio(facts.ratio)}</strong></div>}
      <div><span>Percentile</span><strong title={formatPercentile(facts.percentile)}>{formatPercentile(facts.percentile).replace(' percentile', '')}</strong></div>
      <div><span>Peers</span><strong>n={result.cohort.peer_count}</strong></div>
    </div>
    {all.length === 6 && <div className="ci-distribution" aria-label="Six selected creatives on the metric scale">
      <span className="ci-distribution-label">Six selected creatives · {metricLabel(metric)}</span>
      <div className="ci-distribution-track"><span className="ci-distribution-median" style={{ left: place(Number(facts.median)) }} title={`Peer median ${formatMetric(facts.median, metric, result.cohort.currency)}`} />
        {all.map((member, index) => <span key={member.video_ref} className={`ci-distribution-dot ${index < 3 ? 'is-higher' : 'is-lower'} ${member.percentile !== null ? 'is-reference' : ''}`}
          style={{ left: place(Number(member.metric_value)) }} title={`Creative ${'ABCDEF'[index]}: ${formatMetric(member.metric_value, metric, result.cohort.currency)}`}>
          <span>{'ABCDEF'[index]}</span></span>)}
      </div><div className="ci-distribution-foot"><span>Selected metric values</span><span>Line = peer median</span></div>
    </div>}
  </section>;
}

function CreativeTile({ member, label, group, metric, currency, preview, relation, active, onSelect, onOpen }: {
  member: Member; label: string; group: 'higher' | 'lower'; metric: Metric; currency?: string; preview?: Preview;
  relation: 'support' | 'counterexample' | 'dim' | null; active: boolean; onSelect(): void; onOpen(): void;
}) {
  return <div className={`ci-creative ${group} ${relation ?? ''} ${active ? 'is-active' : ''}`}>
    <button type="button" className="ci-creative-open" onClick={onOpen} disabled={!member.creative_ref}
      aria-label={`Open Creative ${label} analysis`}><span className="ci-creative-media">{preview ? <img src={`data:image/jpeg;base64,${preview.jpeg_base64}`} alt={`Sampled frame from Creative ${label}`} />
      : <span className="ci-creative-fallback"><Film size={22} aria-hidden="true" /><span>Frame unavailable</span></span>}
      <span className="ci-frame-corners" aria-hidden="true" />
      {relation === 'support' && <span className="ci-creative-marker">● Cited</span>}
      {relation === 'counterexample' && <span className="ci-creative-marker">◆ Counterexample</span>}
    </span></button><span className="ci-creative-footer"><b>{label}</b><span title={member.metric_value}>{formatMetric(member.metric_value, metric, currency)}</span></span>
    <button type="button" className="ci-creative-focus" onClick={onSelect} aria-pressed={active}>Focus in Signal Map</button>
    {member.percentile !== null && <span className="ci-reference">Reference ad</span>}
  </div>;
}

function CreativeCohort({ result, metric, selected, selectedCreative, onCreative, onOpen }: {
  result: IntelligenceResult; metric: Metric; selected: Difference | null; selectedCreative: string | null; onCreative(ref: string): void; onOpen(member: Member, label: string, group: 'higher' | 'lower'): void;
}) {
  const groups = result.cohort.content_groups;
  if (!groups) return null;
  const preview = new Map(result.creative_previews.map(item => [item.video_ref, item]));
  const support = selected ? new Set(selected.supporting_video_refs) : null;
  const counter = selected ? new Set(selected.counterexamples.map(item => item.video_ref)) : null;
  const render = (members: Member[], group: 'higher' | 'lower', offset: number) =>
    <div className={`ci-creative-group ${group}`}><div className="ci-group-heading"><strong>{group === 'higher' ? 'Higher' : 'Lower'} {metricLabel(metric)}</strong><span>3 creatives</span></div>
      <div className="ci-creative-list">{members.map((member, index) => {
        const relation = counter?.has(member.video_ref) ? 'counterexample' : support?.has(member.video_ref) ? 'support' : selected ? 'dim' : null;
        return <CreativeTile key={member.video_ref} member={member} label={'ABCDEF'[offset + index]} group={group} metric={metric}
          currency={result.cohort.currency} preview={preview.get(member.video_ref)} relation={relation}
          active={selectedCreative === member.video_ref} onSelect={() => onCreative(member.video_ref)} onOpen={() => onOpen(member, 'ABCDEF'[offset + index], group)} />;
      })}</div></div>;
  return <section className="ci-creatives" aria-labelledby="ci-creatives-title"><header className="ci-section-heading"><h2 id="ci-creatives-title">Compared creatives</h2><span>A–F connect performance, signals and evidence</span></header>
    <div className="ci-creative-groups">{render(groups.higher, 'higher', 0)}{render(groups.lower, 'lower', 3)}</div></section>;
}

function citationForVideo(difference: Difference, videoRef: string): Cited | undefined {
  return citations(difference).filter(item => item.citation.video_ref === videoRef)
    .sort((a, b) => a.citation.timestamp_seconds - b.citation.timestamp_seconds)[0];
}
function SignalCell({ difference, member, label, maxTime, onInspect }: { difference: Difference; member: Member; label: string;
  maxTime: number; onInspect(ref: string, trigger: HTMLButtonElement): void;
}) {
  const entry = citationForVideo(difference, member.video_ref);
  if (!entry) return <span className="ci-signal-cell unknown" title="No validated citation; absence is not established">?</span>;
  const sameVideo = citations(difference).filter(item => item.citation.video_ref === member.video_ref).length;
  const position = `${Math.min(92, Math.max(5, entry.citation.timestamp_seconds / maxTime * 90))}%`;
  return <button type="button" className={`ci-signal-cell ${entry.role}`} onClick={event => onInspect(entry.citation.evidence_ref, event.currentTarget)}
    aria-label={`Creative ${label}, ${entry.role}, cited at ${timeLabel(entry.citation.timestamp_seconds)}. Inspect evidence.`}>
    <span className="ci-cell-value">{entry.role === 'counterexample' ? '◆' : '●'} {timeLabel(entry.citation.timestamp_seconds)}{sameVideo > 1 ? ` +${sameVideo - 1}` : ''}</span>
    <span className="ci-cell-rail"><span style={{ left: position }} /></span></button>;
}

function SignalMap({ result, metric, selectedIndex, selectedCreative, onSelect, onInspect }: {
  result: IntelligenceResult; metric: Metric; selectedIndex: number | null; selectedCreative: string | null;
  onSelect(index: number): void; onInspect(index: number, ref: string | null, trigger: HTMLButtonElement): void;
}) {
  const groups = result.cohort.content_groups;
  if (!groups || !result.content_differences.length) return null;
  const members = [...groups.higher, ...groups.lower];
  const maxTime = Math.max(1, ...result.content_differences.flatMap(row => citations(row).map(item => item.citation.timestamp_seconds)));
  return <section className="ci-map" id="ci-signal-map" aria-labelledby="ci-map-title">
    <header className="ci-section-heading"><h2 id="ci-map-title">Creative Signal Map</h2><span className="ci-map-key">● cited&nbsp;&nbsp; ◆ counterexample&nbsp;&nbsp; ? no validated citation</span></header>
    <div className="ci-map-frame"><div className="ci-map-head"><span>Validated observation<br /><small>Seconds from start · latest citation {timeLabel(maxTime)}</small></span>
      <span className="ci-map-high">Higher {metricLabel(metric)}</span><span className="ci-map-low">Lower {metricLabel(metric)}</span>
      {members.map((member, index) => <span className={`ci-map-creative-label ${index < 3 ? 'higher' : 'lower'} ${selectedCreative === member.video_ref ? 'is-active' : ''}`} key={member.video_ref}>
        <b>{'ABCDEF'[index]}</b><small>{formatMetric(member.metric_value, metric, result.cohort.currency)}</small></span>)}</div>
      {result.content_differences.map((difference, index) => <div key={`${difference.description}:${index}`} className={`ci-map-row ${selectedIndex === index ? 'is-selected' : ''} ${selectedIndex !== null && selectedIndex !== index ? 'is-muted' : ''} ${selectedCreative && selectedIndex === null ? citationForVideo(difference, selectedCreative) ? 'is-creative-match' : 'is-creative-muted' : ''}`}>
        <button className="ci-signal-name" type="button" aria-pressed={selectedIndex === index} onClick={() => onSelect(index)}>
          <span className="ci-signal-index">{String(index + 1).padStart(2, '0')}</span><span className="ci-signal-copy"><strong>{difference.description}</strong>
            <small>{difference.higher_group_support}/{difference.higher_group_size} higher · {difference.lower_group_support}/{difference.lower_group_size} lower · {difference.evidence_type}</small></span></button>
        {members.map((member, itemIndex) => <SignalCell key={member.video_ref} difference={difference} member={member} label={'ABCDEF'[itemIndex]}
          maxTime={maxTime} onInspect={(ref, trigger) => onInspect(index, ref, trigger)} />)}
        <button type="button" className="ci-inspect" onClick={event => onInspect(index, null, event.currentTarget)}>Inspect <ArrowRight size={14} aria-hidden="true" /></button>
        {selectedIndex === index && <div className="ci-mobile-signal-lanes">{members.map((member, itemIndex) => {
          const entry = citationForVideo(difference, member.video_ref);
          return <div key={member.video_ref} className={`ci-mobile-signal-lane ${itemIndex < 3 ? 'higher' : 'lower'}`}><b>{'ABCDEF'[itemIndex]}</b>
            <span className="ci-mobile-lane-rail">{entry && <i className={entry.role} style={{ left: `${Math.min(92, Math.max(5, entry.citation.timestamp_seconds / maxTime * 90))}%` }} />}</span>
            {entry ? <button type="button" onClick={event => onInspect(index, entry.citation.evidence_ref, event.currentTarget)}>{entry.role === 'counterexample' ? '◆ ' : '● '}{timeLabel(entry.citation.timestamp_seconds)}</button>
              : <span title="No validated citation; absence is not established">?</span>}</div>;
        })}</div>}
      </div>)}</div>
    <p className="ci-method-note">Observed patterns are associations within this comparison, not proven causes. A question mark does not establish absence.</p>
  </section>;
}

function Experiment({ item, index, sourceIndex, onSource }: { item: Hypothesis; index: number; sourceIndex: number; onSource(index: number): void }) {
  return <article className="ci-experiment"><div className="ci-experiment-head"><span>{String(index + 1).padStart(2, '0')}</span><h3>{item.hypothesis}</h3>
    {sourceIndex >= 0 && <button type="button" onClick={() => onSource(sourceIndex)}>Source signal {String(sourceIndex + 1).padStart(2, '0')} ↑</button>}</div>
    <div className="ci-ab"><div><span>A · CONTROL</span><p>{item.control_condition}</p></div><ArrowRight size={18} aria-hidden="true" /><div><span>B · VARIANT</span><p>{item.variant_condition}</p></div></div>
    <div className="ci-experiment-foot"><span><b>Change</b> {item.variable_to_test}</span><span><b>Measure</b> {metricLabel(item.primary_metric)}</span>
      {item.what_to_hold_constant.length > 0 && <span><b>Keep constant</b> {item.what_to_hold_constant.join(' · ')}</span>}</div>
    {(item.counterevidence.length > 0 || item.limitations.length > 0) && <details><summary>Why this test and its limits</summary><p>Source observation: {item.source_difference}</p>
      {item.counterevidence.length > 0 && <p>{item.counterevidence.length} counterevidence {item.counterevidence.length === 1 ? 'citation' : 'citations'} available in the source signal.</p>}
      {item.limitations.map((text, itemIndex) => <p key={itemIndex}>{text}</p>)}</details>}
  </article>;
}

export function IntelligenceResultView({ result, metric, accountName }: { result: IntelligenceResult; metric: Metric; accountName: string }) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [selectedCreative, setSelectedCreative] = useState<string | null>(null);
  const [inspector, setInspector] = useState<{ index: number; ref: string | null } | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLButtonElement | null>(null);
  const differences = result.content_differences;
  const activeDifference = inspector ? differences[inspector.index] ?? null : null;
  const entries = activeDifference ? citations(activeDifference) : [];
  const groups = result.cohort.content_groups;
  const labels = new Map(groups ? [...groups.higher, ...groups.lower].map((member, index) => [member.video_ref, 'ABCDEF'[index]]) : []);
  const openMember = (member: Member, label: string, group: 'higher' | 'lower', chosen?: Citation, signal?: string) => {
    if (!member.creative_ref) return;
    const related = differences.flatMap(diff => citations(diff)
      .filter(item => item.citation.video_ref === member.video_ref).map(item => ({ signal: diff.description, citation: item.citation })));
    const selectedSignal = signal ?? (selectedIndex === null ? undefined : differences[selectedIndex]?.description);
    const citation = chosen ?? (selectedSignal ? related.find(item => item.signal === selectedSignal)?.citation : undefined);
    dialog.current?.close(); setInspector(null);
    openCreative({ creativeRef: member.creative_ref, videoRef: member.video_ref, label, group, metric,
      metricValue: member.metric_value, currency: result.cohort.currency, start: result.cohort.date_start,
      stop: result.cohort.date_stop, accountName, selectedSignal, citation, citations: related, scrollY: window.scrollY });
  };
  useEffect(() => {
    if (inspector && !dialog.current?.open) dialog.current?.showModal();
    if (!inspector && dialog.current?.open) { dialog.current.close(); returnFocus.current?.focus(); }
  }, [inspector]);
  const inspect = (index: number, ref: string | null, trigger: HTMLButtonElement) => {
    setSelectedIndex(index); returnFocus.current = trigger; setInspector({ index, ref });
  };
  const source = (index: number) => { setSelectedIndex(index); document.getElementById('ci-signal-map')?.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }); };
  const noCohort = result.abstentions.some(item => ['insufficient_historical_cohort', 'insufficient_or_mixed_report_context', 'content_group_unavailable'].includes(item));
  return <div className="ci-result" aria-label="Creative Intelligence result">
    <div className="ci-context"><span>{accountName}</span><span>{metricLabel(metric)}</span><span>{result.cohort.date_start} – {result.cohort.date_stop}</span>
      {groups && <span>6 selected creatives</span>}</div>
    {result.performance ? <><PerformanceStrip result={result} metric={metric} />
      {groups && <CreativeCohort result={result} metric={metric} selected={selectedIndex !== null ? differences[selectedIndex] ?? null : null}
        selectedCreative={selectedCreative} onCreative={ref => setSelectedCreative(current => current === ref ? null : ref)}
        onOpen={openMember} />}
      {differences.length > 0 ? <><SignalMap result={result} metric={metric} selectedIndex={selectedIndex} selectedCreative={selectedCreative}
        onSelect={index => setSelectedIndex(current => current === index ? null : index)} onInspect={inspect} />
        {result.hypotheses.length > 0 ? <section className="ci-experiments" aria-labelledby="ci-experiments-title"><header className="ci-section-heading"><h2 id="ci-experiments-title">Experiments to try</h2><span>Controlled tests from validated observations</span></header>
          {result.hypotheses.map((item, index) => <Experiment key={`${item.source_difference}:${index}`} item={item} index={index}
            sourceIndex={differences.findIndex(diff => diff.description === item.source_difference)} onSource={source} />)}</section>
          : <p className="ci-partial">No experiment was returned for these observations.</p>}</>
        : <section className="ci-partial" aria-labelledby="ci-partial-title"><h2 id="ci-partial-title">Creative comparison unavailable</h2><p>{reasonText(result)}</p></section>}
      <details className="ci-methodology"><summary>How this works and limitations <ChevronDown size={14} aria-hidden="true" /></summary>
        <p>ContentMetric compares eligible ads in the exact selected reporting context, then cites validated video evidence. Patterns are associations, not proven causes. Uncited signals do not establish absence.</p>
        {result.abstentions.includes('source_media_unavailable') && <p>Some source videos could not be accessed.</p>}
        {result.abstentions.includes('insufficient_source_video_coverage') && <p>Some video analysis or sampled media was unavailable.</p>}
        {result.abstentions.includes('hypothesis_model_or_validation_failed') && <p>Validated differences remain visible, but experiments could not be completed.</p>}
      </details></> : <section className="ci-partial" aria-labelledby="ci-partial-title"><h2 id="ci-partial-title">No comparison available yet</h2>
      {result.abstentions.includes('meta_disconnected') ? <p>Meta is disconnected. Reconnect it in <a href="#settings">Integrations</a>, then run the comparison again.</p>
        : noCohort ? <p>More comparable ads are needed for this exact metric, reporting context and date window.</p>
          : <p>Comparable performance observations are unavailable for this exact reporting context.</p>}
      {!result.abstentions.includes('meta_disconnected') && <a href="#intelligence-start">Change reporting dates</a>}
    </section>}
    <EvidenceTrace difference={activeDifference} entries={entries} activeRef={inspector?.ref ?? null} previews={result.creative_previews}
      onChoose={ref => setInspector(current => current ? { ...current, ref } : null)} onClose={() => setInspector(null)} dialogRef={dialog} labels={labels}
      onOpenCreative={citation => { const members = groups ? [...groups.higher, ...groups.lower] : []; const index = members.findIndex(member => member.video_ref === citation.video_ref);
        if (index >= 0) openMember(members[index], 'ABCDEF'[index], index < 3 ? 'higher' : 'lower', citation, activeDifference?.description); }} />
  </div>;
}
