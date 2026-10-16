"""Stage callbacks follow real analysis operations and remain optional."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.analysis_pipeline import analyze_file
from app.meta_media import MediaUnavailable, preview_bytes, preview_url


class ContentAnalysisStageTests(unittest.TestCase):
    def test_stage_order_with_audio(self):
        stages = []
        metadata = SimpleNamespace(audio={'codec': 'aac'}, as_dict=lambda: {'audio': {'codec': 'aac'}})
        ops = {
            'inspect_video': lambda *_args, **_kwargs: metadata,
            'normalise_video': lambda *_args: None,
            'detect_scenes': lambda *_args: [],
            'detect_on_screen_text': lambda *_args: [],
            'detect_motion_events': lambda *_args: [],
            'extract_wav_audio': lambda *_args: None,
            'transcribe_audio': lambda *_args: {'text': '', 'segments': []},
        }
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_file(Path(directory, 'source.mp4'), directory,
                                  operations=ops, on_stage=stages.append)
        self.assertEqual(stages, ['inspecting', 'normalizing', 'detecting_scenes',
                                  'reading_text', 'detecting_motion',
                                  'extracting_audio', 'transcribing'])
        self.assertEqual(result['audio']['segments'], [])

    def test_callback_is_optional_for_silent_video(self):
        metadata = SimpleNamespace(audio={'codec': None}, as_dict=lambda: {'audio': {'codec': None}})
        ops = {
            'inspect_video': lambda *_args, **_kwargs: metadata,
            'normalise_video': lambda *_args: None,
            'detect_scenes': lambda *_args: [],
            'detect_on_screen_text': lambda *_args: [],
            'detect_motion_events': lambda *_args: [],
        }
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(analyze_file(Path(directory, 'source.mp4'), directory,
                                          operations=ops)['audio']['segments'], [])

    def test_preview_never_follows_untrusted_redirect_or_large_body(self):
        original = httpx.Client
        for response in (httpx.Response(302, headers={'location': 'https://evil.invalid/secret'}),
                         httpx.Response(200, headers={'content-type': 'image/jpeg',
                                                      'content-length': str(6 * 1024 * 1024)})):
            with patch('app.meta_media.socket.getaddrinfo',
                       return_value=[(0, 0, 0, '', ('8.8.8.8', 443))]), \
                 patch('app.meta_media.httpx.Client',
                       side_effect=lambda **kw: original(
                           transport=httpx.MockTransport(lambda _request: response), **kw)):
                with self.assertRaises(MediaUnavailable):
                    preview_bytes('https://x.fbcdn.net/thumbnail')

    def test_provider_thumbnail_fields_and_owner(self):
        class Provider:
            def __init__(self):
                self.calls = []
            def for_page(self, page):
                self.calls.append(('page', page))
                return self
            def get(self, media, params):
                self.calls.append((media, params['fields']))
                return {'id': media, 'media_type': 'VIDEO',
                        'thumbnail_url': 'https://x.cdninstagram.com/thumb',
                        'picture': 'https://x.fbcdn.net/thumb', 'from': {'id': '9'}}
        client = Provider()
        self.assertEqual(preview_url(client, {'platform': 'instagram', 'external_id': '1'}),
                         'https://x.cdninstagram.com/thumb')
        self.assertEqual(preview_url(client, {'platform': 'facebook', 'external_id': '2',
                                              'account_external_id': '9'}),
                         'https://x.fbcdn.net/thumb')
        self.assertIn(('1', 'id,media_type,thumbnail_url'), client.calls)
        self.assertIn(('2', 'id,from,picture'), client.calls)
        with self.assertRaises(MediaUnavailable):
            preview_url(client, {'platform': 'facebook', 'external_id': '2',
                                 'account_external_id': '8'})
