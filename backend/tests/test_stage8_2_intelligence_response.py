"""Presentation-only citation enrichment keeps validated source references intact."""

from unittest import TestCase

import base64

import cv2
import numpy as np

from app.company_intelligence import _creative_previews, _readable_citations, _readable_differences


class ReadableEvidenceTests(TestCase):
    def test_previews_are_bounded_and_use_only_sampled_authorized_frames(self):
        pixels = np.zeros((480, 800, 3), dtype=np.uint8)
        pixels[:, :, 1] = 90
        encoded, jpeg = cv2.imencode('.jpg', pixels)
        self.assertTrue(encoded)
        case = {"images": [("frame:0", jpeg.tobytes())], "packets": [
            {"video_ref": "video_demo", "frames": [{"ref": "frame:0", "timestamp_seconds": 0.5}]},
            {"video_ref": "video_missing", "frames": [{"ref": "frame:1", "timestamp_seconds": 1.0}]}]}
        previews = _creative_previews(case)
        self.assertEqual(len(previews), 1)
        self.assertEqual(set(previews[0]), {"video_ref", "frame_ref", "timestamp_seconds", "jpeg_base64"})
        self.assertEqual(previews[0]["frame_ref"], "frame:0")
        self.assertLessEqual(len(base64.b64decode(previews[0]["jpeg_base64"])), 64 * 1024)
        resized = cv2.imdecode(np.frombuffer(base64.b64decode(previews[0]["jpeg_base64"]), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(max(resized.shape[:2]), 320)

    def test_unreadable_sampled_image_does_not_create_preview(self):
        case = {"images": [("frame:0", b"not a jpeg")], "packets": [
            {"video_ref": "video_demo", "frames": [{"ref": "frame:0", "timestamp_seconds": 0.5}]}]}
        self.assertEqual(_creative_previews(case), [])

    def test_transcript_and_ocr_excerpts_follow_bounded_packet_refs(self):
        packet = {"video_ref": "video_demo", "transcript": [
            {"ref": "video_demo:transcript:0", "text": "Spoken offer"}],
            "ocr": [{"ref": "video_demo:ocr:0", "text": "Offer card"}]}
        support = {"video_ref": "video_demo", "evidence_ref": "video_demo:transcript:0",
                   "evidence_type": "transcript", "timestamp_seconds": 1.5}
        counter = {**support, "evidence_ref": "video_demo:ocr:0", "evidence_type": "ocr"}
        difference = {"description": "An observed difference", "evidence_refs": [support],
                      "counterexamples": [counter]}
        readable = _readable_differences([difference], [packet])[0]
        self.assertEqual(readable["evidence_refs"], [{**support, "excerpt": "Spoken offer"}])
        self.assertEqual(readable["counterexamples"], [{**counter, "excerpt": "Offer card"}])
        self.assertEqual(difference["evidence_refs"], [support])

    def test_frames_keep_reference_without_raw_image(self):
        frame = {"video_ref": "video_demo", "evidence_ref": "video_demo:frame:0",
                 "evidence_type": "frame", "timestamp_seconds": 0.5}
        self.assertEqual(_readable_citations([frame], [{"transcript": [], "ocr": []}]), [frame])
