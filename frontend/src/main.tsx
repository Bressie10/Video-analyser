import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { MetaConnection } from "./MetaConnection";
import { VideoLibrary } from "./VideoLibrary";
import type { Idea } from "./metaLibrary";
import "./style.css";

function App() {
  const [connected, setConnected] = useState(false);
  const [expired, setExpired] = useState(false);
  const [initialJobId, setInitialJobId] = useState<string | null>(null);
  const [hasConnected, setHasConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [idea, setIdea] = useState<Idea | null>(null);
  const ideaHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (idea) {
      ideaHeading.current?.focus({ preventScroll: true });
      ideaHeading.current?.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }, [idea]);
  const connectionChanged = useCallback((value: boolean) => {
    setConnected(value);
    if (value) { setHasConnected(true); setExpired(false); }
  }, []);
  const disconnected = useCallback(() => { setExpired(true); setConnected(false); }, []);
  return <main>
    <header className="page-heading"><p className="eyebrow">Your next video starts here</p><h1>Turn your content into your next idea.</h1><p>Choose videos from your business accounts. Get a fresh concept and a script you can make your own.</p></header>
    <MetaConnection onSyncStarted={setInitialJobId} disconnected={expired} disabled={busy} onConnectionChange={connectionChanged} />
    {expired && <p className="notice" role="alert">Your Meta connection has expired. Reconnect to continue. Your content and ideas are still here.</p>}
    {!hasConnected && !connected && <div className="welcome"><h2>Start with your business content</h2><p>Connect Meta to find your Facebook videos, Instagram Reels and video ads in one place.</p></div>}
    {hasConnected && <VideoLibrary connected={connected} initialJobId={initialJobId} onDisconnected={disconnected} onIdea={setIdea} onBusy={setBusy} />}
    {idea && <section className="idea-result" aria-labelledby="idea-title" aria-live="polite">
      <p className="eyebrow">Something new to share</p><h2 id="idea-title" ref={ideaHeading} tabIndex={-1}>New video idea</h2>
      <p className="muted">Based on {idea.usedCount} selected {idea.usedCount === 1 ? "video" : "videos"}.</p>
      {idea.concept && idea.script ? <><p className="concept">{idea.concept}</p><h3>Script</h3><p className="script">{idea.script}</p></>
        : <p className="script">{idea.response}</p>}
    </section>}
  </main>;
}
const root = document.getElementById("root");
if (!root) throw new Error("Application root element is missing.");
createRoot(root).render(<StrictMode><App /></StrictMode>);
