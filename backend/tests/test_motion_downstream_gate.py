"""Legacy motion observations stay in stored evidence, outside model evidence."""

import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from app.idea_generation import IDEA_PROMPT, generate_idea
from app.idea_models import GeneratedIdea
from app.recommendations import SYSTEM_PROMPT, recommend_videos


ANALYSIS = {
    "metadata": {"duration_seconds": 12},
    "audio": {"text": "Try this"},
    "scenes": [{"start_seconds": 0, "end_seconds": 12}],
    "on_screen_text": [{"text": "Try this"}],
    "motion_events": [
        {"type": kind, "start_seconds": index, "end_seconds": index + 0.5}
        for index, kind in enumerate(("camera_pan", "camera_zoom", "camera_shake",
                                      "general_motion", "local_motion", "unknown"))
    ],
    "performance_metrics": {"view_count": 100},
}


class MotionDownstreamGateTests(unittest.TestCase):
    def test_shared_prompts_exclude_motion_comparison(self):
        for prompt in (SYSTEM_PROMPT, IDEA_PROMPT):
            self.assertIn("Motion detector labels are unavailable", prompt)
            self.assertIn("Do not compare or credit camera pan, zoom, shake", prompt)
            self.assertNotIn("Compare transcript hooks, scene timing/editing, on-screen text, motion", prompt)
            self.assertNotIn("motion events, and performance metrics", prompt)

    @patch("app.recommendations.OpenAI")
    def test_recommendation_model_input_omits_motion_without_changing_analysis(self, client):
        analysis = deepcopy(ANALYSIS)
        original = deepcopy(analysis)
        client.return_value.__enter__.return_value.responses.create.return_value.output_text = "Idea"

        self.assertEqual(recommend_videos(analysis, api_key="test-key"),
                         {"model": "gpt-6-sol", "response": "Idea"})
        request = client.return_value.__enter__.return_value.responses.create.call_args.kwargs
        sent = json.loads(request["input"].split("\n", 1)[1])
        self.assertNotIn("motion_events", sent)
        self.assertEqual(sent, {key: value for key, value in original.items()
                                if key != "motion_events"})
        self.assertEqual(analysis, original)

    @patch("app.idea_generation.OpenAI")
    def test_idea_model_input_omits_nested_motion_without_changing_evidence(self, client):
        evidence = {
            "videos": [{"analysis_payload": deepcopy(ANALYSIS),
                        "performance_ids": ["snapshot-1"]}],
            "performance_snapshots": [{"id": "snapshot-1", "view_count": 100}],
            "generation_brief": "Make a tutorial",
        }
        original = deepcopy(evidence)
        result = GeneratedIdea(title="Tutorial", concept="Show the method", script="Start. Show. End.")
        client.return_value.__enter__.return_value.responses.parse.return_value = (
            SimpleNamespace(status="completed", output_parsed=result))

        self.assertEqual(generate_idea(evidence, model="test-model", api_key="test-key"), result)
        request = client.return_value.__enter__.return_value.responses.parse.call_args.kwargs
        sent = json.loads(request["input"])
        self.assertNotIn("motion_events", sent["videos"][0]["analysis_payload"])
        self.assertEqual(sent["videos"][0]["analysis_payload"],
                         {key: value for key, value in ANALYSIS.items() if key != "motion_events"})
        self.assertEqual(sent["performance_snapshots"], original["performance_snapshots"])
        self.assertEqual(sent["generation_brief"], original["generation_brief"])
        self.assertEqual(evidence, original)


if __name__ == "__main__":
    unittest.main()
