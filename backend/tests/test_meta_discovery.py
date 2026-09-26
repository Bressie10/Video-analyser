from contextlib import contextmanager
import os
import unittest
from unittest.mock import patch

import httpx

from app import meta
from test_instagram_api import authenticated_api
from test_meta_api import CONFIG


@contextmanager
def graph(payloads):
    requests = []
    original = httpx.Client
    def respond(request):
        requests.append(request)
        path = request.url.path.removeprefix('/v26.0/')
        payload = payloads[path]
        return httpx.Response(400 if 'error' in payload else 200, json=payload)
    with patch('app.meta.httpx.Client', side_effect=lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs,
    )):
        yield requests


PAGES = {'data': [{'id': '123', 'name': 'Our bakery', 'access_token': 'private-page-token', 'tasks': ['ANALYZE']}]}
ACCOUNT = {'instagram_business_account': {'id': '234', 'username': 'bakery'}}


@patch.dict(os.environ, CONFIG)
class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.api = authenticated_api()

    def tearDown(self):
        meta._sessions.clear()

    def test_discovery_fields_tokens_and_no_insights(self):
        cases = [
            ('pages', 'me/accounts', PAGES, 'Our bakery'),
            ('pages/123/instagram-accounts', '123', ACCOUNT, 'bakery'),
            ('pages/123/facebook/reels', '123/video_reels', {'data': [{'id': '456', 'description': 'Fresh bread'}]}, 'Fresh bread'),
            ('pages/123/facebook/videos', '123/videos', {'data': [{'id': '456', 'title': 'Bread tutorial'}]}, 'Bread tutorial'),
            ('pages/123/instagram/234/media', '234/media', {'data': [{'id': '456', 'caption': 'Fresh bread', 'media_type': 'VIDEO', 'media_product_type': 'REELS'}]}, 'Fresh bread'),
            ('ad-accounts', 'me/adaccounts', {'data': [{'id': 'act_345', 'name': 'Bakery advertising'}]}, 'Bakery advertising'),
            ('ad-accounts/act_345/ads', 'act_345/ads', {'data': [{'id': '456', 'name': 'Weekend offer', 'effective_status': 'ACTIVE', 'creative': {'thumbnail_url': 'https://example.com/image.jpg', 'secret': 'hidden'}}]}, 'Weekend offer'),
        ]
        for endpoint, path, payload, label in cases:
            with self.subTest(endpoint=endpoint), graph({'me/accounts': PAGES, '123': ACCOUNT, path: payload}) as requests:
                response = self.api.get('/api/meta/discovery/' + endpoint)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['items'][0]['name'], label)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('private-page-token', response.text)
            self.assertNotIn('hidden', response.text)
            for request in requests:
                self.assertNotIn('insights', request.url.path)
                self.assertNotIn('metric', request.url.params)
                self.assertNotIn('access_token', request.url.params)
            if 'facebook/' in endpoint:
                self.assertEqual(requests[-1].headers['authorization'], 'Bearer private-page-token')

    def test_cursor_forwarded_without_provider_url_or_extra_fields(self):
        payload = {'data': [{'id': '123', 'name': 'Bakery', 'secret': 'hidden'}],
                   'paging': {'next': 'https://untrusted.invalid/?access_token=hidden', 'cursors': {'after': 'next'}}}
        with graph({'me/accounts': payload}) as requests:
            response = self.api.get('/api/meta/discovery/pages?after=previous')
        self.assertEqual(response.json()['next_cursor'], 'next')
        self.assertEqual(requests[0].url.params['after'], 'previous')
        self.assertEqual(requests[0].url.params['fields'], 'id,name')
        self.assertNotIn('hidden', response.text)

    def test_empty_lists_and_no_linked_instagram(self):
        for endpoint, path in [('pages', 'me/accounts'), ('ad-accounts', 'me/adaccounts'),
                               ('pages/123/facebook/reels', '123/video_reels'),
                               ('pages/123/instagram/234/media', '234/media'),
                               ('ad-accounts/act_345/ads', 'act_345/ads')]:
            with self.subTest(endpoint=endpoint), graph({'me/accounts': PAGES, '123': ACCOUNT, path: {'data': []}}):
                response = self.api.get('/api/meta/discovery/' + endpoint)
            self.assertEqual(response.json(), {'items': [], 'next_cursor': None})
        with graph({'me/accounts': PAGES, '123': {}}):
            self.assertEqual(self.api.get('/api/meta/discovery/pages/123/instagram-accounts').json()['items'], [])

    def test_permission_expired_and_provider_errors(self):
        for code, status in [(10, 403), (200, 403), (190, 401), (2, 502)]:
            self.api = authenticated_api()
            with graph({'me/accounts': {'error': {'code': code, 'message': 'private-provider-detail'}}}):
                response = self.api.get('/api/meta/discovery/pages')
            self.assertEqual(response.status_code, status)
            self.assertNotIn('private-provider-detail', response.text)

    def test_disconnected_and_inaccessible_accounts(self):
        meta._sessions.clear()
        self.assertEqual(self.api.get('/api/meta/discovery/pages').status_code, 401)
        self.api = authenticated_api()
        with graph({'me/accounts': {'data': []}}):
            self.assertEqual(self.api.get('/api/meta/discovery/pages/123/facebook/reels').status_code, 403)
        with graph({'me/accounts': PAGES, '123': ACCOUNT}) as requests:
            self.assertEqual(self.api.get('/api/meta/discovery/pages/123/instagram/999/media').status_code, 403)
        self.assertEqual(len(requests), 2)

    def test_non_reels_visible_but_not_selectable(self):
        with graph({'me/accounts': PAGES, '123': ACCOUNT, '234/media': {'data': [{'id': '456', 'media_type': 'IMAGE'}]}}):
            response = self.api.get('/api/meta/discovery/pages/123/instagram/234/media')
        self.assertFalse(response.json()['items'][0]['selectable'])

    def test_invalid_inputs_and_malformed_provider_data(self):
        self.assertEqual(self.api.get('/api/meta/discovery/pages/bad/facebook/reels').status_code, 422)
        self.assertEqual(self.api.get('/api/meta/discovery/ad-accounts/123/ads').status_code, 422)
        for payload in [{'data': None}, {'data': [None]}, {'data': [{'id': 'bad'}]},
                        {'data': [], 'paging': {'next': 'url'}},
                        {'data': [], 'paging': {'next': 'url', 'cursors': {'after': 'same'}}}]:
            with graph({'me/accounts': payload}):
                self.assertEqual(self.api.get('/api/meta/discovery/pages?after=same').status_code, 502)
