import { useEffect, useRef, useState } from "react";

type Status = "checking" | "disconnected" | "connecting" | "connected" | "error";

export function MetaConnection({ onConnectionChange, disconnected = false, disabled = false }: { onConnectionChange: (connected: boolean) => void; disconnected?: boolean; disabled?: boolean }) {
  const [status, setStatus] = useState<Status>("checking");
  const [error, setError] = useState("");
  const stopWatching = useRef<(() => void) | null>(null);

  useEffect(() => { onConnectionChange(status === "connected"); }, [status, onConnectionChange]);
  useEffect(() => { if (disconnected) setStatus("disconnected"); }, [disconnected]);

  async function checkConnection(signal: AbortSignal, afterLogin = false) {
    const response = await fetch("/api/meta/test", { credentials: "same-origin", cache: "no-store", signal });
    if (response.status === 401 && !afterLogin) return "disconnected" as const;
    const body = await response.json();
    if (!response.ok || body?.connected !== true) {
      throw new Error(typeof body?.detail === "string" ? body.detail : "Could not verify the Meta connection. Try again.");
    }
    return "connected" as const;
  }

  useEffect(() => {
    const controller = new AbortController();
    checkConnection(AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]))
      .then((result) => { if (!controller.signal.aborted) setStatus(result); })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError("Could not check the Meta connection. Try connecting again.");
          setStatus("error");
        }
      });
    return () => { controller.abort(); stopWatching.current?.(); };
  }, []);

  function connect() {
    setError("");
    const popup = window.open("/api/meta/connect", "meta-authorization", "popup,width=600,height=760");
    if (!popup) {
      setError("Allow popups for this site, then select Connect Meta again.");
      setStatus("error");
      return;
    }
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
        fail(typeof body?.detail === "string" ? body.detail : "Meta authentication failed. Try again.");
        return;
      }
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

  return <section aria-labelledby="meta-title">
    <h2 id="meta-title">Meta account</h2>
    <p role="status">{{
      checking: "Checking Meta connection…",
      disconnected: "Meta is not connected.",
      connecting: "Connecting to Meta… Complete authorization in the popup window.",
      connected: "Meta connected successfully.",
      error: "Meta connection could not be confirmed.",
    }[status]}</p>
    {error && <p role="alert" className="error">{error}</p>}
    <button type="button" onClick={connect} disabled={disabled || status === "checking" || status === "connecting"}>
      {status === "connecting" ? "Connecting…" : status === "connected" ? "Reconnect Meta" : "Connect Meta"}
    </button>
  </section>;
}
