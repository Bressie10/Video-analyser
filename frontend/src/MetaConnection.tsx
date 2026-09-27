import { useEffect, useRef, useState, type RefObject } from "react";
import { friendlyError, isUUID } from "./metaLibrary";

import { Button } from "./ui/controls";
import { Badge } from "./ui/layout";
import "./settings.css";

type Status = "checking" | "disconnected" | "connecting" | "connected" | "error";

export function MetaConnection({ onConnectionChange, disconnected = false, disabled = false, onSyncStarted, connectAction }: { connectAction?: RefObject<() => void>; onSyncStarted: (id: string | null) => void; onConnectionChange: (connected: boolean) => void; disconnected?: boolean; disabled?: boolean }) {
  const [status, setStatus] = useState<Status>("checking");
  const [error, setError] = useState("");
  const stopWatching = useRef<(() => void) | null>(null);

  useEffect(() => { onConnectionChange(status === "connected"); }, [status, onConnectionChange]);
  useEffect(() => { if (disconnected) { setStatus("disconnected"); setError(""); } }, [disconnected]);

  async function checkConnection(signal: AbortSignal, afterLogin = false) {
    const response = await fetch("/api/meta/test", { credentials: "same-origin", cache: "no-store", signal });
    const body = await response.json();
    if (response.ok && body?.connected === false && !afterLogin) return "disconnected" as const;
    if (!response.ok || body?.connected !== true) {
      throw new Error(friendlyError(response.status, "accounts"));
    }
    return "connected" as const;
  }

  useEffect(() => {
    const controller = new AbortController();
    // Strict Mode replays effects in development. Cancel the first scheduled
    // probe before it reaches the network, while keeping real unmount cleanup.
    const timer = window.setTimeout(() => {
      checkConnection(AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]))
        .then((result) => { if (!controller.signal.aborted) setStatus(result); })
        .catch(() => {
          if (!controller.signal.aborted) {
            setError("Could not check the Meta connection. Try connecting again.");
            setStatus("error");
          }
        });
    }, 0);
    return () => { window.clearTimeout(timer); controller.abort(); stopWatching.current?.(); };
  }, []);

  function connect() {
    setError("");
    const popup = window.open("/api/meta/connect", "meta-authorization", "popup,width=600,height=760");
    if (!popup) {
      setError("Allow popups for this site, then select Connect Meta again.");
      setStatus("error");
      return;
    }
    onSyncStarted(null);
    setStatus("connecting");
    const started = Date.now();
    const controller = new AbortController();
    const stop = () => { window.clearInterval(timer); controller.abort(); popup.close(); };
    stopWatching.current = stop;
    const fail = (message: string) => { stop(); setError(message); setStatus("error"); };
    const timer = window.setInterval(() => {
      if (popup.closed) {
        fail("Meta authorization was not completed. Select Connect Meta to try again.");
        return;
      }
      if (Date.now() - started > 5 * 60 * 1000) {
        fail("Meta authorization timed out. Select Connect Meta to try again.");
        return;
      }
      let body;
      try {
        // The backend returns JSON at connect (errors) and callback (the OAuth result).
        // Meta's cross-origin authorization pages are intentionally unreadable here.
        if (popup.location.origin !== window.location.origin ||
            !["/api/meta/connect", "/api/meta/callback"].includes(popup.location.pathname) ||
            popup.document.readyState !== "complete") return;
        body = JSON.parse(popup.document.querySelector("pre")?.textContent ?? popup.document.body.innerText);
      } catch { return; }
      window.clearInterval(timer);
      popup.close();
      if (body?.connected !== true) {
        fail("We couldn’t connect Meta. Try again and allow access to your business accounts.");
        return;
      }
      onSyncStarted(isUUID(body.job_id) ? body.job_id : null);
      checkConnection(AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]), true)
        .then((result) => { if (!controller.signal.aborted) setStatus(result); })
        .catch((caught) => {
          if (!controller.signal.aborted) {
            setError(caught instanceof Error ? caught.message : "Could not verify the Meta connection.");
            setStatus("error");
          }
        });
    }, 400);
  }

  useEffect(() => { if (connectAction) connectAction.current = connect; });

  return <section className="settings-connection" aria-labelledby="settings-meta">
    <h2 id="settings-meta" tabIndex={-1}>Integrations</h2>
    <h3>Meta <Badge tone={status === "connected" ? "success" : status === "error" ? "warning" : "neutral"}>{status === "connected" ? "Connected" : status === "error" ? "Connection issue" : status === "disconnected" ? "Not connected" : status === "checking" ? "Checking" : "Connecting"}</Badge></h3>
    <p>Connect once, then choose Facebook Pages, Instagram accounts and Ads accounts for each company in Content ownership.</p>
    <p role="status">{{
      checking: "Checking Meta connection…",
      disconnected: "Meta is not connected.",
      connecting: "Connecting to Meta… Complete authorization in the popup window.",
      connected: "Meta connected successfully.",
      error: "Meta connection could not be confirmed.",
    }[status]}</p>
    {error && <p role="alert" className="error">{error}</p>}
    <Button variant={status === "connected" ? "secondary" : "primary"} type="button" onClick={connect} disabled={disabled || status === "checking" || status === "connecting"}>
      {status === "connecting" ? "Connecting…" : status === "connected" ? "Reconnect Meta" : "Connect Meta"}
    </Button>
  </section>;
}
