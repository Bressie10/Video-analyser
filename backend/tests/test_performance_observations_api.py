"""Mocked provider identity and authorization checks for the company writer."""

from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import meta
from app.main import app
from app.meta_auth_dependencies import require_meta_session
from test_instagram_api import authenticated_api
from test_meta_api import CONFIG
from test_meta_ads_api import AD_ID, AD, DATES, ROW, graph_transport


@patch.dict(os.environ, CONFIG)
class ObservationApiTests(unittest.TestCase):
    def setUp(self):
        from app.auth import AuthenticatedUser, require_authenticated_user
        from auth_fixtures import USER_ID
        app.dependency_overrides[require_authenticated_user] = lambda: AuthenticatedUser(USER_ID, "fixture@example.com")
        app.dependency_overrides[require_meta_session] = lambda: None
        self.addCleanup(lambda: app.dependency_overrides.pop(require_authenticated_user, None))
        self.addCleanup(lambda: app.dependency_overrides.pop(require_meta_session, None))
        self.addCleanup(meta._sessions.clear)
        self.api = authenticated_api()
        self.company, self.item = uuid4(), uuid4()

    def call(self):
        return self.api.post(f"/api/meta/ads/companies/{self.company}/items/{self.item}/metrics",
                             json=DATES)

    def test_verified_provider_identity_reaches_writer(self):
        client = meta.session_client(self.api.cookies.get(meta.SESSION_COOKIE))
        stored = {"id": uuid4(), "fetched_at": datetime.now(timezone.utc)}
        with patch("app.meta_ads_routes.library.session_connection", return_value={"id": uuid4()}), \
             patch("app.meta_ads_routes.library.connection_client", return_value=client), \
             patch("app.meta_ads_routes.observations.authorized_ad", return_value={"ad_id": AD_ID}) as authorize, \
             patch("app.meta_ads_routes.observations.save_meta_ad_observation", return_value=stored) as save, \
             graph_transport() as requests:
            response = self.call()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["observation_id"], str(stored["id"]))
        self.assertEqual(save.call_args.args[4], {"ad_id": AD_ID,
                         "account_id": AD["account_id"], "placement_scope": "meta_all_placements"})
        self.assertEqual(save.call_args.args[5]["performance_metrics"]["meta_ads"]["date_start"], DATES["since"])
        self.assertEqual([request.url.path for request in requests][-1], f"/v26.0/{AD_ID}/insights")
        authorize.assert_called_once()

    def test_provider_mismatch_and_authorization_fail_closed(self):
        client = meta.session_client(self.api.cookies.get(meta.SESSION_COOKIE))
        with patch("app.meta_ads_routes.library.session_connection", return_value={"id": uuid4()}), \
             patch("app.meta_ads_routes.library.connection_client", return_value=client), \
             patch("app.meta_ads_routes.observations.authorized_ad", return_value={"ad_id": AD_ID}), \
             patch("app.meta_ads_routes.observations.save_meta_ad_observation") as save, \
             graph_transport(row={**ROW, "account_id": "999"}):
            self.assertEqual(self.call().status_code, 502)
        save.assert_not_called()
        from app.performance_observation_repository import ObservationOwnershipError
        with patch("app.meta_ads_routes.library.session_connection", return_value={"id": uuid4()}), \
             patch("app.meta_ads_routes.observations.authorized_ad", side_effect=ObservationOwnershipError()) as authorize, \
             patch("app.meta_ads_routes.library.connection_client") as provider:
            self.assertEqual(self.call().status_code, 404)
        authorize.assert_called_once()
        provider.assert_not_called()
