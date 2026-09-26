import { useEffect, useRef, useState } from "react";
import { errorMessage, isProcessing, prepareVideos, readJob, readLibrary, ServiceError, syncLibrary, type Job, type LibraryItem } from "./metaLibrary";

/** Owns the connected library, independently of the customer's local account filters. */
export function useMetaLibrary(connected: boolean, initialJobId: string | null, onDisconnected: () => void) {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [complete, setComplete] = useState(false);
  const [loading, setLoading] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [preparationError, setPreparationError] = useState("");
  const callbackJobUsed = useRef(false);
  const [preparing, setPreparing] = useState(false);
  const [revision, setRevision] = useState(0);
  const life = useRef<AbortController | null>(null);
  const itemsRef = useRef<LibraryItem[]>([]);
  const completeRef = useRef(false);
  const jobsRef = useRef(new Map<string, Job | null>());
  const submitted = useRef(new Set<string>());
  const running = useRef(false);
  const repeat = useRef(false);
  const pendingSync = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prepareCount = useRef(0);

  function publishJobs() { setJobs([...jobsRef.current.values()].filter((job): job is Job => job !== null)); }
  function handleError(caught: unknown) {
    setError(errorMessage(caught));
    if (caught instanceof ServiceError && caught.status === 401) onDisconnected();
  }
  async function refresh(sync = false) {
    const active = life.current;
    if (!active || active.signal.aborted || !connected) return;
    if (sync) pendingSync.current = true;
    if (running.current) { repeat.current = true; return; }
    running.current = true;
    if (timer.current) clearTimeout(timer.current);
    setLoading(true); setError("");
    const valid = () => life.current === active && !active.signal.aborted;
    try {
      if (pendingSync.current) {
        pendingSync.current = false;
        // Load cached content before asking for new work.
        const saved = await readLibrary(active.signal, completeRef.current ? undefined : (partial) => {
          if (valid()) { itemsRef.current = partial; setItems(partial); }
        });
        if (!valid()) return;
        itemsRef.current = saved; setItems(saved); completeRef.current = true; setComplete(true);
        const id = initialJobId && !callbackJobUsed.current ? initialJobId : await syncLibrary(active.signal);
        callbackJobUsed.current = true;
        if (!valid()) return;
        for (const [key, job] of jobsRef.current) if (job?.kind === "sync" && job.state !== "running") jobsRef.current.delete(key);
        jobsRef.current.set(id, null);
      }
      for (const [id, previous] of jobsRef.current) {
        if (previous && ["completed", "partial_failure"].includes(previous.state)) continue;
        const job = await readJob(id, active.signal);
        if (!valid()) return;
        jobsRef.current.set(id, job); publishJobs();
        if (job.state === "blocked") throw new ServiceError(401, "Your Meta connection has expired. Reconnect Meta to continue.");
      }
      const data = await readLibrary(active.signal, completeRef.current ? undefined : (partial) => {
        if (valid()) { itemsRef.current = partial; setItems(partial); }
      });
      if (!valid()) return;
      itemsRef.current = data; setItems(data); completeRef.current = true; setComplete(true);
      setRevision((value) => value + 1);
      for (const item of data.flatMap((item) => [item, ...(item.assets ?? [])])) {
        if (!["discovered", "deferred"].includes(item.analysis_state)) submitted.current.delete(item.id);
      }
    } catch (caught) { if (valid()) handleError(caught); }
    finally {
      if (valid()) {
        running.current = false; setLoading(false);
        const unfinished = [...jobsRef.current.values()].some((job) => !job || job.state === "running");
        const processing = itemsRef.current.some((item) => isProcessing(item) || item.assets?.some(isProcessing));
        if (repeat.current) { repeat.current = false; timer.current = setTimeout(() => { void refresh(); }, 0); }
        else if (unfinished || processing) timer.current = setTimeout(() => { void refresh(); }, 5000);
      }
    }
  }
  async function prepare(ids: string[], stillSelected: () => boolean = () => true) {
    const active = life.current;
    if (!active || active.signal.aborted || !connected) return;
    const targets = [...new Set(ids)].filter((id) => !submitted.current.has(id));
    if (!targets.length) return;
    targets.forEach((id) => submitted.current.add(id));
    prepareCount.current++; setPreparing(true); setPreparationError("");
    let accepted = 0;
    try {
      for (let offset = 0; offset < targets.length; offset += 100) {
        if (!stillSelected() || active.signal.aborted) break;
        const id = await prepareVideos(targets.slice(offset, offset + 100), active.signal);
        if (active.signal.aborted) return;
        accepted = Math.min(offset + 100, targets.length);
        jobsRef.current.set(id, null);
      }
      if (!active.signal.aborted) await refresh();
    } catch (caught) {
      if (!active.signal.aborted) {
        setPreparationError(errorMessage(caught));
        if (caught instanceof ServiceError && caught.status === 401) onDisconnected();
      }
    }
    finally {
      targets.slice(accepted).forEach((id) => submitted.current.delete(id));
      if (life.current === active && !active.signal.aborted) {
        prepareCount.current--; setPreparing(prepareCount.current > 0);
        // Even a partially accepted batch must continue to report progress.
        if (accepted) void refresh();
      }
    }
  }
  useEffect(() => {
    const active = new AbortController(); life.current = active;
    running.current = false; repeat.current = false; pendingSync.current = false;
    prepareCount.current = 0; setPreparing(false); setLoading(false);
    if (!connected) return () => active.abort();
    jobsRef.current.clear(); submitted.current.clear(); setJobs([]); callbackJobUsed.current = false;
    const start = setTimeout(() => { void refresh(true); }, 300);
    return () => {
      clearTimeout(start); if (timer.current) clearTimeout(timer.current);
      active.abort();
    };
    // One lifecycle per verified connection, never per filter or selection change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, initialJobId]);
  return { items, complete, loading, jobs, error: error || preparationError, preparing, revision, refresh, prepare };
}
