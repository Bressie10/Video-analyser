from contextlib import contextmanager
from datetime import date
import json
import os
import unittest
from unittest.mock import patch
from uuid import UUID

import httpx
import psycopg

from app import meta, meta_ads
from app.performance import performance_snapshot
from app.video_repository import PerformanceSourceConflict
from test_instagram_api import authenticated_api
from test_meta_api import CONFIG, TOKEN

VIDEO_ID = UUID('8db7e284-353b-4f3e-9bf0-44d78d888720')
AD_ID = '123456789012345'
AD = {'id': AD_ID, 'account_id': '987654321'}
DATES = {'since': '2026-09-01', 'until': '2026-09-20'}
ROW = {
    'ad_id': AD_ID, 'account_id': AD['account_id'], 'account_currency': 'EUR',
    'date_start': DATES['since'], 'date_stop': DATES['until'],
    'impressions': '1200', 'reach': '900', 'clicks': '24', 'spend': '12.3400', 'ctr': '2', 'cpc': '0.514167',
    'actions': [{'action_type': 'video_view', 'value': '300'},
                {'action_type': 'offsite_conversion.fb_pixel_purchase', 'value': '2.5', '7d_click': '2', '1d_view': '0.5'},
                {'action_type': 'post_reaction', 'value': '15'}],
    'conversions': [{'action_type': 'purchase', 'value': '2.5'}],
    'video_play_actions': [{'action_type': 'video_view', 'value': '450'}],
}
CONTEXT = {'action_report_time': 'impression', 'action_attribution_windows': ['7d_click', '1d_view']}


def attach(api, video_id=VIDEO_ID, **dates):
    return api.post(f'/api/meta/ads/{AD_ID}/metrics', json={'video_id': str(video_id), **DATES, **dates})


@contextmanager
def graph_transport(row=None, payload=None, ad=None, error=None):
    original = httpx.Client
    requests = []
    def respond(request):
        requests.append(request)
        if error is not None:
            return httpx.Response(400, json={'error': error})
        if request.url.path == f'/v26.0/{AD_ID}':
            return httpx.Response(200, json=AD if ad is None else ad)
        if request.url.path == f'/v26.0/{AD_ID}/insights':
            return httpx.Response(200, json=payload if payload is not None else {'data': [ROW if row is None else row]})
        raise AssertionError(f'Unexpected Graph path {request.url.path}')
    with patch('app.meta.httpx.Client', side_effect=lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs,
    )):
        yield requests


