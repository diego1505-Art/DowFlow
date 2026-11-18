import os
import unittest
from unittest.mock import patch

from app import app


class ElectronDesktopTokenTests(unittest.TestCase):
    def setUp(self):
        self.token_patch = patch.dict(
            os.environ,
            {"DOWFLOW_DESKTOP_TOKEN": "test-electron-token"},
        )
        self.token_patch.start()
        self.client = app.test_client()

    def tearDown(self):
        self.token_patch.stop()

    def test_health_check_rejects_missing_token(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 403)

    def test_health_check_rejects_incorrect_token(self):
        response = self.client.get(
            "/api/status",
            headers={"X-DowFlow-Desktop": "not-the-token"},
        )
        self.assertEqual(response.status_code, 403)

    def test_health_check_accepts_the_current_launch_token(self):
        response = self.client.get(
            "/api/status",
            headers={"X-DowFlow-Desktop": "test-electron-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ready"])


if __name__ == "__main__":
    unittest.main()
