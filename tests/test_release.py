"""Tests for release detection, selection, and tag generation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from release import (
    extract_version,
    generate_release_body,
    make_mirror_tag,
    make_release_title,
    pick_release,
)


class TestPickRelease(unittest.TestCase):
    def _release(self, tag, draft=False, prerelease=False, release_id=1):
        return {
            "id": release_id,
            "tag_name": tag,
            "name": f"Release {tag}",
            "draft": draft,
            "prerelease": prerelease,
            "assets": [],
        }

    def test_latest_stable(self):
        releases = [
            self._release("v2.0.0", prerelease=True, release_id=3),
            self._release("v1.1.0", release_id=2),
            self._release("v1.0.0", release_id=1),
        ]
        result = pick_release(releases, "latest-stable")
        self.assertIsNotNone(result)
        self.assertEqual(result["tag_name"], "v1.1.0")

    def test_latest_alias(self):
        releases = [self._release("v1.0.0")]
        result = pick_release(releases, "latest")
        self.assertIsNotNone(result)
        self.assertEqual(result["tag_name"], "v1.0.0")

    def test_latest_prerelease(self):
        releases = [
            self._release("v2.0.0-beta", prerelease=True),
            self._release("v1.0.0"),
        ]
        result = pick_release(releases, "latest-prerelease")
        self.assertIsNotNone(result)
        self.assertEqual(result["tag_name"], "v2.0.0-beta")

    def test_latest_any(self):
        releases = [
            self._release("v2.0.0-beta", prerelease=True),
            self._release("v1.0.0"),
        ]
        result = pick_release(releases, "latest-any")
        self.assertIsNotNone(result)
        self.assertEqual(result["tag_name"], "v2.0.0-beta")

    def test_skip_drafts(self):
        releases = [
            self._release("v2.0.0", draft=True),
            self._release("v1.0.0"),
        ]
        result = pick_release(releases, "latest-stable")
        self.assertEqual(result["tag_name"], "v1.0.0")

    def test_no_matching_release(self):
        releases = [
            self._release("v1.0.0-beta", prerelease=True),
        ]
        result = pick_release(releases, "latest-stable")
        self.assertIsNone(result)

    def test_empty_releases(self):
        result = pick_release([], "latest-stable")
        self.assertIsNone(result)

    def test_all_drafts(self):
        releases = [self._release("v1.0.0", draft=True)]
        result = pick_release(releases, "latest-any")
        self.assertIsNone(result)


class TestExtractVersion(unittest.TestCase):
    def test_tag_name(self):
        self.assertEqual(extract_version({"tag_name": "v1.2.3", "id": 1}), "v1.2.3")

    def test_name_fallback(self):
        self.assertEqual(extract_version({"tag_name": "", "name": "Release v2.0.0", "id": 1}), "v2.0.0")

    def test_id_fallback(self):
        self.assertEqual(extract_version({"tag_name": "", "name": "", "id": 12345}), "release-12345")


class TestMirrorTag(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(make_mirror_tag("example-app", "v1.2.3"), "example-app-v1.2.3")

    def test_special_characters(self):
        tag = make_mirror_tag("my-app", "release 1.0 (beta)")
        self.assertNotIn(" ", tag)
        self.assertNotIn("(", tag)

    def test_release_without_v(self):
        self.assertEqual(make_mirror_tag("app", "1.0.0"), "app-1.0.0")


class TestReleaseTitle(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(make_release_title("Example App", "v1.0.0"), "Example App v1.0.0")


class TestReleaseBody(unittest.TestCase):
    def test_contains_attribution(self):
        body = generate_release_body(
            "Test App", "v1.0", "owner/repo", "v1.0",
            [{"filename": "app.apk", "sha256": "abc123", "architecture": "universal", "file_size": 1024000}],
        )
        self.assertIn("owner/repo", body)
        self.assertIn("abc123", body)
        self.assertIn("without modification", body)
        self.assertIn("original project", body)

    def test_includes_license(self):
        body = generate_release_body(
            "Test App", "v1.0", "owner/repo", "v1.0", [], license_info="MIT License",
        )
        self.assertIn("MIT License", body)


if __name__ == "__main__":
    unittest.main()
