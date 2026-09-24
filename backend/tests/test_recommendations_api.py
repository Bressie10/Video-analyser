import os
import json
import unittest
from uuid import UUID
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import httpx
from openai import OpenAI, OpenAIError

from app.main import app
from app.recommendations import SYSTEM_PROMPT, MissingAPIKeyError, recommend_videos
from app.video_repository import get_analysis, save_analysis
from app.video_processing import VideoMetadata


VIDEO_ID = UUID("8db7e284-353b-4f3e-9bf0-44d78d888720")
ANALYSIS = {
    "metadata": {
        "duration_seconds": 12.345, "container": "mov,mp4", "file_size_bytes": 123,
        "overall_bit_rate": 800000,
        "video": {"codec": "h264", "codec_long_name": "H.264", "resolution": {"width": 1920, "height": 1080},
                  "fps": 30, "source_fps": 30, "pixel_format": "yuv420p", "bit_rate": 700000, "frame_count": 370},
        "audio": {"codec": "aac", "codec_long_name": "AAC", "sample_rate": 48000,
                  "channels": 2, "channel_layout": "stereo", "bit_rate": 96000},
    },
    "audio": {"text": "Hello world", "segments": [{"start": 0.1, "end": 1.25, "text": "Hello world"}]},
    "scenes": [{"scene_number": 1, "start_seconds": 0, "end_seconds": 12.345,
                "duration_seconds": 12.345, "cut_timestamp_seconds": None}],
    "on_screen_text": [{"text": "Watch this", "bounding_box": [[10, 20], [110, 20]],
                        "confidence": 0.987, "appearance_timestamp_seconds": 1.5,
                        "disappearance_timestamp_seconds": 3}],
    "motion_events": [{"start_seconds": 2, "end_seconds": 4.25,
                       "type": "camera_pan", "confidence": 0.875}],
}


