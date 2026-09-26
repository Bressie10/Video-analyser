import type { Source } from "./metaLibrary";

export function MetaBrowser({ sources, selected, complete, loading, onChange, disabled }: {
  sources: Source[]; selected: Set<string>; complete: boolean; loading: boolean;
  onChange: (ids: Set<string>) => void; disabled: boolean;
}) {
  return <section className="sources" aria-labelledby="sources-title">
    <div className="section-heading"><div><p className="eyebrow">Your sources</p><h2 id="sources-title">Choose your business accounts</h2></div></div>
    <p className="muted">Use your Facebook, Instagram and advertising content together.</p>
    {loading && !complete && <p role="status">Finding accounts in your video library…</p>}
    {complete && !sources.length && <p>Accounts will appear here when their content has synced.</p>}
    <div className="source-groups">
      {(["facebook", "instagram", "meta_ads"] as const).map((platform) => {
        const group = sources.filter((source) => source.platform === platform);
        if (!group.length) return null;
        return <fieldset key={platform} disabled={disabled || !complete}>
          <legend>{{ facebook: "Facebook Pages", instagram: "Instagram accounts", meta_ads: "Ad accounts" }[platform]}</legend>
          {group.map((source, index) => <label className="source-choice" key={source.id}>
            <input type="checkbox" checked={selected.has(source.id)} onChange={(event) => {
              const next = new Set(selected); if (event.target.checked) next.add(source.id); else next.delete(source.id); onChange(next);
            }} />
            <span>{source.name}{group.filter((entry) => entry.name === source.name).length > 1 ? ` (${index + 1})` : ""}</span>
          </label>)}
        </fieldset>;
      })}
    </div>
  </section>;
}
