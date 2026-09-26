import unittest
from unittest.mock import patch

import httpx

from app import tiktok
from app.performance import performance_snapshot


class PerformanceTests(unittest.TestCase):
    def test_sources_share_one_contract_with_unknown_and_zero_counts(self):
        for source in ("tiktok", "instagram", "facebook", "meta_ads"):
            with self.subTest(source=source):
                self.assertEqual(performance_snapshot(source, {"view_count": 0, "secret": "ignored"}), {
                    "performance_source": source,
                    "performance_metrics": {
                        "view_count": 0, "like_count": None, "comment_count": None, "share_count": None,
                    },
                })

    def test_invalid_counts_and_unknown_source_are_rejected(self):
        for value in (-1, True, 1.5, "12", 2**63, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                performance_snapshot("instagram", {"view_count": value})
        with self.assertRaises(ValueError):
            performance_snapshot("unknown", {"view_count": 1})

    def test_tiktok_adapter_handles_partial_and_invalid_responses(self):
        original_client = httpx.Client
        for value in (0, None, -1, True, "1", 2**63):
            with self.subTest(value=value):
                transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
                    "error": {"code": "ok"},
                    "data": {"videos": [{"id": "123", "view_count": value}]},
                }))
                with patch("app.tiktok.httpx.Client", side_effect=lambda **kwargs: original_client(
                    transport=transport, **kwargs,
                )):
                    if type(value) is int and value == 0:
                        snapshot = tiktok.video_performance("token", "123")
                        self.assertEqual(snapshot, performance_snapshot("tiktok", {"view_count": 0}))
                    else:
                        with self.assertRaises(tiktok.TikTokError):
                            tiktok.video_performance("token", "123")
