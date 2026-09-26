import { useEffect, useRef, useState } from "react";
import { errorMessage, generateIdea, readLibrary, ServiceError, sourceKey, syncLibrary, type Idea, type Library, type Source, type Video } from "./metaLibrary";

const labels = { instagram_reel: "Instagram Reel", facebook_reel: "Facebook Reel", facebook_video: "Facebook video", meta_video_ad: "Meta video ad" };
const states = { ready: "Ready", new: "New", analyzing: "Analyzing", unavailable: "Unavailable", failed: "Failed" };
const selectable = (video: Video) => video.status !== "unavailable" && video.status !== "failed";
const unique = (items: Video[]) => [...new Map(items.map((item) => [item.id, item])).values()];

function Thumbnail({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const safe = url && /^https:\/\//i.test(url);
  return <div className="thumbnail" aria-hidden="true">{safe && !failed
    ? <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    : <span className="thumbnail-placeholder">▶<small>Video preview</small></span>}</div>;
}

export function VideoLibrary({ sources, connected, onDisconnected, onIdea, onBusy }: {
  sources: Source[]; connected: boolean; onDisconnected: () => void; onIdea: (idea: Idea) => void; onBusy: (busy: boolean) => void;
}) {
  const [library, setLibrary] = useState<Library | null>(null);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [generationError, setGenerationError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const pages = useRef(1);
  const controller = useRef<AbortController | null>(null);
  const generationController = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestVersion = useRef(0);

  function fail(error: unknown) {
    setError(errorMessage(error));
    if (error instanceof ServiceError && error.status === 401) onDisconnected();
  }
  function commit(data: Library) {
    setLibrary(data);
    const usable = new Set(data.items.filter(selectable).map((item) => item.id));
    setSelection((previous) => new Set([...previous].filter((id) => usable.has(id))));
  }
  function schedule(data: Library, signal: AbortSignal) {
    if (timer.current) clearTimeout(timer.current);
    if (!signal.aborted && (data.sync_state === "syncing" || data.summary.new + data.summary.analyzing > 0)) {
      timer.current = setTimeout(() => { void refresh(false); }, 5000);
    }
  }
  async function refresh(startSync: boolean, more = false) {
    if (!connected) return;
    controller.current?.abort();
    if (timer.current) clearTimeout(timer.current);
    const active = new AbortController(); controller.current = active;
    const version = ++requestVersion.current;
    const valid = () => !active.signal.aborted && version === requestVersion.current;
    setLoading(true); setSyncing(false); setError("");
    try {
      // Re-read the loaded window so status changes update every visible card.
      let cursor: string | null = null;
      let data: Library | null = null;
      const items: Video[] = [];
      const seen = new Set<string>();
      const target = pages.current + (more ? 1 : 0);
      let loaded = 0;
      for (let page = 0; page < target; page++) {
        data = await readLibrary(sources, cursor, active.signal);
        if (!valid()) return;
        items.push(...data.items); loaded++;
        cursor = data.next_cursor;
        if (!cursor) break;
        if (seen.has(cursor)) throw new Error("Repeated cursor");
        seen.add(cursor);
      }
      if (!data || !valid()) return;
      pages.current = loaded;
      data = { ...data, items: unique(items) };
      commit(data); setLoading(false);
      if (startSync) {
        setSyncing(true);
        await syncLibrary(sources, active.signal);
        if (!valid()) return;
        data = { ...data, sync_state: "syncing" }; commit(data);
      }
      schedule(data, active.signal);
    } catch (caught) {
      if (valid()) fail(caught);
    } finally { if (valid()) { setLoading(false); setSyncing(false); } }
  }
  useEffect(() => {
    // Debounce source changes and avoid duplicate syncs in React StrictMode.
    const start = setTimeout(() => { void refresh(true); }, 300);
    return () => {
      clearTimeout(start); if (timer.current) clearTimeout(timer.current);
      controller.current?.abort(); generationController.current?.abort();
      setGenerating(false); onBusy(false);
    };
    // This component is keyed by source scope; reconnect/retry revalidates saved content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, attempt]);

  const ready = library?.items.filter((item) => selection.has(item.id) && item.status === "ready") ?? [];
  const pending = (library?.items ?? []).filter((item) => selection.has(item.id) && ["new", "analyzing"].includes(item.status)).length;
  const canGenerate = connected && ready.length > 0 && !generating;
  async function generate() {
    if (!canGenerate) return;
    const active = new AbortController(); generationController.current = active;
    setGenerating(true); onBusy(true); setGenerationError("");
    try {
      const idea = await generateIdea(ready.map((item) => item.id), active.signal);
      if (!active.signal.aborted) onIdea(idea);
    } catch (caught) {
      if (!active.signal.aborted) {
        setGenerationError(errorMessage(caught, "generation"));
        if (caught instanceof ServiceError && caught.status === 401) onDisconnected();
      }
    } finally { if (!active.signal.aborted) { setGenerating(false); onBusy(false); } }
  }
  const refreshing = loading || syncing;
  const selectionBar = <div className="selection-bar">
      <div><strong role="status">{selection.size} selected</strong><div className="selection-actions">
        <button disabled={!connected || generating || !library?.items.some(selectable)} onClick={() => setSelection(new Set(library?.items.filter(selectable).map((item) => item.id)))}>Select all currently shown</button>
        <button disabled={!selection.size || generating} onClick={() => setSelection(new Set())}>Clear selection</button>
      </div></div>
      <button className="primary" disabled={!canGenerate} onClick={() => { void generate(); }}>{generating ? "Creating your idea…" : "Generate a new video idea"}</button>
      <p className="selection-hint" role="status">{generating ? "Creating one new concept and script from your selected ready videos…" : pending > 0
        ? `${pending} selected ${pending === 1 ? "video is" : "videos are"} still processing. ${ready.length ? `Your idea will use the ${ready.length} ready ${ready.length === 1 ? "video" : "videos"}.` : "You can generate an idea when a selected video is ready."}`
        : ready.length ? `Your idea will use ${ready.length} ready ${ready.length === 1 ? "video" : "videos"}.` : "Select ready videos to inspire your next idea."}</p>
    {generationError && <p role="alert" className="notice error">{generationError}</p>}
    </div>;
  return <section className="library" aria-labelledby="library-title">
    <div className="section-heading"><div><p className="eyebrow">Start with what you’ve shared</p><h2 id="library-title">Your video library</h2></div>
      <button disabled={!connected || refreshing || generating} onClick={() => { void refresh(true); }}>Sync content</button></div>
    {!connected && <p role="status">Reconnect Meta to update your library and generate ideas.</p>}
    {refreshing && <p role="status">{syncing ? "Syncing your content…" : "Loading your video library…"}</p>}
    {error && <div role="alert" className="notice error"><p>{error}</p><button disabled={!connected || refreshing || generating} onClick={() => setAttempt((value) => value + 1)}>Try library again</button></div>}
    {selectionBar}
    {library && <>
      <p className="library-summary" role="status">{library.summary.total} videos found · {library.summary.ready} ready{library.summary.new + library.summary.analyzing > 0 ? ` · ${library.summary.new + library.summary.analyzing} new videos processing` : ""}{library.sync_state === "syncing" ? " · Syncing content…" : ""}</p>
      {library.source_errors.map((failure, index) => <p key={`${sourceKey(failure.source)}-${index}`} className="notice" role="alert">
        {sources.find((source) => sourceKey(source) === sourceKey(failure.source))?.name ?? "One account"}: {failure.code === "permission_missing" ? "Reconnect Meta to share access to this account." : "Some content couldn’t be updated. Other videos are still available. Try syncing again."}
      </p>)}
      {!library.items.length && <div className="empty"><h3>{library.source_errors.length ? "Some content is unavailable" : library.summary.total > 0 ? "No suitable videos available" : "Your videos will appear here"}</h3><p>{library.source_errors.length ? "We couldn’t check all your selected accounts. Try syncing again or reconnect Meta to share access." : library.sync_state === "syncing" ? "We’re checking your accounts for video content." : "There are no suitable videos in these accounts yet. Try another account or sync again after sharing a video."}</p></div>}
      <div className="video-grid">
        {library.items.map((video) => {
          const chosen = selection.has(video.id);
          const date = video.published_at && !Number.isNaN(Date.parse(video.published_at)) ? new Date(video.published_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : null;
          return <article key={video.id} className={`video-card${chosen ? " selected" : ""}`}>
            <label className="card-choice">
              <Thumbnail url={video.thumbnail_url} />
              <input type="checkbox" aria-label={`Select ${video.title || labels[video.content_type]}`} checked={chosen} disabled={!connected || !selectable(video) || generating} onChange={(event) => {
                setSelection((previous) => { const next = new Set(previous); if (event.target.checked) next.add(video.id); else next.delete(video.id); return next; });
              }} />
              <div className="card-body"><div className="card-labels"><span>{labels[video.content_type]}</span><span className={`badge ${video.distribution}`}>{video.distribution === "paid" ? "Paid ad" : "Organic"}</span></div>
                <h3>{video.title || "Untitled video"}</h3>{date && <p className="muted"><time dateTime={video.published_at!}>{date}</time></p>}
                <span className={`status status-${video.status}`}>{states[video.status]}</span>
              </div>
            </label>
            <div className="card-footer">{video.metrics && Object.values(video.metrics).some((value) => value !== null)
              ? <dl className="metrics">{(["views", "likes", "comments", "shares"] as const).map((key) => video.metrics?.[key] != null && <div key={key}><dt>{key}</dt><dd>{video.metrics[key]!.toLocaleString()}</dd></div>)}</dl>
              : <p className="muted">Performance not available yet</p>}
              {video.status === "unavailable" && <p>This video can’t be used right now.</p>}
              {video.status === "failed" && <p>We couldn’t prepare this video. Try syncing again.</p>}
            </div>
          </article>;
        })}
      </div>
      {library.next_cursor && <button className="load-more" disabled={!connected || refreshing || generating} onClick={() => { void refresh(false, true); }}>Load more videos</button>}
    </>}
  </section>;
}
