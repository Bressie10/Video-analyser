import { useEffect, useRef, useState } from "react";
import { MetaBrowser } from "./MetaBrowser";
import { useMetaLibrary } from "./useMetaLibrary";
import { assetsOf, contentLabel, displayItems, displayStatus, errorMessage, generateIdea, isProcessing, isReady, isSelectable, needsPreparation, ownMetrics, RECOMMENDATION_LIMIT, ServiceError, sourcesFrom, type Asset, type Idea } from "./metaLibrary";

const states = { ready: "Ready", partial: "Partly ready", new: "New", analyzing: "Analyzing", unavailable: "Unavailable", failed: "Failed" };
export function VideoLibrary({ connected, initialJobId, onDisconnected, onIdea, onBusy }: {
  connected: boolean; initialJobId: string | null; onDisconnected: () => void; onIdea: (idea: Idea) => void; onBusy: (busy: boolean) => void;
}) {
  const library = useMetaLibrary(connected, initialJobId, onDisconnected);
  const [accounts, setAccounts] = useState<Set<string>>(new Set());
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState(25);
  const [generating, setGenerating] = useState(false);
  const [generationError, setGenerationError] = useState("");
  const [stale, setStale] = useState<Set<string>>(new Set());
  const touchedAccounts = useRef(false);
  const selectionEpoch = useRef(0);
  const preparationQueue = useRef<Promise<void>>(Promise.resolve());
  const generationController = useRef<AbortController | null>(null);
  const staleVersions = useRef(new Map<string, number | null>());
  const sources = sourcesFrom(library.items);
  const cards = displayItems(library.items);
  const filtered = cards.filter((item) => accounts.has(item.account_id));
  const visible = filtered.slice(0, shown);
  const selectedAssets = [...new Map(filtered.filter((item) => selection.has(item.id)).flatMap(assetsOf).map((asset) => [asset.id, asset])).values()];
  const ready = selectedAssets.filter((asset) => isReady(asset) && !stale.has(asset.id));
  const readyCount = new Set(ready.map((asset) => asset.id)).size;
  const waiting = selectedAssets.filter((asset) => needsPreparation(asset) || isProcessing(asset) || stale.has(asset.id)).length;
  const unusable = selectedAssets.length - ready.length - waiting;
  const activeJobs = library.jobs.some((job) => job.state === "running");
  const partialFailure = library.jobs.some((job) => job.state === "partial_failure");
  const canGenerate = connected && readyCount > 0 && readyCount <= RECOMMENDATION_LIMIT && !generating;

  useEffect(() => {
    if (!library.complete) return;
    const available = new Set(sources.map((source) => source.id));
    setAccounts((previous) => {
      if (touchedAccounts.current) return new Set([...previous].filter((id) => available.has(id)));
      return new Set(["facebook", "instagram", "meta_ads"].flatMap((platform) => {
        const group = sources.filter((source) => source.platform === platform);
        return group.length === 1 ? [group[0].id] : [];
      }));
    });
    const usable = new Set(cards.filter(isSelectable).map((item) => item.id));
    setSelection((previous) => new Set([...previous].filter((id) => usable.has(id))));
    // A 409 may indicate an old analysis version. Do not label that old copy Ready.
    const assets = library.items.flatMap((item) => [item, ...(item.assets ?? [])]);
    for (const asset of assets) {
      if (staleVersions.current.has(asset.id) && (!isReady(asset) || asset.analysis_version !== staleVersions.current.get(asset.id))) staleVersions.current.delete(asset.id);
    }
    setStale(new Set(staleVersions.current.keys()));
    // Account defaults and readiness change only after a completed library read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [library.revision]);
  useEffect(() => {
    if (!connected) { generationController.current?.abort(); setGenerating(false); onBusy(false); selectionEpoch.current++; }
    return () => generationController.current?.abort();
  }, [connected, onBusy]);

  function prepare(assets: Asset[]) {
    const epoch = selectionEpoch.current;
    preparationQueue.current = preparationQueue.current.then(async () => {
      if (epoch === selectionEpoch.current) await library.prepare(assets.filter(needsPreparation).map((asset) => asset.id), () => epoch === selectionEpoch.current);
    });
  }
  function changeSelection(next: Set<string>) {
    touchedAccounts.current = true;
    selectionEpoch.current++;
    setSelection(next);
    const targets = filtered.filter((item) => next.has(item.id)).flatMap(assetsOf);
    prepare(targets);
  }
  async function generate() {
    if (!canGenerate) return;
    const active = new AbortController(); generationController.current = active;
    setGenerating(true); onBusy(true); setGenerationError("");
    try {
      const idea = await generateIdea(ready, active.signal);
      if (!active.signal.aborted) onIdea(idea);
    } catch (caught) {
      if (active.signal.aborted) return;
      setGenerationError(errorMessage(caught, "generation"));
      if (caught instanceof ServiceError && caught.status === 401) onDisconnected();
      if (caught instanceof ServiceError && caught.status === 409) {
        const affected = ready.filter((asset) => caught.affectedIds.includes(asset.id) || caught.affectedIds.includes(asset.video_id!));
        affected.forEach((asset) => staleVersions.current.set(asset.id, asset.analysis_version));
        setStale(new Set(staleVersions.current.keys()));
        if (affected.length) await library.prepare(affected.map((asset) => asset.id));
        else await library.refresh();
      }
      if (caught instanceof ServiceError && caught.status === 404) await library.refresh();
    } finally { if (!active.signal.aborted) { setGenerating(false); onBusy(false); } }
  }
  const readyCards = filtered.filter((item) => assetsOf(item).some((asset) => isReady(asset) && !stale.has(asset.id))).length;
  const processingCards = filtered.filter((item) => assetsOf(item).some(isProcessing)).length;
  return <>
    <MetaBrowser sources={sources} selected={accounts} complete={library.complete} loading={library.loading} disabled={!connected || generating}
      onChange={(ids) => { touchedAccounts.current = true; setAccounts(ids); changeSelection(new Set()); setShown(25); setGenerationError(""); }} />
    <section className="library" aria-labelledby="library-title">
      <div className="section-heading"><div><p className="eyebrow">Start with what you’ve shared</p><h2 id="library-title">Your video library</h2></div>
        <button disabled={!connected || library.loading || generating} onClick={() => { void library.refresh(true); }}>Sync content</button></div>
      {!connected && <p role="status">Reconnect Meta to update your library and generate ideas.</p>}
      {library.loading && <p role="status">Loading your video library…</p>}
      {activeJobs && <p role="status">Syncing and preparing your content…</p>}
      {library.error && <div role="alert" className="notice error"><p>{library.error}</p><button disabled={!connected || library.loading || generating} onClick={() => { void library.refresh(true); }}>Try library again</button></div>}
      {partialFailure && <p role="alert" className="notice">Some content couldn’t be updated. Your available videos and previous ideas are still here.</p>}
      <div className="selection-bar">
        <div><strong role="status">{selection.size} selected</strong><div className="selection-actions">
          <button disabled={!connected || generating || !visible.some(isSelectable)} onClick={() => changeSelection(new Set([...selection, ...visible.filter(isSelectable).map((item) => item.id)]))}>Select all currently shown</button>
          <button disabled={!selection.size || generating} onClick={() => changeSelection(new Set())}>Clear selection</button>
        </div></div>
        <button className="primary" disabled={!canGenerate} onClick={() => { void generate(); }}>{generating ? "Creating your idea…" : "Generate a new video idea"}</button>
        <p className="selection-hint" role="status">{generating ? "Creating one new concept and script from your selected ready videos…"
          : readyCount > RECOMMENDATION_LIMIT ? `${readyCount} ready videos selected. Choose up to 20 ready videos for one idea. An ad can contain more than one video.`
          : readyCount ? `Your idea will use ${readyCount} ready ${readyCount === 1 ? "video" : "videos"}.` : "Select ready videos to inspire your next idea."}
          {waiting > 0 && ` ${waiting} selected ${waiting === 1 ? "video is" : "videos are"} being prepared or waiting to be prepared. Only ready videos will be used.`}
          {unusable > 0 && ` ${unusable} selected ${unusable === 1 ? "video is" : "videos are"} unavailable and won’t be used.`}
          {library.preparing && " Preparing your selection…"}</p>
        {generationError && <p role="alert" className="notice error">{generationError}</p>}
      </div>
      {(library.complete || library.items.length > 0) && <>
        <p className="library-summary" role="status">{filtered.length} videos and ads {library.complete ? "found" : "loaded"} · {readyCards} ready{processingCards > 0 ? ` · ${processingCards} processing` : ""}</p>
        {library.complete && !filtered.length && !library.error && <div className="empty"><h3>{cards.length ? "Choose your business accounts" : partialFailure ? "Some content is unavailable" : "Your videos will appear here"}</h3>
          <p>{cards.length ? "Choose accounts above to browse their videos." : activeJobs ? "We’re checking your accounts for video content." : partialFailure ? "We couldn’t check all your content. Try syncing again or reconnect Meta to share access." : "There are no suitable videos in your library yet. Sync again after sharing a video."}</p></div>}
        <div className="video-grid">{visible.map((video) => {
          const status = assetsOf(video).some((asset) => stale.has(asset.id)) ? "analyzing" : displayStatus(video);
          const date = video.published_at && !Number.isNaN(Date.parse(video.published_at)) ? new Date(video.published_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : null;
          const metrics = ownMetrics(video);
          const paid = video.content_type === "ad" || video.account_platform === "meta_ads";
          return <article key={video.id} className={`video-card${selection.has(video.id) ? " selected" : ""}`}>
            <label className="card-choice">
              <div className="thumbnail" aria-hidden="true"><span className="thumbnail-placeholder">▶<small>Video preview</small></span></div>
              <input type="checkbox" aria-label={`Select ${video.label || contentLabel(video)}`} checked={selection.has(video.id)} disabled={!connected || !isSelectable(video) || generating} onChange={(event) => {
                const next = new Set(selection); if (event.target.checked) next.add(video.id); else next.delete(video.id); changeSelection(next);
              }} />
              <div className="card-body"><div className="card-labels"><span>{contentLabel(video)}</span><span className={`badge ${paid ? "paid" : "organic"}`}>{paid ? "Paid ad" : "Organic"}</span></div>
                <h3>{video.label || "Untitled video"}</h3>{date && <p className="muted"><time dateTime={video.published_at!}>{date}</time></p>}
                <span className={`status status-${status}`}>{states[status]}</span>
              </div>
            </label>
            <div className="card-footer">{metrics.length ? <dl className="metrics">{metrics.map((metric) => <div key={metric.name}><dt>{metric.name}</dt><dd>{metric.value.toLocaleString()}</dd></div>)}</dl> : <p className="muted">Performance not available yet</p>}
              {status === "new" && <p>Select this video to prepare it for your next idea.</p>}
              {status === "partial" && <p>{assetsOf(video).filter(isReady).length} of {assetsOf(video).length} videos ready. Your idea will use the ready videos.</p>}
              {status === "unavailable" && <p>This content has no usable video right now.</p>}
              {status === "failed" && <p>We couldn’t prepare this video.</p>}
              {video.performance.some((entry) => entry.item_id === video.id && entry.attribution === "shared_ad") && <p>Performance describes the whole ad, not individual videos.</p>}
            </div>
          </article>;
        })}</div>
        {visible.length < filtered.length && <button className="load-more" disabled={generating} onClick={() => setShown((value) => value + 25)}>Load more videos</button>}
      </>}
    </section>
  </>;
}
