from contextlib import contextmanager
from copy import deepcopy
import hashlib
import hmac
import os
import unittest
from unittest.mock import patch
from uuid import UUID

import httpx
import psycopg

from app import facebook, meta
from app.video_repository import PerformanceSourceConflict
from test_instagram_api import authenticated_api
from test_meta_api import CONFIG, TOKEN

VIDEO_ID = UUID('8db7e284-353b-4f3e-9bf0-44d78d888720')
MEDIA_ID = '1234567890'
PAGE_ID = '2345678901'
PAGE_TOKEN = 'test-page-token'
MEDIA = {'id': MEDIA_ID, 'from': {'id': PAGE_ID}}
COUNTS = {'view_count': 120, 'like_count': 12, 'comment_count': 0, 'share_count': 2}
SNAPSHOT = {'performance_source': 'facebook', 'performance_metrics': COUNTS}


def insights(values=None, kind='reels'):
    if values is None:
        values = ({'fb_reels_total_plays': 120,
                   'post_video_likes_by_reaction_type': {'REACTION_LIKE': 12, 'REACTION_LOVE': 7},
                   'post_video_social_actions': {'COMMENT': 0, 'SHARE': 2}} if kind == 'reels' else
                  {'total_video_views': 120, 'total_video_reactions_by_type_total': {'like': 12, 'love': 7},
                   'total_video_stories_by_action_type': {'comment': 0, 'share': 2}})
    return {'data': [
        {'name': name, 'period': 'lifetime', 'values': [{'value': value}],
         'id': f'{MEDIA_ID}/video_insights/{name}/lifetime'} for name, value in values.items()
    ]}


def attach(api, video_id=VIDEO_ID, kind='reels'):
    return api.post(f'/api/meta/facebook/{kind}/{MEDIA_ID}/metrics',
                    json={'video_id': str(video_id), 'page_id': PAGE_ID})


@contextmanager
def graph_transport(media=None, metrics=None, error=None, pages=None, kind='reels'):
    requests = []
    original = httpx.Client
    def respond(request):
        requests.append(request)
        if error is not None:
            return httpx.Response(400, json={'error': error})
        if request.url.path == '/v26.0/me/accounts':
            if pages is not None:
                payload = pages[1 if request.url.params.get('after') else 0]
            else:
                payload = {'data': [{'id': PAGE_ID, 'access_token': PAGE_TOKEN, 'tasks': ['ANALYZE']}]}
            return httpx.Response(200, json=payload)
        if request.url.path == f'/v26.0/{MEDIA_ID}':
            return httpx.Response(200, json=MEDIA if media is None else media)
        if request.url.path == f'/v26.0/{MEDIA_ID}/video_insights':
            return httpx.Response(200, json=insights(kind=kind) if metrics is None else metrics)
        raise AssertionError(f'Unexpected Graph path: {request.url.path}')
    with patch('app.meta.httpx.Client', side_effect=lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs,
    )):
        yield requests


