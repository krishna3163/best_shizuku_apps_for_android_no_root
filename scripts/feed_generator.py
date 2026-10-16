"""Obtainium & RSS / Atom Feed Generator.

Generates site/releases.atom and site/obtainium.json for tracking mirrored Shizuku apps.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("feed-generator")
ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "apps.json"
SITE_DIR = ROOT / "site"


def build_obtainium_export(apps_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate an Obtainium-compatible JSON export."""
    obtainium_apps = []
    for app in apps_data:
        slug = app.get("slug", "")
        name = app.get("name", slug)
        repo = app.get("repository") or app.get("source_repo", "")
        if not repo:
            continue
        obtainium_apps.append({
            "id": slug,
            "url": f"https://github.com/{repo}",
            "author": repo.split("/")[0],
            "name": name,
            "preferredApkFilter": app.get("asset_patterns", [".*\\.apk$"])[0] if app.get("asset_patterns") else ".*\\.apk$",
            "filterByPrerelease": False,
            "versionExtraction": "latest-stable",
        })

    return {
        "formatVersion": 1,
        "name": "Best Shizuku Apps (No Root) Catalog",
        "description": "Auto-sync and direct update feed for Shizuku apps curated by krishna3163",
        "source": "https://github.com/krishna3163/best_shizuku_apps_for_android_no_root",
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "apps": obtainium_apps,
    }


def build_atom_feed(apps_data: list[dict[str, Any]], releases: Optional[list[dict[str, Any]]] = None) -> str:
    """Generate a valid Atom 1.0 XML feed."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    feed_id = "tag:github.com,2026:krishna3163/best_shizuku_apps_for_android_no_root"
    feed_url = "https://github.com/krishna3163/best_shizuku_apps_for_android_no_root"

    entries_xml = []
    items_to_render = releases if releases else apps_data

    for item in items_to_render:
        title = html.escape(item.get("name") or item.get("title") or "Shizuku App Release")
        slug = item.get("slug", "app")
        version = item.get("version", "latest")
        repo = item.get("repository") or item.get("source_repo", "krishna3163/best_shizuku_apps_for_android_no_root")
        item_url = item.get("html_url") or f"https://github.com/{repo}/releases"
        published = item.get("published_at") or now_iso
        description = html.escape(item.get("description") or f"Mirrored update for {title}")

        entry = f"""  <entry>
    <title>{title} {version}</title>
    <link href="{item_url}"/>
    <id>{feed_id}:{slug}:{version}</id>
    <updated>{published}</updated>
    <summary type="text">{description}</summary>
    <author>
      <name>{html.escape(repo.split('/')[0])}</name>
    </author>
  </entry>"""
        entries_xml.append(entry)

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Best Shizuku Apps for Android - Releases Feed</title>
  <subtitle>Latest mirrored APK releases and Shizuku power-tool updates</subtitle>
  <link href="{feed_url}/releases.atom" rel="self"/>
  <link href="{feed_url}"/>
  <id>{feed_id}</id>
  <updated>{now_iso}</updated>
  <author>
    <name>krishna3163</name>
    <uri>{feed_url}</uri>
  </author>
{chr(10).join(entries_xml)}
</feed>
"""
    return xml


def generate_feeds(output_dir: Path) -> tuple[Path, Path]:
    """Generate both feed files in the destination directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    apps = []
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            apps = data.get("apps", [])
        except Exception as exc:
            logger.warning("Could not read apps.json: %s", exc)

    # 1. Obtainium Export
    obtainium_data = build_obtainium_export(apps)
    obtainium_path = output_dir / "obtainium.json"
    obtainium_path.write_text(json.dumps(obtainium_data, indent=2), encoding="utf-8")

    # 2. Atom XML Feed
    atom_xml = build_atom_feed(apps)
    atom_path = output_dir / "releases.atom"
    atom_path.write_text(atom_xml, encoding="utf-8")

    return obtainium_path, atom_path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Generate Obtainium export and Atom XML feeds.")
    parser.add_argument("--output-dir", default=str(SITE_DIR), help="Output directory (default: site/)")
    args = parser.parse_args()

    out = Path(args.output_dir)
    p_obt, p_atom = generate_feeds(out)
    print(f"✅ Generated Obtainium feed: {p_obt}")
    print(f"✅ Generated Atom feed: {p_atom}")
    return 0


if __name__ == "__main__":
    main()
