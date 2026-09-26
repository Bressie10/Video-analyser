import { FormEvent, StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Analysis = {
  video_id: string;
  metadata: { duration_seconds: number; video: { resolution: { width: number; height: number }; fps: number | null } };
  audio: { text: string };
  scenes: { scene_number: number; start_seconds: number; end_seconds: number }[];
  on_screen_text: { text: string; appearance_timestamp_seconds: number; disappearance_timestamp_seconds: number }[];
  motion_events: { type: string; start_seconds: number; end_seconds: number }[];
  performance_source?: "tiktok" | "instagram" | "facebook" | "meta_ads";
  performance_metrics?: { view_count: number | null; like_count: number | null; comment_count: number | null; share_count: number | null };
};
type Recommendation = { model: string; response: string };
type Platform = "tiktok" | "instagram";
type Stage = "idle" | "uploading" | "processing" | "loading" | "metrics" | "generating" | "complete";

function responseError(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((item) => item.msg ?? String(item)).join("; ");
  }
  return fallback;
}

async function readResponse<T>(response: Response, fallback: string): Promise<T> {
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(responseError(body, fallback));
  return body as T;
}

function uploadVideo(file: File, tiktokUrl: string, onProcessing: () => void): Promise<Analysis> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("video", file);
    if (tiktokUrl) form.append("tiktok_url", tiktokUrl);
    const request = new XMLHttpRequest();
    request.open("POST", "/api/videos");
    request.upload.addEventListener("load", onProcessing);
    request.addEventListener("load", () => {
      let body: unknown;
      try { body = JSON.parse(request.responseText); }
      catch { reject(new Error("The server returned an invalid response.")); return; }
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(responseError(body, "Video analysis failed.")));
        return;
      }
      resolve(body as Analysis);
    });
    request.addEventListener("error", () => reject(new Error("Could not reach the server.")));
    request.send(form);
  });
}

