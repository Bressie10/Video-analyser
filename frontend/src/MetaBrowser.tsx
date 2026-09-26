import { useEffect, useState } from "react";

export type MetaSelection = { id: string; pageId: string; kind: string; name: string };
type Item = { id: string; name: string; type: string; thumbnail?: string; created_at?: string; status?: string; selectable?: boolean };
type Listing = { items: Item[]; next_cursor: string | null };
type Props = { platform: string; disabled: boolean; onSelect: (selection: MetaSelection | null) => void; onDisconnected: () => void };

function Choices({ path, label, disabled, selected, onChoose, onDisconnected, cards = false }: {
  path: string; label: string; disabled: boolean; selected: string;
  onChoose: (item: Item) => void; onDisconnected: () => void; cards?: boolean;
}) {
  const [data, setData] = useState<Listing>({ items: [], next_cursor: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    fetch(`/api/meta/discovery/${path}${cursor ? `?after=${encodeURIComponent(cursor)}` : ""}`, {
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]), cache: "no-store",
    }).then(async (response) => {
      if (controller.signal.aborted) return;
      if (response.status === 401) { onDisconnected(); return; }
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Could not load content. Try again.");
      if (controller.signal.aborted) return;
      setData((previous) => ({ ...result, items: cursor
        ? [...previous.items, ...result.items.filter((item: Item) => !previous.items.some((old) => old.id === item.id))]
        : result.items }));
      if (!cards && !cursor && !result.next_cursor && result.items.length === 1) onChoose(result.items[0]);
    }).catch((caught) => {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Could not load content.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // Parents key each list by its source; callbacks do not change the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, cursor, attempt]);
  return <div className="meta-list">
    <p><strong>{label}</strong></p>
    {loading && <p role="status">Loading {label.toLowerCase()}…</p>}
    {error && <><p role="alert" className="error">{error}</p><button type="button" disabled={disabled} onClick={() => setAttempt(attempt + 1)}>Try again</button></>}
    {!loading && !error && data.items.length === 0 && <p role="status">No {label.toLowerCase()} available. Check that you shared access when connecting Meta.</p>}
    <div className={cards ? "meta-grid" : "meta-options"}>
      {data.items.map((item) => <button key={item.id} type="button" disabled={disabled || item.selectable === false}
        aria-pressed={selected === item.id} onClick={() => onChoose(item)}>
        {cards && item.thumbnail && <img src={item.thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer" onError={(event) => { event.currentTarget.hidden = true; }} />}
        <span>{item.name}</span>
        {cards && <small>{item.type.replaceAll("_", " ").toLowerCase()}{item.status ? ` · ${item.status.replaceAll("_", " ").toLowerCase()}` : ""}
          {item.created_at && !Number.isNaN(Date.parse(item.created_at)) ? ` · ${new Date(item.created_at).toLocaleDateString()}` : ""}</small>}
        {item.selectable === false && <small>Only Reels can be analyzed currently.</small>}
      </button>)}
    </div>
    {data.next_cursor && !error && <button type="button" disabled={loading || disabled} onClick={() => setCursor(data.next_cursor)}>Load more {label.toLowerCase()}</button>}
  </div>;
}

export function MetaBrowser({ platform, disabled, onSelect, onDisconnected }: Props) {
  const [page, setPage] = useState<Item | null>(null);
  const [account, setAccount] = useState<Item | null>(null);
  const [kind, setKind] = useState("reels");
  const [selected, setSelected] = useState("");
  function clear() { setSelected(""); onSelect(null); }
  const ads = platform === "meta_ads";
  const path = ads && account ? `ad-accounts/${account.id}/ads`
    : platform === "facebook" && page ? `pages/${page.id}/facebook/${kind}`
    : platform === "instagram" && page && account ? `pages/${page.id}/instagram/${account.id}/media` : "";
  return <div aria-label="Browse Meta content">
    <Choices path={ads ? "ad-accounts" : "pages"} label={ads ? "Ad accounts" : "Facebook Pages"} disabled={disabled}
      selected={ads ? account?.id ?? "" : page?.id ?? ""} onDisconnected={onDisconnected}
      onChoose={(item) => { clear(); if (ads) setAccount(item); else { setPage(item); setAccount(null); } }} />
    {platform === "instagram" && page && <Choices key={page.id} path={`pages/${page.id}/instagram-accounts`}
      label="Instagram accounts" disabled={disabled} selected={account?.id ?? ""} onDisconnected={onDisconnected}
      onChoose={(item) => { clear(); setAccount(item); }} />}
    {platform === "facebook" && page && <><label htmlFor="facebook-kind">Facebook content type</label>
      <select id="facebook-kind" disabled={disabled} value={kind} onChange={(event) => { clear(); setKind(event.target.value); }}>
        <option value="reels">Reels</option><option value="videos">Videos</option>
      </select></>}
    {path && <Choices key={path} path={path} label={ads ? "Ads" : "Content"} cards disabled={disabled}
      selected={selected} onDisconnected={onDisconnected} onChoose={(item) => {
        setSelected(item.id); onSelect({ id: item.id, pageId: page?.id ?? "", kind, name: item.name });
      }} />}
  </div>;
}
