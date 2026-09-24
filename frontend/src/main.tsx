import { FormEvent, StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tiktokUrl, setTiktokUrl] = useState("");
  const [message, setMessage] = useState("Select a video to send to the API.");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedFile) {
      setMessage("Choose a video before uploading.");
      return;
    }

    const formData = new FormData();
    formData.append("video", selectedFile);
    if (tiktokUrl.trim()) {
      formData.append("tiktok_url", tiktokUrl.trim());
    }

    try {
      const response = await fetch("/api/videos", {
        method: "POST",
        body: formData,
      });
      const result = (await response.json()) as {
        detail?: string;
        filename?: string;
        metadata?: {
          duration_seconds?: number;
          video?: {
            fps?: number | null;
          };
        };
        audio?: {
          text?: string;
        };
        performance_metrics?: {
          view_count?: number | null;
          like_count?: number | null;
          comment_count?: number | null;
          share_count?: number | null;
        };
      };

      if (!response.ok) {
        throw new Error(result.detail ?? "The upload failed.");
      }

      const stats = result.performance_metrics;
      const performance = stats
        ? ` TikTok: ${stats.view_count ?? "—"} views, ${stats.like_count ?? "—"} likes, ${stats.comment_count ?? "—"} comments, ${stats.share_count ?? "—"} shares.`
        : "";
      setMessage(
        `Processed ${result.metadata?.duration_seconds}s video at ${result.metadata?.video?.fps} FPS. Transcript: ${result.audio?.text ?? ""}${performance}`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The upload failed.");
    }
  }

  return (
    <main>
      <h1>Video Analyzer</h1>
      <a href="/api/tiktok/connect" target="_blank" rel="noopener noreferrer">
        Connect TikTok (opens a new tab)
      </a>
      <form onSubmit={handleSubmit}>
        <label htmlFor="video">Video</label>
        <input
          id="video"
          type="file"
          accept="video/mp4,video/quicktime,video/x-matroska,video/webm"
          onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
        />
        <label htmlFor="tiktok-url">TikTok video URL (optional)</label>
        <input
          id="tiktok-url"
          type="url"
          value={tiktokUrl}
          placeholder="https://www.tiktok.com/@user/video/123456789"
          onChange={(event) => setTiktokUrl(event.target.value)}
        />
        <button type="submit">Upload video</button>
      </form>
      <p aria-live="polite">{message}</p>
    </main>
  );
}

const root = document.getElementById("root");

if (!root) {
  throw new Error("Application root element is missing.");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