const count = (value: number | null | undefined) => value == null ? "Unavailable" : value.toLocaleString();
const seconds = (value: number) => `${Number(value).toFixed(1)}s`;

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tiktokUrl, setTiktokUrl] = useState("");
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [metaIdentifier, setMetaIdentifier] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const busy = stage === "uploading" || stage === "processing" || stage === "loading" || stage === "metrics" || stage === "generating";
  const status = {
    idle: "Ready to analyze a video.",
    uploading: "Uploading video…",
    processing: "Processing video… This can take several minutes.",
    loading: "Loading saved analysis from the database…",
    metrics: "Retrieving Instagram Reel metrics…",
    generating: "Generating recommendation and script…",
    complete: "Analysis complete.",
  }[stage];

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile || !apiKey.trim()) {
      setError("Choose a matching video file and enter your OpenAI API key."); return;
    }
    if (platform === "tiktok" && !tiktokUrl.trim()) {
      setError("Enter the matching TikTok video URL."); return;
    }
    if (platform === "instagram" && !/^[0-9]{1,30}$/.test(metaIdentifier.trim())) {
      setError("Enter a numeric Instagram Graph media ID (1–30 digits). Public Reel URLs and shortcodes are not supported yet."); return;
    }
    setError(""); setAnalysis(null); setRecommendation(null); setStage("uploading");
    try {
      const uploaded = await uploadVideo(selectedFile, platform === "tiktok" ? tiktokUrl.trim() : "", () => setStage("processing"));
      if (!uploaded.video_id) throw new Error("The upload was processed but was not saved. Configure the backend database to generate recommendations.");
      setStage("loading");
      const saved = await readResponse<Analysis>(
        await fetch(`/api/videos/${encodeURIComponent(uploaded.video_id)}/analysis`),
        "Could not load the saved analysis.",
      );
      setAnalysis(saved);
      if (platform === "instagram") {
        setStage("metrics");
        const performance = await readResponse<Pick<Analysis, "performance_source" | "performance_metrics">>(
          await fetch(`/api/meta/instagram/reels/${encodeURIComponent(metaIdentifier.trim())}/metrics`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_id: uploaded.video_id }),
          }),
          "Could not retrieve content metrics. Your video analysis has been saved.",
        );
        setAnalysis({ ...saved, ...performance });
      }
      setStage("generating");
      const generated = await readResponse<Recommendation>(
        await fetch(`/api/videos/${encodeURIComponent(uploaded.video_id)}/recommendations`, {
          method: "POST", headers: { "X-OpenAI-API-Key": apiKey.trim() },
        }),
        "Could not generate the recommendation.",
      );
      setRecommendation(generated); setStage("complete");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Analysis failed.");
      setStage("idle");
    }
  }

  return <main>
    <h1>Video Analyzer</h1>
    <p>Analyze your video content and performance, then get an idea and script for the next one.</p>
    {platform === "tiktok" && <p><a href="/api/tiktok/connect">Connect your TikTok account</a> before analyzing a video. The video URL must belong to that account.</p>}
    <form onSubmit={handleSubmit}>
      <label htmlFor="platform">Platform / content type</label>
      <select id="platform" value={platform} disabled={busy} onChange={(event) => {
        setPlatform(event.target.value as Platform); setMetaIdentifier("");
        setError(""); setAnalysis(null); setRecommendation(null); setStage("idle");
      }}>
        <option value="tiktok">TikTok video</option>
        <option value="instagram">Instagram Reel</option>
      </select>
      <label htmlFor="video">Video file</label>
      <input id="video" type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm" required disabled={busy}
        onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
      <small>Choose the same video as the content identifier below.</small>
      {platform === "tiktok" ? <>
      <label htmlFor="tiktok-url">Matching TikTok video URL</label>
      <input id="tiktok-url" type="url" value={tiktokUrl} required disabled={busy}
        placeholder="https://www.tiktok.com/@user/video/123456789"
        onChange={(event) => setTiktokUrl(event.target.value)} />
      </> : <>
        <label htmlFor="meta-identifier">Instagram Graph media ID</label>
        <input id="meta-identifier" type="text" value={metaIdentifier} required disabled={busy}
          aria-describedby="meta-identifier-help" inputMode="numeric"
          placeholder="17895695668004550"
          onChange={(event) => setMetaIdentifier(event.target.value)} />
        <small id="meta-identifier-help">Use a connected Meta account. Enter the numeric Graph media ID for your Reel, not its public URL or shortcode. URL lookup is not supported yet.</small>
      </>}
      <label htmlFor="api-key">OpenAI API key</label>
      <input id="api-key" type="password" value={apiKey} required disabled={busy} autoComplete="off"
        onChange={(event) => setApiKey(event.target.value)} />
      <small>The key is used for this request and is not saved by the frontend.</small>
      <button type="submit" disabled={busy}>{busy ? "Analyzing…" : "Analyze video"}</button>
    </form>
    <p role="status" aria-live="polite">{status}</p>
    {error && <p role="alert" className="error">{error}</p>}
    {analysis && <section aria-labelledby="analysis-title">
      <h2 id="analysis-title">Video analysis</h2>
      <p>Duration: {seconds(analysis.metadata.duration_seconds)} · Resolution: {analysis.metadata.video.resolution.width} × {analysis.metadata.video.resolution.height} · FPS: {analysis.metadata.video.fps ?? "Unavailable"}</p>
      <h3>Video performance</h3>
      {analysis.performance_metrics ? <dl className="stats">
        <div><dt>Views</dt><dd>{count(analysis.performance_metrics.view_count)}</dd></div>
        <div><dt>Likes</dt><dd>{count(analysis.performance_metrics.like_count)}</dd></div>
        <div><dt>Comments</dt><dd>{count(analysis.performance_metrics.comment_count)}</dd></div>
        <div><dt>Shares</dt><dd>{count(analysis.performance_metrics.share_count)}</dd></div>
      </dl> : <p>Performance stats were not available.</p>}
      <h3>Transcript</h3><p>{analysis.audio.text || "No speech detected."}</p>
      <h3>Scenes</h3>
      {analysis.scenes.length ? <ul>{analysis.scenes.map((scene) => <li key={scene.scene_number}>Scene {scene.scene_number}: {seconds(scene.start_seconds)}–{seconds(scene.end_seconds)}</li>)}</ul> : <p>No scene cuts detected.</p>}
      <h3>On-screen text</h3>
      {analysis.on_screen_text.length ? <ul>{analysis.on_screen_text.map((item, index) => <li key={index}>{seconds(item.appearance_timestamp_seconds)}–{seconds(item.disappearance_timestamp_seconds)}: {item.text}</li>)}</ul> : <p>No on-screen text detected.</p>}
      <h3>Motion events</h3>
      {analysis.motion_events.length ? <ul>{analysis.motion_events.map((item, index) => <li key={index}>{seconds(item.start_seconds)}–{seconds(item.end_seconds)}: {item.type.replaceAll("_", " ")}</li>)}</ul> : <p>No motion events detected.</p>}
      <details><summary>Full analysis data</summary><pre>{JSON.stringify(analysis, null, 2)}</pre></details>
    </section>}
    {recommendation && <section aria-labelledby="recommendation-title">
      <h2 id="recommendation-title">Recommendation and script</h2>
      <p className="generated">{recommendation.response || "The model returned no text."}</p>
    </section>}
  </main>;
}

const root = document.getElementById("root");
if (!root) throw new Error("Application root element is missing.");
createRoot(root).render(<StrictMode><App /></StrictMode>);
