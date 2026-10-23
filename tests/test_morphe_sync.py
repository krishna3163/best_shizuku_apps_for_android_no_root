"""Tests for Morphe patch bundle client, patcher, and sync automation in best_shizuku_apps."""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from morphe_builder import (
    BaseApkManager,
    MorpheAppConfig,
    MorpheBundleClient,
    MorphePatcher,
)
from morphe_sync import (
    generate_morphe_readme_table,
    make_morphe_tag,
    update_readme_content,
)


class TestMorpheShizukuSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        dummy_data = {
            "bundles": [
                {
                    "source": "github",
                    "repo": "MorpheApp/morphe-patches",
                    "name": "Official Morphe",
                    "targetApps": ["com.google.android.youtube"],
                    "patchCount": 10,
                }
            ],
            "store": {
                "com.google.android.youtube": {
                    "name": "YouTube",
                    "category": "Video",
                    "description": "Video streaming",
                }
            },
            "compatibilities": [
                {
                    "packageName": "com.google.android.youtube",
                    "targets": [{"version": "19.16.39"}],
                }
            ],
        }
        with open(self.tmp.name, "w", encoding="utf-8") as f:
            json.dump(dummy_data, f)
        self.client = MorpheBundleClient(cache_file=Path(self.tmp.name))

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_client_lookups(self):
        b = self.client.get_bundle_by_repo("MorpheApp/morphe-patches")
        self.assertIsNotNone(b)
        versions = self.client.get_compatible_versions("com.google.android.youtube")
        self.assertEqual(versions, ["19.16.39"])

    def test_tag_generation(self):
        self.assertEqual(make_morphe_tag("morphe-youtube-nonroot", "19.16.39", "stable"), "morphe-youtube-nonroot-19.16.39")
        self.assertEqual(make_morphe_tag("morphe-insta", "328.0", "beta"), "morphe-insta-328.0-beta")

    def test_patcher_internal_engine(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_apk = BaseApkManager.fetch_base_apk("com.google.android.youtube", "19.16.39", tmp_dir)
            bundle_mpp = os.path.join(tmp_dir, "test.mpp")
            with open(bundle_mpp, "wb") as f:
                f.write(b"MPP")
            out_apk = os.path.join(tmp_dir, "patched.apk")

            patcher = MorphePatcher()
            ok, msg = patcher.patch_apk(base_apk, bundle_mpp, out_apk, ["GmsCore support", "Hide ads"])
            self.assertTrue(ok, msg)
            self.assertTrue(os.path.exists(out_apk))

            with zipfile.ZipFile(out_apk, "r") as zf:
                self.assertIn("assets/morphe_patch_info.json", zf.namelist())


if __name__ == "__main__":
    unittest.main()