class VideoAccessTests(unittest.TestCase):
    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"})
    @patch("app.video_repository.psycopg.connect")
    def test_save_writes_all_analysis_tables(self, connect: MagicMock) -> None:
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (VIDEO_ID,)

        self.assertEqual(save_analysis(ANALYSIS), str(VIDEO_ID))

        tables = [call.args[0].split("INSERT INTO ")[1].split()[0] for call in cursor.execute.call_args_list]
        self.assertEqual(tables, ["videos", "transcript_segments", "scenes", "on_screen_text", "motion_events"])
        self.assertEqual(cursor.execute.call_args_list[1].args[1][2:], (0.1, 1.25, "Hello world"))

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"})
    @patch("app.video_repository.psycopg.connect")
    def test_get_reconstructs_analysis(self, connect: MagicMock) -> None:
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        row = {
            "id": VIDEO_ID, "duration_seconds": 12.345, "container": "mov,mp4", "file_size_bytes": 123,
            "overall_bit_rate": 800000, "video_codec": "h264", "video_codec_long_name": "H.264",
            "width": 1920, "height": 1080, "fps": 30, "source_fps": 30, "pixel_format": "yuv420p",
            "video_bit_rate": 700000, "frame_count": 370, "audio_codec": "aac",
            "audio_codec_long_name": "AAC", "audio_sample_rate": 48000, "audio_channels": 2,
            "audio_channel_layout": "stereo", "audio_bit_rate": 96000, "transcript_text": "Hello world",
        }
        cursor.fetchone.return_value = row
        cursor.fetchall.side_effect = [
            [{"video_id": VIDEO_ID, "segment_index": 0, "start_seconds": 0.1,
              "end_seconds": 1.25, "text": "Hello world"}],
            [{"video_id": VIDEO_ID, **ANALYSIS["scenes"][0]}],
            [{"video_id": VIDEO_ID, "detection_index": 0, **ANALYSIS["on_screen_text"][0]}],
            [{"video_id": VIDEO_ID, "event_index": 0, **ANALYSIS["motion_events"][0]}],
        ]

        self.assertEqual(get_analysis(VIDEO_ID), {"video_id": str(VIDEO_ID), **ANALYSIS})
        self.assertEqual(cursor.execute.call_count, 5)

    @patch("app.main.get_analysis", return_value={"video_id": str(VIDEO_ID), **ANALYSIS})
    @patch("app.main.recommend_videos", return_value={"model": "gpt-6-sol", "response": "Idea one"})
    def test_recommendation_endpoint_returns_model_response(self, recommend: MagicMock, get: MagicMock) -> None:
        response = TestClient(app).post(f"/api/videos/{VIDEO_ID}/recommendations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"model": "gpt-6-sol", "response": "Idea one"})
        recommend.assert_called_once_with({"video_id": str(VIDEO_ID), **ANALYSIS}, api_key=None)
        get.assert_called_once_with(VIDEO_ID)

    @patch("app.main.get_analysis", return_value={"video_id": str(VIDEO_ID), **ANALYSIS})
    @patch("app.main.recommend_videos", return_value={"model": "gpt-6-sol", "response": "Idea one"})
    def test_runtime_key_is_request_only(self, recommend: MagicMock, get: MagicMock) -> None:
        key = "runtime-secret-for-test"
        with patch("app.main.save_analysis") as save:
            response = TestClient(app).post(
                f"/api/videos/{VIDEO_ID}/recommendations",
                headers={"X-OpenAI-API-Key": key},
            )
            save.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(key, response.text)
        recommend.assert_called_once_with({"video_id": str(VIDEO_ID), **ANALYSIS}, api_key=key)
        get.assert_called_once_with(VIDEO_ID)

    @patch("app.main.get_analysis", return_value={"video_id": str(VIDEO_ID), **ANALYSIS})
    @patch("app.main.recommend_videos", side_effect=OpenAIError("provider error runtime-secret-for-test"))
    def test_provider_error_does_not_expose_key(self, recommend: MagicMock, get: MagicMock) -> None:
        key = "runtime-secret-for-test"
        response = TestClient(app).post(
            f"/api/videos/{VIDEO_ID}/recommendations",
            headers={"X-OpenAI-API-Key": key},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "OpenAI request failed."})
        self.assertNotIn(key, response.text)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key_does_not_make_model_request(self) -> None:
        with patch("app.recommendations.OpenAI") as client:
            with self.assertRaises(MissingAPIKeyError):
                recommend_videos(ANALYSIS)
            client.assert_not_called()

    @patch.dict(os.environ, {"OPENAI_API_KEY": "default-test-key"})
    def test_blank_runtime_key_does_not_use_backend_default(self) -> None:
        with patch("app.recommendations.OpenAI") as client:
            with self.assertRaises(MissingAPIKeyError):
                recommend_videos(ANALYSIS, api_key="  ")
            client.assert_not_called()

    @patch("app.main.get_analysis", return_value=None)
    def test_unknown_video_returns_404(self, get: MagicMock) -> None:
        response = TestClient(app).post(f"/api/videos/{VIDEO_ID}/recommendations")
        self.assertEqual(response.status_code, 404)

    @patch("app.main.get_analysis", return_value={"video_id": str(VIDEO_ID), **ANALYSIS})
    def test_analysis_endpoint_returns_stored_data(self, get: MagicMock) -> None:
        response = TestClient(app).get(f"/api/videos/{VIDEO_ID}/analysis")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audio"]["segments"][0]["text"], "Hello world")
        self.assertEqual(response.json()["on_screen_text"][0]["text"], "Watch this")
        get.assert_called_once_with(VIDEO_ID)

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"})
    @patch("app.main.save_analysis", return_value=str(VIDEO_ID))
    @patch("app.main.inspect_video")
    @patch("app.main.normalise_video")
    @patch("app.main.detect_scenes", return_value=ANALYSIS["scenes"])
    @patch("app.main.detect_on_screen_text", return_value=ANALYSIS["on_screen_text"])
    @patch("app.main.detect_motion_events", return_value=ANALYSIS["motion_events"])
    @patch("app.main.extract_wav_audio")
    @patch("app.main.transcribe_audio", return_value=ANALYSIS["audio"])
    def test_upload_stores_analysis(self, transcribe: MagicMock, extract: MagicMock,
                                    motion: MagicMock, text: MagicMock, scenes: MagicMock,
                                    normalise: MagicMock, inspect: MagicMock,
                                    save: MagicMock) -> None:
        inspect.return_value = VideoMetadata(**ANALYSIS["metadata"])
        response = TestClient(app).post("/api/videos", files={"video": ("sample.mp4", b"video", "video/mp4")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["video_id"], str(VIDEO_ID))
        save.assert_called_once_with(ANALYSIS)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "gpt-6-sol"})
    @patch("app.recommendations.OpenAI")
    def test_client_sends_analysis_and_returns_text(self, client: MagicMock) -> None:
        sdk = client.return_value.__enter__.return_value
        sdk.responses.create.return_value.output_text = "Try a short follow-up."

        self.assertEqual(recommend_videos(ANALYSIS),
                         {"model": "gpt-6-sol", "response": "Try a short follow-up."})
        client.assert_called_once_with(api_key="test-key", timeout=60.0)
        request = sdk.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-6-sol")
        self.assertEqual(request["instructions"], SYSTEM_PROMPT)
        self.assertIn("Hello world", request["input"])
        self.assertIn("camera_pan", request["input"])
        self.assertFalse(request["store"])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "default-test-key", "OPENAI_MODEL": "gpt-6-sol"})
    def test_sdk_http_request_and_response(self) -> None:
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 1,
                "model": "gpt-6-sol", "status": "completed", "error": None,
                "incomplete_details": None, "instructions": None,
                "output": [{"id": "msg_test", "type": "message", "status": "completed",
                            "role": "assistant", "content": [{"type": "output_text",
                                                        "text": "Try a short follow-up.", "annotations": []}]}],
                "parallel_tool_calls": True, "previous_response_id": None,
                "reasoning": {"effort": "medium", "summary": None}, "store": False,
                "temperature": None, "text": {"format": {"type": "text"}},
                "tool_choice": "auto", "tools": [], "top_p": None,
                "truncation": "disabled", "usage": {"input_tokens": 10, "output_tokens": 5,
                                                  "total_tokens": 15}, "user": None,
            })

        original_client = OpenAI

        def client_with_transport(*, api_key: str, timeout: float) -> OpenAI:
            return original_client(
                api_key=api_key,
                timeout=timeout,
                http_client=httpx.Client(transport=httpx.MockTransport(respond)),
            )

        with patch("app.main.get_analysis", return_value={"video_id": str(VIDEO_ID), **ANALYSIS}), \
             patch("app.recommendations.OpenAI", side_effect=client_with_transport):
            api = TestClient(app)
            default_response = api.post(f"/api/videos/{VIDEO_ID}/recommendations")
            runtime_response = api.post(
                f"/api/videos/{VIDEO_ID}/recommendations",
                headers={"X-OpenAI-API-Key": "runtime-test-key"},
            )

        self.assertEqual(default_response.status_code, 200)
        self.assertEqual(runtime_response.status_code, 200)
        self.assertEqual(default_response.json(),
                         {"model": "gpt-6-sol", "response": "Try a short follow-up."})
        self.assertEqual(runtime_response.json(), default_response.json())
        self.assertNotIn("runtime-test-key", runtime_response.text)
        self.assertEqual([request.headers["authorization"] for request in requests],
                         ["Bearer default-test-key", "Bearer runtime-test-key"])
        for request in requests:
            self.assertEqual(request.url.path, "/v1/responses")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "gpt-6-sol")
            self.assertEqual(body["instructions"], SYSTEM_PROMPT)
            self.assertNotIn("test-key", request.content.decode())
        self.assertEqual(os.environ["OPENAI_API_KEY"], "default-test-key")

    def test_system_prompt_sets_evidence_boundaries(self) -> None:
        for phrase in (
            "all supplied videos together",
            "stronger and weaker performance",
            "supporting evidence",
            "causal claims",
            "sample is too small",
            "one original video idea",
            "Do not copy or lightly rewrite",
            "Use only the supplied",
        ):
            self.assertIn(phrase, SYSTEM_PROMPT)
        self.assertNotIn("backend", SYSTEM_PROMPT.casefold())
        self.assertNotIn("PostgreSQL", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
