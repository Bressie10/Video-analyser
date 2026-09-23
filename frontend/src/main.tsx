import { FormEvent, StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [message, setMessage] = useState("Select a video to send to the API.");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedFile) {
      setMessage("Choose a video before uploading.");
      return;
    }

    const formData = new FormData();
    formData.append("video", selectedFile);

    try {
      const response = await fetch("/api/videos", {
        method: "POST",
        body: formData,
      });
      const result = (await response.json()) as {
        detail?: string;
        filename?: string;
        duration_seconds?: number;
        status?: string;
      };

      if (!response.ok) {
        throw new Error(result.detail ?? "The upload failed.");
      }

      setMessage(
        `Backend ${result.status}: ${result.filename} (${result.duration_seconds}s)`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The upload failed.");
    }
  }

  return (
    <main>
      <h1>Video Analyzer</h1>
      <form onSubmit={handleSubmit}>
        <label htmlFor="video">Video</label>
        <input
          id="video"
          type="file"
          accept="video/mp4,video/quicktime,video/x-matroska,video/webm"
          onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
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
