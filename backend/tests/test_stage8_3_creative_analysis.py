"""Company boundary, response allowlist, and seekable media checks."""

from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from app import creative_analysis as subject
from app.creative_analysis_routes import _open_media
from app.meta_media import MediaUnavailable
from app.meta_media import media_url, validate_url
from app import meta


class Query:
    def __init__(self, rows):
        self.rows = rows
    def fetchall(self):
        return self.rows


class Database:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ''
        self.params = None
    def execute(self, sql, params):
        self.sql, self.params = sql, params
        return Query(self.rows)


class CreativeBoundaryTests(TestCase):
    def setUp(self):
        self.company = uuid4()
        self.creative = uuid4()
        self.connection = uuid4()
        self.asset = {'id': self.creative, 'video_id': uuid4(), 'analysis_state': 'completed',
                      'connection_id': self.connection, 'ad_label': 'Offer video',
                      'status': 'connected', 'expires_at': datetime.now(timezone.utc) + timedelta(hours=1),
                      'token_ciphertext': 'SECRET', 'external_id': 'PROVIDER_VIDEO'}

    @patch.object(subject, 'authorize')
    def test_exact_asset_and_company_edge_required(self, authorize):
        authorize.return_value = {'connection_id': self.connection}
        db = Database([self.asset])
        asset, label = subject.authorized_asset(db, object(), self.company, self.creative)
        self.assertEqual(asset['id'], self.creative)
        self.assertEqual(label, 'Offer video')
        self.assertIn('company_ad_assignments', db.sql)
        self.assertIn('meta_ad_assets', db.sql)
        self.assertIn('asset.id=%s', db.sql)
        self.assertEqual(db.params, (self.company, self.creative, self.connection))
        with self.assertRaises(HTTPException) as failure:
            subject.authorized_asset(Database([]), object(), self.company, uuid4())
        self.assertEqual(failure.exception.status_code, 404)

    @patch.object(subject, 'authorize')
    def test_cross_company_membership_denial_precedes_asset_query(self, authorize):
        authorize.side_effect = HTTPException(403, 'Company access denied.')
        db = Database([self.asset])
        with self.assertRaises(HTTPException) as failure:
            subject.authorized_asset(db, object(), uuid4(), self.creative)
        self.assertEqual(failure.exception.status_code, 403)
        self.assertEqual(db.sql, '')

    @patch.object(subject, 'read_analysis')
    @patch.object(subject, 'authorized_asset')
    def test_allowlist_and_disconnected_stored_evidence(self, authorized, read):
        authorized.return_value = ({**self.asset, 'status': 'disconnected'}, 'Offer video')
        read.return_value = {'metadata': {'duration_seconds': 12, 'video': {'resolution': {'width': 720, 'height': 1280},
                             'source_url': 'SECRET'}}, 'audio': {'segments': [{'start': 0.2, 'end': 1.1, 'text': 'Hello', 'prompt': 'SECRET'}]},
                             'scenes': [{'scene_number': 1, 'start_seconds': 0, 'end_seconds': 12, 'raw': 'SECRET'}],
                             'on_screen_text': [{'text': 'Offer', 'appearance_timestamp_seconds': .4,
                             'disappearance_timestamp_seconds': 1.2, 'bounding_box': [[0, 0], [100, 100]],
                             'provider_url': 'SECRET'}], 'motion_events': [{'type': 'SECRET'},
                             {'type': 'camera_pan', 'start_seconds': .5, 'end_seconds': 1.5, 'confidence': .8,
                              'private': 'SECRET'}]}
        result = subject.detail(object(), object(), self.company, self.creative)
        self.assertEqual(result['media'], {'state': 'unavailable'})
        self.assertEqual(result['transcript'][0]['text'], 'Hello')
        self.assertEqual(result['ocr'][0]['text'], 'Offer')
        self.assertEqual(result['motion'], [{'start_seconds': .5, 'end_seconds': 1.5,
                                           'type': 'camera_pan', 'confidence': .8}])
        self.assertNotIn('SECRET', str(result))
        self.assertNotIn('bounding_box', str(result))
        self.assertEqual(set(result), {'creative_ref', 'label', 'duration_seconds', 'resolution', 'scenes', 'transcript', 'ocr', 'motion', 'media'})

    @patch.object(subject, 'read_analysis', return_value=None)
    @patch.object(subject, 'authorized_asset')
    def test_missing_stored_analysis(self, authorized, read):
        authorized.return_value = (self.asset, 'Offer video')
        with self.assertRaises(HTTPException) as failure:
            subject.detail(object(), object(), self.company, self.creative)
        self.assertEqual(failure.exception.status_code, 404)


