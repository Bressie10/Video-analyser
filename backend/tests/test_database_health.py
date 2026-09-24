import os
import unittest
from unittest.mock import MagicMock, patch

import psycopg
from fastapi import HTTPException

from app.main import database_health_check


class DatabaseHealthCheckTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_database_url_returns_503(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            database_health_check()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Database is not configured.")

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://test:test@localhost/test"})
    @patch("app.main.psycopg.connect")
    def test_successful_query_returns_ok(self, connect: MagicMock) -> None:
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value

        response = database_health_check()

        self.assertEqual(response, {"status": "ok"})
        connect.assert_called_once_with(os.environ["DATABASE_URL"], connect_timeout=3)
        cursor.execute.assert_called_once_with("SELECT 1")

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql://test:test@localhost/test"})
    @patch("app.main.psycopg.connect", side_effect=psycopg.OperationalError("test failure"))
    def test_connection_failure_returns_503(self, connect: MagicMock) -> None:
        with self.assertRaises(HTTPException) as raised:
            database_health_check()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Database is unavailable.")
        connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
