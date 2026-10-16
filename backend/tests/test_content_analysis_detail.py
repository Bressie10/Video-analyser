"""Content analysis allowlist and company scope without a live provider."""

import json
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from app import content_analysis_routes as subject, meta_library_repository as library


class Query:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class Database:
    def __init__(self, row): self.row = row; self.calls = []
    def execute(self, sql, params):
        self.calls.append((sql, params))
        return Query(self.row)


class ContentDetailTests(TestCase):
    def setUp(self):
        self.company, self.item, self.connection, self.video = (uuid4() for _ in range(4))
        self.asset = {'id': self.item, 'video_id': self.video, 'platform': 'instagram',
                      'content_type': 'reel', 'analysis_state': 'completed',
                      'analysis_version': library.ANALYSIS_VERSION, 'published_at': datetime.now(timezone.utc)}

    @patch.object(subject.ownership, '_selected')
    @patch.object(subject, 'authorize')
    def test_selected_uses_company_scope_and_current_video(self, authorize, selected):
        authorize.return_value = {'connection_id': self.connection}
        selected.return_value = self.asset
        db = Database({'id': self.video})
        item, connection = subject._item(db, object(), self.company, self.item)
        self.assertEqual((item, connection), (self.asset, self.connection))
        selected.assert_called_once_with(db, self.connection, self.company, self.item)
        self.assertIn('meta_connection_id=%s', db.calls[0][0])
        self.assertEqual(db.calls[0][1], (self.video, self.connection, library.ANALYSIS_VERSION))
        authorize.side_effect = HTTPException(403, 'denied')
        with self.assertRaises(HTTPException) as failure:
            subject._item(Database({'id': self.video}), object(), uuid4(), self.item)
        self.assertEqual(failure.exception.status_code, 403)

    @patch.object(subject.ownership, '_selected')
    @patch.object(subject, 'authorize')
    def test_unanalysed_and_ad_assets_fail_closed(self, authorize, selected):
        authorize.return_value = {'connection_id': self.connection}
        for updates in ({'analysis_state': 'processing'}, {'analysis_version': library.ANALYSIS_VERSION + 1},
                        {'content_type': 'ad'}, {'video_id': None}):
            selected.return_value = {**self.asset, **updates}
            with self.subTest(updates=updates), self.assertRaises(HTTPException) as failure:
                subject._item(Database({'id': self.video}), object(), self.company, self.item)
            self.assertEqual(failure.exception.status_code, 404)

    @patch.object(subject.ownership, 'performance')
    @patch.object(subject.ownership, 'analysis')
    @patch.object(subject, '_item')
    def test_safe_projection_of_stored_evidence_and_organic_metrics(self, selected, analysis, performance):
        selected.return_value = (self.asset, self.connection)
        analysis.return_value = {
            'video': {'duration_seconds': 5, 'width': 1080, 'height': 1920, 'source_url': 'SECRET'},
            'scenes': [{'scene_number': 1, 'start_seconds': 0, 'end_seconds': 5, 'private': 'SECRET'}],
            'transcript_segments': [{'start_seconds': .2, 'end_seconds': 1, 'text': 'Hello', 'private': 'SECRET'}],
            'on_screen_text': [{'appearance_timestamp_seconds': .4, 'disappearance_timestamp_seconds': 1.2,
                                'text': 'Offer', 'confidence': .9, 'bounding_box': 'SECRET'}],
            'motion_events': [{'start_seconds': .5, 'end_seconds': 2, 'type': 'camera_pan', 'confidence': .8,
                               'internal_error': 'SECRET'}]}
        performance.return_value = [{'item_id': self.item, 'attribution': 'organic',
            'snapshot': {'performance_source': 'instagram', 'performance_metrics':
                         {'view_count': 8, 'like_count': None, 'reach': 12, 'provider_url': 'SECRET'}}}]
        db = Database({'status': 'connected', 'expires_at': datetime.now(timezone.utc) + timedelta(hours=1)})
        result = subject.detail(db, object(), self.company, self.item)
        self.assertEqual(result['item']['display_title'], 'Instagram reel')
        self.assertEqual(result['scenes'][0]['scene_number'], 1)
        self.assertEqual(result['transcript'][0]['text'], 'Hello')
        self.assertEqual(result['ocr'][0]['text'], 'Offer')
        self.assertEqual(result['motion'][0]['type'], 'camera_pan')
        self.assertEqual(result['performance'], {'view_count': 8, 'reach': 12})
        self.assertNotIn('SECRET', json.dumps(result, default=str))