class Response:
    def __init__(self, status, headers):
        self.status_code, self.headers = status, headers
        self.closed = False
    def close(self): self.closed = True


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.closed = False
    def build_request(self, method, url, headers):
        self.requests.append((method, url, headers))
        return None
    def send(self, request, stream): return next(self.responses)
    def close(self): self.closed = True


class MediaTests(TestCase):
    @patch('app.meta_media.socket.getaddrinfo', return_value=[(0, 0, 0, '', ('8.8.8.8', 443))])
    def test_url_validation_rejects_non_provider_and_http(self, dns):
        for url in ('http://video.xx.fbcdn.net/movie', 'https://evil.example/movie',
                    'https://fbcdn.net.evil.example/movie', 'https://user@video.xx.fbcdn.net/movie'):
            with self.subTest(url=url), self.assertRaises(MediaUnavailable):
                validate_url(url)
        validate_url('https://video.xx.fbcdn.net/movie')

    def test_meta_identity_mismatch_blocks_media_location(self):
        class Provider:
            def get(self, external_id, fields):
                return {'id': 'wrong-video', 'source': 'https://video.xx.fbcdn.net/signed'}
        with self.assertRaises(meta.MetaError):
            media_url(Provider(), {'platform': 'facebook', 'account_external_id': 'page',
                                   'external_id': 'expected-video'})

    @patch('app.creative_analysis_routes.validate_url')
    @patch('app.creative_analysis_routes.httpx.Client')
    def test_range_headers_and_redirect_revalidated(self, client_factory, validate):
        first = Response(302, {'location': 'https://video.xx.fbcdn.net/next'})
        second = Response(206, {'content-type': 'video/mp4', 'content-length': '10', 'content-range': 'bytes 10-19/100'})
        client = Client([first, second]); client_factory.return_value = client
        _, upstream, headers = _open_media('https://video.xx.fbcdn.net/start', 'bytes=10-19')
        self.assertIs(upstream, second)
        self.assertEqual(headers['Content-Range'], 'bytes 10-19/100')
        self.assertEqual(headers['Cache-Control'], 'private, no-store')
        self.assertEqual(client.requests[0][2], {'Accept-Encoding': 'identity', 'Range': 'bytes=10-19'})
        self.assertEqual(validate.call_count, 2)
        self.assertTrue(first.closed)
        self.assertNotIn('Authorization', str(client.requests))

    @patch('app.creative_analysis_routes.validate_url')
    @patch('app.creative_analysis_routes.httpx.Client')
    def test_provider_and_limit_fail_closed(self, client_factory, validate):
        for status, headers in [(403, {}), (404, {}), (410, {}),
                                (200, {'content-type': 'video/mp4', 'content-length': '10'}),
                                (206, {'content-type': 'video/mp4', 'content-length': str(500 * 1024 * 1024 + 1),
                                       'content-range': 'bytes 0-9/100'})]:
            client_factory.return_value = Client([Response(status, headers)])
            with self.subTest(status=status), self.assertRaises(MediaUnavailable):
                _open_media('https://video.xx.fbcdn.net/start', 'bytes=0-9')

    @patch('app.creative_analysis_routes.validate_url', side_effect=MediaUnavailable('unsupported'))
    @patch('app.creative_analysis_routes.httpx.Client')
    def test_unsupported_location(self, client_factory, validate):
        client = Client([]); client_factory.return_value = client
        with self.assertRaises(MediaUnavailable):
            _open_media('https://other.example/media', None)
        self.assertTrue(client.closed)

    @patch('app.creative_analysis_routes.validate_url')
    @patch('app.creative_analysis_routes.httpx.Client')
    def test_mismatched_range_and_redirect_limit(self, client_factory, validate):
        client_factory.return_value = Client([Response(206, {'content-type': 'video/mp4',
            'content-length': '10', 'content-range': 'bytes 20-29/100'})])
        with self.assertRaises(MediaUnavailable):
            _open_media('https://video.xx.fbcdn.net/start', 'bytes=10-19')
        client_factory.return_value = Client([Response(302, {'location': '/next'}) for _ in range(4)])
        with self.assertRaises(MediaUnavailable):
            _open_media('https://video.xx.fbcdn.net/start', None)
        self.assertEqual(validate.call_count, 5)

    @patch('app.creative_analysis_routes.validate_url')
    @patch('app.creative_analysis_routes.httpx.Client')
    def test_range_end_must_be_inside_declared_total(self, client_factory, validate):
        response = Response(206, {'content-type': 'video/mp4',
            'content-length': '10', 'content-range': 'bytes 100-109/100'})
        client = Client([response]); client_factory.return_value = client
        with self.assertRaises(MediaUnavailable):
            _open_media('https://video.xx.fbcdn.net/start', 'bytes=100-109')
        self.assertTrue(response.closed)
        self.assertTrue(client.closed)
