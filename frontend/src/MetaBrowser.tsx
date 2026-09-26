import { useEffect, useState } from "react";
import { discoverSources, errorMessage, ServiceError, sourceKey, type Source } from "./metaLibrary";

export function MetaBrowser({ connected, selected, onChange, onDisconnected, disabled }: {
  connected: boolean; selected: Source[]; onChange: (sources: Source[]) => void; onDisconnected: () => void; disabled: boolean;
}) {
  const [sources, setSources] = useState<Source[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!connected) return;
    const controller = new AbortController();
    setLoading(true); setErrors([]);
    discoverSources(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setSources(result.sources); setErrors(result.errors);
      // Revalidate access on every reconnect. Never keep an inaccessible source selected.
      const retained = selected.filter((source) => result.sources.some((current) => sourceKey(current) === sourceKey(source)));
      const defaults = ["facebook", "instagram", "meta_ads"].flatMap((platform) => {
        const group = result.sources.filter((source) => source.platform === platform);
        return group.length === 1 ? group : [];
      });
      onChange(selected.length ? retained : defaults);
    }).catch((error) => {
      if (controller.signal.aborted) return;
      setErrors([errorMessage(error, "accounts")]);
      if (error instanceof ServiceError && error.status === 401) onDisconnected();
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // Account discovery is scoped to connection/retry, not checkbox changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, attempt]);
  return <section className="sources" aria-labelledby="sources-title">
    <div className="section-heading"><div><p className="eyebrow">Your sources</p><h2 id="sources-title">Choose your business accounts</h2></div></div>
    <p className="muted">Use your Facebook, Instagram and advertising content together.</p>
    {loading && <p role="status">Loading your accounts…</p>}
    {errors.map((error) => <p key={error} role="alert" className="error">{error}</p>)}
    {!!errors.length && <button disabled={!connected || loading || disabled} onClick={() => setAttempt((value) => value + 1)}>Try accounts again</button>}
    {!loading && !errors.length && !sources.length && <p>No business accounts were shared. Reconnect Meta and choose the accounts you want to use.</p>}
    <div className="source-groups">
      {(["facebook", "instagram", "meta_ads"] as const).map((platform) => {
        const group = sources.filter((source) => source.platform === platform);
        if (!group.length) return null;
        return <fieldset key={platform} disabled={!connected || loading || disabled}>
          <legend>{{ facebook: "Facebook Pages", instagram: "Instagram accounts", meta_ads: "Ad accounts" }[platform]}</legend>
          {group.map((source) => <label className="source-choice" key={sourceKey(source)}>
            <input type="checkbox" checked={selected.some((current) => sourceKey(current) === sourceKey(source))} onChange={(event) => onChange(event.target.checked ? [...selected, source] : selected.filter((current) => sourceKey(current) !== sourceKey(source)))} />
            <span>{source.name}</span>
          </label>)}
        </fieldset>;
      })}
    </div>
  </section>;
}
