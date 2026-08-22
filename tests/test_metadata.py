"""Tests for metadata database operations."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from metadata import (
    get_synced_asset_names,
    is_already_synced,
    update_release_entry,
    update_status,
)


class TestDuplicateDetection(unittest.TestCase):
    """Test that duplicate releases are properly detected."""

    def test_already_synced(self):
        db = {
            "example-app": {
                "source_release_id": 12345,
                "source_tag": "v1.0.0",
                "assets": [],
            }
        }
        self.assertTrue(is_already_synced(db, "example-app", 12345))

    def test_not_synced(self):
        db = {
            "example-app": {
                "source_release_id": 12345,
                "source_tag": "v1.0.0",
                "assets": [],
            }
        }
        self.assertFalse(is_already_synced(db, "example-app", 99999))

    def test_new_app(self):
        db = {}
        self.assertFalse(is_already_synced(db, "new-app", 12345))

    def test_same_release_different_app(self):
        db = {
            "app-a": {"source_release_id": 12345, "assets": []},
        }
        self.assertFalse(is_already_synced(db, "app-b", 12345))


class TestAssetTracking(unittest.TestCase):
    def test_get_synced_assets(self):
        db = {
            "app": {
                "assets": [
                    {"filename": "app-universal.apk"},
                    {"filename": "app-arm64.apk"},
                ]
            }
        }
        names = get_synced_asset_names(db, "app")
        self.assertEqual(names, {"app-universal.apk", "app-arm64.apk"})

    def test_empty_app(self):
        names = get_synced_asset_names({}, "nonexistent")
        self.assertEqual(names, set())


class TestUpdateEntry(unittest.TestCase):
    def test_new_entry(self):
        db = {}
        update_release_entry(
            db, "test", "owner/repo", 123, "v1.0", "2026-01-01T00:00:00Z",
            [{"filename": "app.apk", "sha256": "abc"}], "test-v1.0",
        )
        self.assertIn("test", db)
        self.assertEqual(db["test"]["source_release_id"], 123)
        self.assertEqual(len(db["test"]["assets"]), 1)

    def test_update_same_release(self):
        """Adding assets to an existing release should merge."""
        db = {
            "test": {
                "source_release_id": 123,
                "assets": [{"filename": "app-a.apk", "sha256": "aaa"}],
            }
        }
        update_release_entry(
            db, "test", "owner/repo", 123, "v1.0", "2026-01-01T00:00:00Z",
            [{"filename": "app-b.apk", "sha256": "bbb"}], "test-v1.0",
        )
        self.assertEqual(len(db["test"]["assets"]), 2)


class TestStatus(unittest.TestCase):
    def test_synced_status(self):
        db = {}
        update_status(db, "app", "synced", latest_version="v1.0")
        self.assertEqual(db["app"]["status"], "synced")
        self.assertIn("last_synced", db["app"])

    def test_failed_status(self):
        db = {}
        update_status(db, "app", "failed", error="404 Not Found")
        self.assertEqual(db["app"]["status"], "failed")
        self.assertEqual(db["app"]["error"], "404 Not Found")

    def test_error_cleared_on_success(self):
        db = {"app": {"status": "failed", "error": "old error"}}
        update_status(db, "app", "synced", latest_version="v1.0")
        self.assertNotIn("error", db["app"])


if __name__ == "__main__":
    unittest.main()
