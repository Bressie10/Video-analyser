"""Opt-in known-fixture checks using the actual local video/ML pipeline."""

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from app.analysis_pipeline import analyze_file
from app.meta_media import download
from app.video_processing import VideoProcessingError, inspect_video


@unittest.skipUnless(
    os.environ.get("RUN_MEDIA_INTEGRATION") == "1", "requires local OCR/Whisper models"
)
class MediaPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        import numpy as np

        cls.directory = TemporaryDirectory(prefix="meta-known-sample-")
        cls.root = Path(cls.directory.name)
        cls.silent = cls.root / "silent.mp4"
        writer = cv2.VideoWriter(
            str(cls.silent), cv2.VideoWriter_fourcc(*"mp4v"), 12, (640, 360)
        )
        if not writer.isOpened():
            raise RuntimeError("Fixture video encoder is unavailable")
        for index in range(48):
            frame = np.full(
                (360, 640, 3),
                (20, 20, 20) if index < 24 else (190, 70, 30),
                dtype=np.uint8,
            )
            cv2.putText(
                frame,
                "VIDEO TEST",
                (90, 100),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.8,
                (255, 255, 255),
                3,
            )
            cv2.rectangle(
                frame, (10 + index * 5, 220), (60 + index * 5, 270), (0, 220, 0), -1
            )
            writer.write(frame)
        writer.release()
        cls.audio = cls.root / "audio.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(cls.silent),
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=220:duration=4",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(cls.audio),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_download_and_full_analysis_with_and_without_audio(self):
        original = httpx.Client
        for source in (self.silent, self.audio):
            with (
                self.subTest(source=source.name),
                TemporaryDirectory(prefix="meta-pipeline-") as work,
            ):
                target = Path(work, "source.mp4")
                content = source.read_bytes()
                with (
                    patch(
                        "app.meta_media.socket.getaddrinfo",
                        return_value=[(0, 0, 0, "", ("8.8.8.8", 443))],
                    ),
                    patch(
                        "app.meta_media.httpx.Client",
                        side_effect=lambda **kw: original(
                            transport=httpx.MockTransport(
                                lambda request: httpx.Response(200, content=content)
                            ),
                            **kw,
                        ),
                    ),
                ):
                    download("https://fixture.fbcdn.net/video", target)
                result = analyze_file(target, work, allow_silent=True)
                self.assertAlmostEqual(
                    result["metadata"]["duration_seconds"], 4, places=1
                )
                self.assertEqual(
                    result["metadata"]["video"]["resolution"],
                    {"width": 640, "height": 360},
                )
                self.assertGreaterEqual(len(result["scenes"]), 2)
                self.assertIn(
                    "VIDEO TEST",
                    " ".join(row["text"] for row in result["on_screen_text"]).upper(),
                )
                self.assertIsInstance(result["motion_events"], list)
                self.assertTrue(result["motion_events"])
                for motion in result["motion_events"]:
                    self.assertIn("start_seconds", motion)
                    self.assertIn("end_seconds", motion)
                    self.assertNotIn("start", motion)
                self.assertIsInstance(result["audio"]["segments"], list)
                if source == self.silent:
                    self.assertIsNone(result["metadata"]["audio"]["codec"])
                    self.assertEqual(result["audio"], {"text": "", "segments": []})
                else:
                    self.assertEqual(result["metadata"]["audio"]["codec"], "aac")

    def test_legacy_upload_still_requires_audio(self):
        with self.assertRaises(VideoProcessingError):
            inspect_video(self.silent)
        self.assertIsNone(inspect_video(self.silent, allow_silent=True).audio["codec"])
