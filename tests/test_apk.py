"""Tests for APK detection, filtering, validation, and checksum utilities."""

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from apk import (
    calculate_sha256,
    create_checksum_file,
    detect_architecture,
    filter_assets,
    is_apk_candidate,
    matches_patterns,
    normalize_filename,
    select_best_assets,
    validate_apk,
)


class TestIsApkCandidate(unittest.TestCase):
    def test_valid_apk(self):
        self.assertTrue(is_apk_candidate("app.apk"))
        self.assertTrue(is_apk_candidate("app-release.apk"))
        self.assertTrue(is_apk_candidate("App-v1.2.3.apk"))
        self.assertTrue(is_apk_candidate("APP.APK"))

    def test_invalid_extensions(self):
        self.assertFalse(is_apk_candidate("app.zip"))
        self.assertFalse(is_apk_candidate("app.aab"))
        self.assertFalse(is_apk_candidate("app.jar"))
        self.assertFalse(is_apk_candidate("app.txt"))
        self.assertFalse(is_apk_candidate("app.json"))
        self.assertFalse(is_apk_candidate("app.sha256"))
        self.assertFalse(is_apk_candidate("app.asc"))


class TestDetectArchitecture(unittest.TestCase):
    def test_universal(self):
        self.assertEqual(detect_architecture("app-universal.apk"), "universal")

    def test_arm64(self):
        self.assertEqual(detect_architecture("app-arm64-v8a.apk"), "arm64-v8a")

    def test_armeabi(self):
        self.assertEqual(detect_architecture("app-armeabi-v7a.apk"), "armeabi-v7a")

    def test_x86_64(self):
        self.assertEqual(detect_architecture("app-x86_64.apk"), "x86_64")

    def test_unknown(self):
        self.assertEqual(detect_architecture("app-release.apk"), "unknown")


class TestFilterAssets(unittest.TestCase):
    def _asset(self, name):
        return {"name": name, "id": 1, "url": "https://example.com"}

    def test_basic_filter(self):
        assets = [self._asset("app.apk"), self._asset("app.zip"), self._asset("source.tar.gz")]
        result = filter_assets(assets)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "app.apk")

    def test_exclude_debug(self):
        assets = [self._asset("app-release.apk"), self._asset("app-debug.apk")]
        result = filter_assets(assets)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "app-release.apk")

    def test_exclude_unsigned(self):
        assets = [self._asset("app.apk"), self._asset("app-unsigned.apk")]
        result = filter_assets(assets)
        self.assertEqual(len(result), 1)

    def test_exclude_test(self):
        assets = [self._asset("app.apk"), self._asset("app-test.apk")]
        result = filter_assets(assets)
        self.assertEqual(len(result), 1)

    def test_multiple_apks(self):
        assets = [
            self._asset("app-universal.apk"),
            self._asset("app-arm64-v8a.apk"),
            self._asset("app-armeabi-v7a.apk"),
        ]
        result = filter_assets(assets)
        self.assertEqual(len(result), 3)

    def test_custom_patterns(self):
        assets = [self._asset("app-universal.apk"), self._asset("app-arm64.apk")]
        result = filter_assets(assets, asset_patterns=[".*universal.*\\.apk$"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "app-universal.apk")

    def test_no_apk(self):
        assets = [self._asset("readme.md"), self._asset("source.zip")]
        result = filter_assets(assets)
        self.assertEqual(len(result), 0)


class TestSelectBestAssets(unittest.TestCase):
    def _asset(self, name):
        return {"name": name, "id": 1}

    def test_single_asset(self):
        assets = [self._asset("app.apk")]
        result = select_best_assets(assets)
        self.assertEqual(len(result), 1)

    def test_multiple_variants(self):
        assets = [
            self._asset("app-universal.apk"),
            self._asset("app-arm64-v8a.apk"),
            self._asset("app-x86_64.apk"),
        ]
        result = select_best_assets(assets)
        self.assertEqual(len(result), 3)

    def test_empty_list(self):
        result = select_best_assets([])
        self.assertEqual(len(result), 0)


class TestValidation(unittest.TestCase):
    def test_nonexistent_file(self):
        valid, msg = validate_apk("/nonexistent/path.apk")
        self.assertFalse(valid)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as f:
            path = f.name
        try:
            valid, msg = validate_apk(path)
            self.assertFalse(valid)
        finally:
            os.unlink(path)

    def test_not_zip(self):
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False, mode="w") as f:
            f.write("this is not a zip file")
            path = f.name
        try:
            valid, msg = validate_apk(path)
            self.assertFalse(valid)
        finally:
            os.unlink(path)

    def test_zip_without_manifest(self):
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as f:
            path = f.name
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("random.txt", "hello")
        try:
            valid, msg = validate_apk(path)
            self.assertFalse(valid)
        finally:
            os.unlink(path)

    def test_valid_apk_structure(self):
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as f:
            path = f.name
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("AndroidManifest.xml", "<manifest/>")
            zf.writestr("classes.dex", "fake-dex")
        try:
            valid, msg = validate_apk(path)
            self.assertTrue(valid)
        finally:
            os.unlink(path)


class TestChecksum(unittest.TestCase):
    def test_sha256(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            path = f.name
        try:
            h = calculate_sha256(path)
            self.assertEqual(len(h), 64)
            # Known SHA-256 of "test content"
            self.assertEqual(h, "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72")
        finally:
            os.unlink(path)

    def test_checksum_file(self):
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as f:
            f.write(b"apk content")
            path = f.name
        try:
            sha = calculate_sha256(path)
            checksum_path = create_checksum_file(path, sha)
            self.assertTrue(os.path.exists(checksum_path))
            content = open(checksum_path, encoding="utf-8").read()
            self.assertIn(sha, content)
            self.assertIn(os.path.basename(path), content)
        finally:
            os.unlink(path)
            if os.path.exists(path + ".sha256"):
                os.unlink(path + ".sha256")


class TestNormalization(unittest.TestCase):
    def test_safe_name_unchanged(self):
        self.assertEqual(normalize_filename("app-release.apk", "test", "v1.0"), "app-release.apk")

    def test_unsafe_characters(self):
        result = normalize_filename("Example App v2.1.0 universal.apk", "test", "v2.1.0")
        self.assertTrue(result.endswith(".apk"))
        self.assertNotIn(" ", result)


if __name__ == "__main__":
    unittest.main()
