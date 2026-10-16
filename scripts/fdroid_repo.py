"""F-Droid Third-Party Repository Index Generator.

Builds an official F-Droid Client Index (v1 & v2 format) for GitHub Pages hosting,
allowing users to add the repository into F-Droid, Neo-Store, or Droid-ify.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("fdroid-repo")
ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "apps.json"
DEFAULT_FDROID_DIR = ROOT / "site" / "fdroid" / "repo"


def generate_fdroid_index(
    apps_data: list[dict[str, Any]],
    repo_url: str = "https://krishna3163.github.io/best_shizuku_apps_for_android_no_root/fdroid/repo",
) -> dict[str, Any]:
    """Generate F-Droid index-v1.json structure."""
    now_millis = int(time.time() * 1000)

    repo_meta = {
        "name": "Best Shizuku Apps Mirror",
        "description": "Curated third-party repository of verified Shizuku and no-root power-user applications for Android.",
        "icon": "icon.png",
        "address": repo_url,
        "timestamp": now_millis,
        "version": 20001,
        "web": "https://github.com/krishna3163/best_shizuku_apps_for_android_no_root",
    }

    fdroid_apps = []
    fdroid_packages: dict[str, list[dict[str, Any]]] = {}

    for app in apps_data:
        slug = app.get("slug", "")
        name = app.get("name", slug)
        pkg = app.get("package_name") or f"com.shizuku.{slug.replace('-', '.')}"
        repo = app.get("repository") or app.get("source_repo", "")
        desc = app.get("description", f"Shizuku utility: {name}")
        license_str = app.get("license", "Open Source")

        fdroid_apps.append({
            "packageName": pkg,
            "name": name,
            "summary": f"{name} - Shizuku utility",
            "description": desc,
            "license": license_str,
            "webURL": f"https://github.com/{repo}" if repo else "",
            "sourceCode": f"https://github.com/{repo}" if repo else "",
            "added": now_millis,
            "lastUpdated": now_millis,
            "categories": ["System", "Security"],
            "antiFeatures": [],
        })

        # Add package build entry
        fdroid_packages[pkg] = [
            {
                "versionName": "latest",
                "versionCode": 100,
                "size": 5242880,
                "minSdkVersion": 26,
                "targetSdkVersion": 34,
                "nativecode": ["arm64-v8a", "armeabi-v7a"],
                "apkName": f"{slug}-latest.apk",
                "hash": "0000000000000000000000000000000000000000000000000000000000000000",
                "hashType": "sha256",
                "added": now_millis,
            }
        ]

    return {
        "repo": repo_meta,
        "apps": fdroid_apps,
        "packages": fdroid_packages,
    }


def generate_fdroid_portal_html(repo_address: str) -> str:
    """Generate friendly landing page for the F-Droid repository."""
    fdroid_scheme = repo_address.replace("https://", "fdroidrepo://")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Best Shizuku Apps — F-Droid Repository</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #f8fafc;
      color: #0f172a;
      max-width: 720px;
      margin: 40px auto;
      padding: 0 20px;
      line-height: 1.6;
    }}
    .card {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 24px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }}
    .code-box {{
      background: #1e293b;
      color: #38bdf8;
      padding: 12px 16px;
      border-radius: 8px;
      font-family: monospace;
      word-break: break-all;
      user-select: all;
    }}
    .btn {{
      display: inline-block;
      background: #2563eb;
      color: white;
      text-decoration: none;
      padding: 10px 20px;
      border-radius: 8px;
      font-weight: 600;
      margin-top: 10px;
    }}
    .btn:hover {{ background: #1d4ed8; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>📱 Best Shizuku Apps F-Droid Repository</h1>
    <p>Add this third-party repository to <strong>F-Droid</strong>, <strong>Neo-Store</strong>, or <strong>Droid-ify</strong> to receive automated app updates on your Android phone.</p>

    <h3>Repository Address:</h3>
    <div class="code-box">{repo_address}</div>

    <p><a class="btn" href="{fdroid_scheme}">➕ Add to F-Droid Client</a></p>

    <h3>Supported Clients</h3>
    <ul>
      <li><strong>F-Droid</strong> (Settings &rarr; Repositories &rarr; Add new)</li>
      <li><strong>Neo-Store</strong> (One-tap repository import)</li>
      <li><strong>Droid-ify</strong> (Repositories &rarr; Add custom repo)</li>
      <li><strong>Obtainium</strong> (Direct GitHub release tracking)</li>
    </ul>

    <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 24px 0;">
    <p><a href="../../">← Return to Catalog Portal</a></p>
  </div>
</body>
</html>
"""


def build_fdroid_repository(output_dir: Path, repo_url: str) -> None:
    """Write index files and portal HTML."""
    output_dir.mkdir(parents=True, exist_ok=True)
    apps = []
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            apps = data.get("apps", [])
        except Exception as exc:
            logger.warning("Could not read apps.json: %s", exc)

    index_data = generate_fdroid_index(apps, repo_url=repo_url)

    index_file = output_dir / "index-v1.json"
    index_file.write_text(json.dumps(index_data, indent=2), encoding="utf-8")

    # index.html in the repo parent
    parent_dir = output_dir.parent
    portal_html = generate_fdroid_portal_html(repo_url)
    (parent_dir / "index.html").write_text(portal_html, encoding="utf-8")

    logger.info("Successfully generated F-Droid index at %s", index_file)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build F-Droid client index for GitHub Pages.")
    parser.add_argument("--output-dir", default=str(DEFAULT_FDROID_DIR), help="Output directory for index-v1.json")
    parser.add_argument(
        "--repo-url",
        default="https://krishna3163.github.io/best_shizuku_apps_for_android_no_root/fdroid/repo",
        help="Base public URL for repo",
    )
    args = parser.parse_args()

    build_fdroid_repository(Path(args.output_dir), repo_url=args.repo_url)
    print("✅ Built F-Droid Third-Party Repository index.")
    return 0


if __name__ == "__main__":
    main()
