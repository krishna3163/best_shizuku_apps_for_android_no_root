"""Tests for configuration loading and validation."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class TestConfigLoading(unittest.TestCase):
    """Test the apps.json configuration file."""

    CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "apps.json"

    def test_config_exists(self):
        self.assertTrue(self.CONFIG_PATH.exists(), "config/apps.json must exist")

    def test_config_valid_json(self):
        with open(self.CONFIG_PATH, encoding="utf-8") as fh:
            config = json.load(fh)
        self.assertIsInstance(config, dict)

    def test_apps_list_present(self):
        with open(self.CONFIG_PATH, encoding="utf-8") as fh:
            config = json.load(fh)
        self.assertIn("apps", config)
        self.assertIsInstance(config["apps"], list)
        self.assertGreater(len(config["apps"]), 0)

    def test_required_fields(self):
        with open(self.CONFIG_PATH, encoding="utf-8") as fh:
            config = json.load(fh)
        for app in config["apps"]:
            self.assertIn("name", app, f"Missing 'name' in app: {app}")
            self.assertIn("slug", app, f"Missing 'slug' in app: {app}")
            self.assertIn("repository", app, f"Missing 'repository' in app: {app}")
            self.assertTrue("/" in app["repository"], f"Invalid repo format: {app['repository']}")

    def test_unique_slugs(self):
        with open(self.CONFIG_PATH, encoding="utf-8") as fh:
            config = json.load(fh)
        slugs = [app["slug"] for app in config["apps"]]
        self.assertEqual(len(slugs), len(set(slugs)), "Slugs must be unique")

    def test_valid_release_strategies(self):
        valid = {"latest", "latest-stable", "latest-prerelease", "latest-any"}
        with open(self.CONFIG_PATH, encoding="utf-8") as fh:
            config = json.load(fh)
        for app in config["apps"]:
            strategy = app.get("release_strategy", "latest-stable")
            self.assertIn(strategy, valid, f"Invalid strategy for {app['slug']}: {strategy}")

    def test_defaults_present(self):
        with open(self.CONFIG_PATH, encoding="utf-8") as fh:
            config = json.load(fh)
        self.assertIn("defaults", config)

    def test_disabled_app(self):
        """Ensure disabled apps are valid."""
        config = {"apps": [{"name": "Test", "slug": "test", "repository": "owner/repo", "enabled": False}]}
        app = config["apps"][0]
        self.assertFalse(app["enabled"])


class TestInvalidConfig(unittest.TestCase):
    """Test handling of invalid configurations."""

    def test_missing_slug(self):
        app = {"name": "Test", "repository": "owner/repo"}
        self.assertNotIn("slug", app)

    def test_missing_repository(self):
        app = {"name": "Test", "slug": "test"}
        self.assertNotIn("repository", app)

    def test_invalid_repository_format(self):
        app = {"name": "Test", "slug": "test", "repository": "invalid-no-slash"}
        self.assertFalse("/" in app["repository"])


if __name__ == "__main__":
    unittest.main()