@patch.dict(os.environ, CONFIG)
class MetaAdsTests(unittest.TestCase):
    def setUp(self):
        self.api = authenticated_api()

    def tearDown(self):
        meta._sessions.clear()

    def test_ad_identification_fields_attribution_and_exact_uuid(self):
        with patch('app.meta_ads_routes.get_analysis', return_value={}) as read, \
             patch('app.meta_ads_routes.save_performance', return_value=True) as save, graph_transport() as requests:
            response = attach(self.api)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['performance_source'], 'meta_ads')
        self.assertEqual(result['video_id'], str(VIDEO_ID))
        counts = result['performance_metrics']
        self.assertEqual(counts['view_count'], 300)
        self.assertIsNone(counts['like_count'])  # Reactions are not likes.
        self.assertIsNone(counts['comment_count'])
        details = counts['meta_ads']
        self.assertEqual(details['impressions'], 1200)
        self.assertEqual(details['spend'], '12.3400')
        self.assertEqual(details['ctr'], '2')
        self.assertEqual(details['cpc'], '0.514167')
        self.assertEqual(details['conversions'][0]['value'], '2.5')
        self.assertEqual(details['actions'][1]['1d_view'], '0.5')
        self.assertEqual(details['video_play_actions'][0]['value'], '450')
        for key in ('ad_id', 'account_id', 'access_token'):
            self.assertNotIn(key, details)
        read.assert_called_once_with(VIDEO_ID)
        save.assert_called_once_with(VIDEO_ID, {k: result[k] for k in ('performance_source', 'performance_metrics')})
        self.assertEqual(requests[0].url.params['fields'], 'id,account_id')
        query = requests[1].url.params
        self.assertEqual(set(query['fields'].split(',')), set(meta_ads.FIELDS))
        self.assertEqual(json.loads(query['time_range']), DATES)
        self.assertEqual(json.loads(query['action_attribution_windows']), ['7d_click', '1d_view'])
        self.assertEqual(query['action_report_time'], 'impression')
        self.assertEqual(query['level'], 'ad')
        self.assertEqual(query['time_increment'], 'all_days')
        self.assertNotIn('breakdowns', query)  # Do not sum reach/rates across placements.
        for request in requests:
            self.assertEqual(request.headers['authorization'], 'Bearer ' + TOKEN)
            self.assertNotIn(TOKEN, str(request.url))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_non_video_ad_and_partial_metrics_preserve_null_and_zero(self):
        for metric in ({'spend': '0.00'}, {'impressions': '0'}, {'conversions': [{'action_type': 'purchase', '1d_view': '0'}]}):
            row = {k: ROW[k] for k in ('ad_id', 'account_id', 'date_start', 'date_stop')}
            row.update(metric)
            with graph_transport(row=row):
                snapshot = meta_ads.ad_performance(meta.session_client(self.api.cookies.get(meta.SESSION_COOKIE)),
                                                   AD_ID, date.fromisoformat(DATES['since']), date.fromisoformat(DATES['until']))
            self.assertIsNone(snapshot['performance_metrics']['view_count'])
            details = snapshot['performance_metrics']['meta_ads']
            self.assertIsNone(details['clicks'])
            self.assertIsNone(details['actions'])
            self.assertIsNone(details['account_currency'])
            self.assertEqual(details['spend'], metric.get('spend'))

    def test_common_contract_validates_extended_data_and_legacy_shapes(self):
        details = {**ROW, **CONTEXT, 'access_token': 'must-not-persist'}
        snapshot = performance_snapshot('meta_ads', {'meta_ads': details})
        self.assertNotIn('access_token', snapshot['performance_metrics']['meta_ads'])
        for source in ('instagram', 'facebook', 'tiktok'):
            with self.assertRaises(ValueError):
                performance_snapshot(source, {'view_count': 1, 'meta_ads': details})
        self.assertEqual(set(performance_snapshot('meta_ads', {'view_count': 0})['performance_metrics']),
                         {'view_count', 'like_count', 'comment_count', 'share_count'})

    def test_malformed_metrics_identity_and_reporting_range_never_save(self):
        cases = [dict(ROW, **{field: bad}) for field in ('impressions', 'clicks')
                 for bad in ('1.2', '-1', True, 'NaN', str(2**63))]
        cases += [dict(ROW, spend=bad) for bad in ('-1', 'Infinity', 'NaN', True, {}, '9'*61)]
        cases += [dict(ROW, **{field: 'wrong'}) for field in ('ad_id', 'account_id', 'date_start', 'account_currency')]
        cases += [dict(ROW, actions=value) for value in ({}, [None], [{'value': '2'}],
                  [{'action_type': 'x', 'value': 'bad'}], [{'action_type': 'x'}, {'action_type': 'x'}])]
        for row in cases:
            with self.subTest(row=row), patch('app.meta_ads_routes.get_analysis', return_value={}), \
                 patch('app.meta_ads_routes.save_performance') as save, graph_transport(row=row):
                self.assertEqual(attach(self.api).status_code, 502)
                save.assert_not_called()
        with patch('app.meta_ads_routes.get_analysis', return_value={}), \
             patch('app.meta_ads_routes.save_performance') as save, graph_transport(ad={**AD, 'id': '999'}) as requests:
            self.assertEqual(attach(self.api).status_code, 502)
            self.assertEqual(len(requests), 1)
            save.assert_not_called()

    def test_empty_reports_and_extra_rows_are_not_zero_snapshots(self):
        empty = {key: ROW[key] for key in ('ad_id', 'account_id', 'date_start', 'date_stop')}
        for payload, status in (({'data': []}, 422), ({'data': [empty]}, 422),
                                ({'data': [ROW, ROW]}, 502), ({'data': None}, 502),
                                ({'data': [ROW], 'paging': {'next': 'https://untrusted.invalid'}}, 502)):
            with self.subTest(payload=payload), patch('app.meta_ads_routes.get_analysis', return_value={}), \
                 patch('app.meta_ads_routes.save_performance') as save, graph_transport(payload=payload):
                self.assertEqual(attach(self.api).status_code, status)
                save.assert_not_called()

    def test_provider_errors_and_missing_session_are_safe(self):
        for code, status in ((190, 401), (10, 403), (200, 403), (4, 502), (100, 502)):
            self.api = authenticated_api()
            with patch('app.meta_ads_routes.get_analysis', return_value={}), \
                 patch('app.meta_ads_routes.save_performance') as save, graph_transport(error={'code': code, 'message': TOKEN}):
                response = attach(self.api)
                self.assertEqual(response.status_code, status)
                self.assertNotIn(TOKEN, response.text)
                save.assert_not_called()
        meta._sessions.clear()
        self.assertEqual(attach(self.api).status_code, 401)

    def test_invalid_request_unknown_uuid_and_source_conflicts(self):
        with patch('app.meta_ads_routes.get_analysis') as read:
            self.assertEqual(attach(self.api, 'bad-uuid').status_code, 422)
            self.assertEqual(attach(self.api, since='bad-date').status_code, 422)
            self.assertEqual(attach(self.api, since='2026-10-01').status_code, 422)
            self.assertEqual(self.api.post('/api/meta/ads/not-an-id/metrics', json={
                'video_id': str(VIDEO_ID), **DATES}).status_code, 422)
            read.assert_not_called()
        for analysis, status in ((None, 404), ({'performance_source': 'facebook'}, 409),
                                 ({'performance_source': 'instagram'}, 409)):
            with patch('app.meta_ads_routes.get_analysis', return_value=analysis), \
                 patch('app.meta_ads.ad_performance') as fetch:
                self.assertEqual(attach(self.api).status_code, status)
                fetch.assert_not_called()

    def test_database_failure_and_concurrent_change(self):
        for result, error, status in ((False, None, 404), (True, PerformanceSourceConflict(), 409),
                                     (True, psycopg.OperationalError('private-db'), 503)):
            with patch('app.meta_ads_routes.get_analysis', return_value={}), graph_transport(), \
                 patch('app.meta_ads_routes.save_performance', return_value=result, side_effect=error):
                response = attach(self.api)
                self.assertEqual(response.status_code, status)
                self.assertNotIn('private-db', response.text)