@patch.dict(os.environ, CONFIG)
class FacebookAPITests(unittest.TestCase):
    def setUp(self):
        meta._sessions.clear()
        self.api = authenticated_api()

    def tearDown(self):
        meta._sessions.clear()

    def test_video_and_reel_attach_to_exact_uuid_using_page_token(self):
        for kind in ('videos', 'reels'):
            with self.subTest(kind=kind), patch('app.facebook_routes.get_analysis', return_value={}) as read, \
                 patch('app.facebook_routes.save_performance', return_value=True) as save, \
                 graph_transport(kind=kind) as requests:
                response = attach(self.api, kind=kind)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {'video_id': str(VIDEO_ID), **SNAPSHOT})
            read.assert_called_once_with(VIDEO_ID)
            save.assert_called_once_with(VIDEO_ID, SNAPSHOT)
            self.assertEqual(len(requests), 3)
            self.assertEqual(requests[0].url.params['fields'], 'id,access_token,tasks')
            self.assertEqual(requests[1].url.params['fields'], 'id,from')
            self.assertEqual(requests[2].url.params['metric'], ','.join(facebook.METRICS[kind]))
            self.assertEqual(requests[2].url.params['period'], 'lifetime')
            for request, token in zip(requests, (TOKEN, PAGE_TOKEN, PAGE_TOKEN)):
                self.assertEqual(request.headers['authorization'], f'Bearer {token}')
                self.assertEqual(request.url.params['appsecret_proof'], hmac.new(
                    CONFIG['META_APP_SECRET'].encode(), token.encode(), hashlib.sha256).hexdigest())
                self.assertNotIn(token, str(request.url))
                self.assertNotIn(token, response.text)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_null_and_zero_in_scalar_and_breakdown_metrics(self):
        for kind, values in (
            ('reels', {'fb_reels_total_plays': 0, 'post_video_likes_by_reaction_type': {},
                       'post_video_social_actions': {'COMMENT': None}}),
            ('videos', {'total_video_views': 0, 'total_video_reactions_by_type_total': None}),
        ):
            with graph_transport(metrics=insights(values)):
                result = facebook.video_performance(meta.session_client(self.api.cookies.get(meta.SESSION_COOKIE)),
                                                    PAGE_ID, MEDIA_ID, kind)
            self.assertEqual(result['performance_metrics'], {
                'view_count': 0, 'like_count': None, 'comment_count': None, 'share_count': None})

    def test_paginates_pages_without_following_provider_urls(self):
        pages = [{'data': [], 'paging': {'next': 'https://untrusted.invalid/?access_token=secret',
                                        'cursors': {'after': 'cursor'}}},
                 {'data': [{'id': PAGE_ID, 'access_token': PAGE_TOKEN, 'tasks': ['ANALYZE']}]}]
        with graph_transport(pages=pages) as requests:
            facebook.video_performance(meta.session_client(self.api.cookies.get(meta.SESSION_COOKIE)),
                                       PAGE_ID, MEDIA_ID, 'reels')
        self.assertEqual(len(requests), 4)
        self.assertEqual(requests[1].url.params['after'], 'cursor')
        self.assertTrue(all(r.url.host == 'graph.facebook.com' for r in requests))

    def test_page_access_and_ownership_failures_never_save(self):
        for options, status in (
            ({'pages': [{'data': []}]}, 403),
            ({'pages': [{'data': [{'id': PAGE_ID, 'tasks': ['ADVERTISE']}]}]}, 403),
            ({'pages': [{'data': [{'id': PAGE_ID, 'tasks': ['ANALYZE'], 'access_token': ''}]}]}, 502),
            ({'pages': [{'data': [], 'paging': {'next': 'url', 'cursors': {'after': 'same'}}}] * 2}, 502),
            ({'media': {'id': MEDIA_ID, 'from': {'id': '999'}}}, 422),
            ({'media': {'id': MEDIA_ID}}, 422),
            ({'media': {**MEDIA, 'id': '999'}}, 502),
        ):
            with self.subTest(options=options), patch('app.facebook_routes.get_analysis', return_value={}), \
                 patch('app.facebook_routes.save_performance') as save, graph_transport(**options):
                self.assertEqual(attach(self.api).status_code, status)
                save.assert_not_called()

    def test_unavailable_and_malformed_metrics_never_replace_snapshot(self):
        cases = [({'data': []}, 422), (insights({'fb_reels_total_plays': None}), 422),
                 ({'data': None}, 502), ({'data': [None]}, 502)]
        for value in (-1, True, '120', 2**63, 1.5):
            cases.append((insights({'fb_reels_total_plays': value}), 502))
            cases.append((insights({'post_video_social_actions': {'COMMENT': value}}), 502))
        cases.append((insights({'post_video_social_actions': 5}), 502))
        duplicate = insights()
        duplicate['data'].append(deepcopy(duplicate['data'][0]))
        cases.append((duplicate, 502))
        for key, value in (('id', '999/video_insights/fb_reels_total_plays/lifetime'),
                           ('period', 'day'), ('values', [{'value': 1}, {'value': 2}])):
            payload = insights({'fb_reels_total_plays': 1})
            payload['data'][0][key] = value
            cases.append((payload, 502))
        for payload, status in cases:
            with self.subTest(payload=payload), patch('app.facebook_routes.get_analysis', return_value=SNAPSHOT), \
                 patch('app.facebook_routes.save_performance') as save, graph_transport(metrics=payload):
                self.assertEqual(attach(self.api).status_code, status)
                save.assert_not_called()

    def test_session_provider_and_database_errors(self):
        for code, status in ((190, 401), (10, 403), (100, 502), (200, 403), (4, 502)):
            self.api = authenticated_api()
            with patch('app.facebook_routes.get_analysis', return_value={}), \
                 patch('app.facebook_routes.save_performance') as save, \
                 graph_transport(error={'code': code, 'message': PAGE_TOKEN}):
                response = attach(self.api)
                self.assertEqual(response.status_code, status)
                self.assertNotIn(PAGE_TOKEN, response.text)
                save.assert_not_called()
        meta._sessions.clear()
        self.assertEqual(attach(self.api).status_code, 401)
        self.api = authenticated_api()
        for result, error, status in ((False, None, 404), (True, PerformanceSourceConflict(), 409),
                                     (True, psycopg.OperationalError('private'), 503)):
            with patch('app.facebook_routes.get_analysis', return_value={}), graph_transport(), \
                 patch('app.facebook_routes.save_performance', return_value=result, side_effect=error):
                self.assertEqual(attach(self.api).status_code, status)

    def test_unknown_uuid_and_conflicting_sources_do_not_fetch(self):
        for analysis, status in ((None, 404), ({'performance_source': 'instagram'}, 409),
                                 ({'performance_source': 'tiktok'}, 409)):
            with patch('app.facebook_routes.get_analysis', return_value=analysis), \
                 patch('app.facebook.video_performance') as fetch:
                self.assertEqual(attach(self.api).status_code, status)
                fetch.assert_not_called()

    def test_invalid_inputs_do_not_read_or_fetch(self):
        with patch('app.facebook_routes.get_analysis') as read:
            self.assertEqual(attach(self.api, 'bad-uuid').status_code, 422)
            self.assertEqual(attach(self.api, kind='ads').status_code, 422)
            for path, body in (
                (f'reels/{MEDIA_ID}', {'video_id': str(VIDEO_ID), 'page_id': 'bad'}),
                ('videos/shortcode', {'video_id': str(VIDEO_ID), 'page_id': PAGE_ID}),
                (f'reels/{MEDIA_ID}', {'video_id': str(VIDEO_ID), 'page_id': PAGE_ID, 'access_token': 'x'}),
            ):
                self.assertEqual(self.api.post('/api/meta/facebook/' + path + '/metrics', json=body).status_code, 422)
            read.assert_not_called()
