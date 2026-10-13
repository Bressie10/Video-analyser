"""Presentation-only citation enrichment keeps validated source references intact."""

from unittest import TestCase

from app.company_intelligence import _readable_citations, _readable_differences


class ReadableEvidenceTests(TestCase):
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
