"""Disposable PostgreSQL through the company API and frozen intelligence stages."""

from copy import deepcopy
from contextlib import ExitStack
from datetime import date
import os
from unittest import TestCase
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import AuthenticatedUser, require_authenticated_user
from app.main import app
from app import performance_observation_repository as history
from app import company_intelligence
from intelligence.cross_video_content import Citation, ComparisonDraft, Pattern
from intelligence.creative_hypotheses import Proposal, ProposalBatch
import test_performance_observations_database as fixture


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class IntelligenceDatabaseTests(TestCase):
    setUp = fixture.ObservationDatabaseTests.setUp
    cleanup_schema = fixture.ObservationDatabaseTests.cleanup_schema

    def seed(self, count=6, content=False):
        for index in range(count):
            ad_id = str(100 + index)
            item = self.db.execute("""INSERT INTO meta_library_items
                (connection_id,account_id,platform,external_id,content_type,label)
                VALUES (%s,%s,'meta_ads',%s,'ad','Fixture') RETURNING id""",
                (self.connection, self.account_uuid, ad_id)).fetchone()["id"]
            self.db.execute("""INSERT INTO company_ad_assignments
                (ad_item_id,company_id,connection_id,account_id) VALUES (%s,%s,%s,%s)""",
                (item, self.company, self.connection, self.account_uuid))
            if content:
                video = self.db.execute("""INSERT INTO videos
                    (duration_seconds,container,file_size_bytes,meta_connection_id)
                    VALUES (12,'mp4',100,%s) RETURNING id""", (self.connection,)).fetchone()["id"]
                asset = self.db.execute("""INSERT INTO meta_library_items
                    (connection_id,account_id,platform,external_id,content_type,label,
                     video_id,analysis_state,analysis_version)
                    VALUES (%s,%s,'facebook',%s,'video','Asset',%s,'completed',1) RETURNING id""",
                    (self.connection, self.account_uuid, str(200 + index), video)).fetchone()["id"]
                self.db.execute("INSERT INTO meta_ad_assets VALUES (%s,%s)", (item, asset))
                self.db.execute("""INSERT INTO scenes
                    (video_id,scene_number,start_seconds,end_seconds,duration_seconds)
                    VALUES (%s,1,0,12,12)""", (video,))
                self.db.execute("""INSERT INTO transcript_segments
                    (video_id,segment_index,start_seconds,end_seconds,text)
                    VALUES (%s,0,1,2,%s)""", (video, 'Offer' if index >= 3 else 'Setup'))
            details = deepcopy(fixture.DETAILS)
            details["ctr"] = str(index + 1)
            history.save_meta_ad_observation(self.user, self.company, self.connection, item,
                {"ad_id": ad_id, "account_id": "123", "placement_scope": "meta_all_placements"},
                {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": details}})
        return item

    def call(self, *, company=None, account=None, metric="ctr"):
        app.dependency_overrides[require_authenticated_user] = lambda: AuthenticatedUser(self.user.user_id)
        self.addCleanup(lambda: app.dependency_overrides.pop(require_authenticated_user, None))
        with TestClient(app) as client:
            return client.post(f"/api/companies/{company or self.company}/intelligence", json={
                "account_id": str(account or self.account_uuid), "metric_id": metric,
                "date_start": "2026-01-01", "date_stop": "2026-01-07"})

    def test_degraded_history_and_latest_version(self):
        item = self.seed()
        details = deepcopy(fixture.DETAILS)
        details["ctr"] = "9"
        history.save_meta_ad_observation(self.user, self.company, self.connection, item,
            {"ad_id": "105", "account_id": "123", "placement_scope": "meta_all_placements"},
            {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": details}})
        with patch("app.company_intelligence.library.connection_client") as provider:
            response = self.call()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["cohort"]["distinct_ads"], 6)
        self.assertEqual(result["cohort"]["observation_count"], 7)
        self.assertEqual(result["cohort"]["peer_count"], 5)
        self.assertIsNotNone(result["performance"])
        self.assertEqual(result["hypotheses"], [])
        self.assertEqual(result["provenance"]["model_calls"], 0)
        self.assertIn("insufficient_source_video_coverage", result["abstentions"])
        provider.assert_not_called()

    def test_full_api_path_and_validated_models(self):
        self.seed(content=True)
        calls = []
        def content_call(instructions, payload, images, schema, *, model, api_key):
            calls.append(schema.__name__)
            videos = {v["video_ref"]: v for v in payload["videos"]}
            refs = [Citation(video_ref=video_ref,
                             evidence_ref=videos[video_ref]["transcript"][0]["ref"])
                    for video_ref in payload["higher_video_refs"]]
            return ComparisonDraft(patterns=[Pattern(
                description="Spoken offer is heard more often in the higher-CTR group.",
                evidence_type="transcript", higher_support=refs,
                lower_support=[], counterexamples=[], temporal_relation="none")],
                similarities=[], evidence_gaps=[]), {"model": model, "input_tokens": 100,
                                                      "output_tokens": 50, "elapsed_seconds": 0.1}
        def proposal_call(instructions, payload, images, schema, *, model, api_key):
            calls.append(schema.__name__)
            return ProposalBatch(hypotheses=[Proposal(source_index=0,
                hypothesis="Test whether spoken content is associated with a different CTR under comparable delivery.",
                variable_to_test="spoken content", control_condition="The offer is not spoken in the opening.",
                variant_condition="The offer is spoken in the opening.", limitations=[])],
                abstentions=[]), {"model": model, "input_tokens": 80,
                                  "output_tokens": 40, "elapsed_seconds": 0.1}
        def frames(path, plan):
            return ([{"ref": "frame:0", "timestamp_seconds": 0.5,
                      "selection_reason": "opening", "jpeg_sha256": "abc"}], [{"_jpeg": b"jpeg"}])
        with patch("app.company_intelligence.library.connection_client", return_value=object()), \
             patch("app.company_intelligence.media_url", side_effect=lambda client, item: item["external_id"]), \
             patch("app.company_intelligence.download", side_effect=lambda url, path: path.write_bytes(b"video")), \
             patch("intelligence.evaluation.stage5_semantic.select_frame_timestamps",
                   return_value=[{"timestamp_seconds": 0.5, "reason": "opening"}]), \
             patch("intelligence.evaluation.stage5_semantic.extract_frames", side_effect=frames), \
             patch("intelligence.cross_video_content._model_call", side_effect=content_call), \
             patch("intelligence.creative_hypotheses._model_call", side_effect=proposal_call):
            response = self.call()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(calls, ["ComparisonDraft", "ProposalBatch"])
        self.assertEqual(result["cohort"]["peer_count"], 5)
        self.assertEqual(len(result["content_differences"]), 1)
        self.assertEqual(len(result["hypotheses"]), 1)
        self.assertEqual(result["provenance"]["model_calls"], 2)
        self.assertNotIn("token_ciphertext", str(result))

    def test_cohort_authorization_and_metric_failures(self):
        self.seed(count=5)
        result = self.call().json()
        self.assertIn("insufficient_historical_cohort", result["abstentions"])
        self.assertEqual(self.call(metric="reach").status_code, 422)
        self.assertEqual(self.call(account=uuid4()).status_code, 404)
        self.assertEqual(self.call(company=uuid4()).status_code, 403)
        self.db.execute("UPDATE meta_connections SET status='reconnect_required' WHERE id=%s",
                        (self.connection,))
        disconnected = self.call().json()
        self.assertIn("meta_disconnected", disconnected["abstentions"])
        self.assertEqual(disconnected["provenance"]["model_calls"], 0)

    def test_media_and_validator_failures_abstain(self):
        self.seed(content=True)
        def frames(path, plan):
            return ([{"ref": "frame:0", "timestamp_seconds": 0.5,
                      "selection_reason": "opening", "jpeg_sha256": "abc"}], [{"_jpeg": b"jpeg"}])
        with ExitStack() as mocks:
            mocks.enter_context(patch("app.company_intelligence.library.connection_client",
                                      return_value=object()))
            mocks.enter_context(patch("app.company_intelligence.media_url",
                                      side_effect=lambda client, item: item["external_id"]))
            download = mocks.enter_context(patch("app.company_intelligence.download",
                                      side_effect=lambda url, path: path.write_bytes(b"video")))
            mocks.enter_context(patch("intelligence.evaluation.stage5_semantic.select_frame_timestamps",
                                      return_value=[{"timestamp_seconds": 0.5, "reason": "opening"}]))
            mocks.enter_context(patch("intelligence.evaluation.stage5_semantic.extract_frames",
                                      side_effect=frames))
            def run(**changes):
                return company_intelligence.generate(self.user, self.company, self.account_uuid,
                    "ctr", date(2026, 1, 1), date(2026, 1, 7), **changes)
            from app.meta_media import MediaUnavailable
            download.side_effect = MediaUnavailable("gone")
            media = run(compare_content=lambda case: self.fail("model was called"))
            self.assertEqual(media["provenance"]["model_calls"], 0)
            self.assertIn("source_media_unavailable", media["abstentions"])
            download.side_effect = lambda url, path: path.write_bytes(b"video")
            def invalid_difference(case):
                from intelligence.cross_video_content import run_one_pass
                draft = ComparisonDraft(patterns=[Pattern(
                    description="The spoken offer caused more clicks.", evidence_type="transcript",
                    higher_support=[], lower_support=[], counterexamples=[],
                    temporal_relation="none")], similarities=[], evidence_gaps=[])
                return run_one_pass(case, ask=lambda *a, **k: (draft, {"model": "fixture"}))
            invalid = run(compare_content=invalid_difference)
            self.assertIn("content_model_or_validation_failed", invalid["abstentions"])
            self.assertEqual(invalid["provenance"]["model_calls"], 1)
            timeout = run(compare_content=lambda case: (_ for _ in ()).throw(TimeoutError()))
            self.assertIn("content_model_or_validation_failed", timeout["abstentions"])
            self.assertEqual(timeout["provenance"]["model_calls"], 1)
            def valid_difference(case):
                from intelligence.cross_video_content import run_one_pass
                high = case["groups"]["higher_metric_group"]
                packets = {row["video_ref"]: row for row in case["packets"]}
                refs = [Citation(video_ref=row["video_ref"],
                    evidence_ref=packets[row["video_ref"]]["transcript"][0]["ref"])
                    for row in high]
                draft = ComparisonDraft(patterns=[Pattern(
                    description="Spoken offer is heard more often in the higher-CTR group.",
                    evidence_type="transcript", higher_support=refs, lower_support=[],
                    counterexamples=[], temporal_relation="none")], similarities=[], evidence_gaps=[])
                return run_one_pass(case, ask=lambda *a, **k: (draft, {"model": "fixture"}))
            def invalid_hypothesis(differences, report):
                from intelligence.creative_hypotheses import run_one_call
                bad = ProposalBatch(hypotheses=[Proposal(source_index=0,
                    hypothesis="Spoken content improves CTR.", variable_to_test="spoken content",
                    control_condition="The offer is not spoken.",
                    variant_condition="The offer is spoken.", limitations=[])], abstentions=[])
                return run_one_call(differences, report,
                    ask=lambda *a, **k: (bad, {"model": "fixture"}))
            rejected = run(compare_content=valid_difference, propose=invalid_hypothesis)
            self.assertEqual(len(rejected["content_differences"]), 1)
            self.assertEqual(rejected["hypotheses"], [])
            self.assertIn("hypothesis_model_or_validation_failed", rejected["abstentions"])
            self.assertEqual(rejected["provenance"]["model_calls"], 2)
