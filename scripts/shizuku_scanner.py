"""Multi-Source Shizuku App Scanner & Automated Release Pipeline.

Scans GitHub (topics, code search, queries) and upstream awesome-shizuku lists
for Android apps with Shizuku integration.
Automatically:
1. Validates Shizuku integration and APK release availability.
2. Registers new apps in config/apps.json and README.md.
3. Downloads & mirrors the latest APK release to GitHub Releases with SHA-256 checksums.

Usage:
    python scripts/shizuku_scanner.py                     # Scan and display new candidates
    python scripts/shizuku_scanner.py --auto-add          # Scan and register in apps.json & README
    python scripts/shizuku_scanner.py --sync-releases     # Full pipeline: scan, register, and mirror APKs to GitHub Releases
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

# Ensure scripts/ is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_api import GitHubAPI
from metadata import load_releases_db, load_status_db, save_releases_db, save_status_db
from sync import get_app_config, load_config, sync_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("shizuku-scanner")

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "apps.json"
README_PATH = ROOT / "README.md"
AWESOME_SHIZUKU_URL = "https://raw.githubusercontent.com/timschneeb/awesome-shizuku/master/README.md"

SEARCH_QUERIES = [
    "topic:shizuku",
    "shizuku android app in:description,readme",
    "shizuku debloat android in:description,readme",
    "moe.shizuku.privileged.api in:file path:build.gradle",
    "android wireless adb shizuku in:readme",
]

CATEGORY_KEYWORDS = {
    "Networking": ["dns", "firewall", "adblock", "proxy", "vpn", "hosts"],
    "App Management": ["debloat", "freeze", "uninstall", "package", "installer", "backup", "apk", "app ops"],
    "Privacy and Security": ["permission", "privacy", "security", "guard", "crypto", "sandbox", "hide"],
    "Automation": ["automate", "macro", "tasker", "scheduler", "trigger"],
    "Customization": ["theme", "systemui", "status bar", "nav bar", "custom", "font", "overlay"],
    "Development": ["logcat", "debug", "developer", "terminal", "shell", "rish", "adb", "inspector"],
    "File Management": ["file", "explorer", "manager", "storage", "sdcard", "saf"],
    "Gaming": ["game", "fps", "performance", "boost", "controller", "graphics"],
}


def load_known_repositories() -> set[str]:
    """Return set of normalized lowercase repository slugs (owner/repo)."""
    known = set()
    # 1. From config/apps.json
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for a in cfg.get("apps", []):
                    repo = a.get("repository", "").strip().lower()
                    if repo:
                        known.add(repo)
        except Exception as e:
            logger.warning("Could not read apps.json: %s", e)

    # 2. From README.md
    if README_PATH.exists():
        content = README_PATH.read_text(encoding="utf-8")
        github_links = re.findall(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", content)
        for link in github_links:
            clean = link.rstrip("/").lower()
            if not clean.endswith(".git") and not clean.startswith("krishna3163/"):
                known.add(clean)

    return known


def guess_category(name: str, description: str, topics: list[str]) -> str:
    """Classify app into a catalog category based on keywords."""
    combined = f"{name} {description} {' '.join(topics)}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return category
    return "System Utilities"


def fetch_awesome_shizuku_repos() -> list[str]:
    """Scrape GitHub repos mentioned in timschneeb/awesome-shizuku."""
    repos: list[str] = []
    try:
        req = Request(AWESOME_SHIZUKU_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", "ignore")
            matches = re.findall(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text)
            for m in matches:
                clean = m.rstrip("/").strip()
                if clean.lower() not in {"timschneeb/awesome-shizuku", "rikkaapps/shizuku"}:
                    repos.append(clean)
    except Exception as exc:
        logger.warning("Failed to fetch upstream awesome-shizuku: %s", exc)
    return repos


def query_github_search(query: str, token: str = "") -> list[dict[str, Any]]:
    """Query GitHub Search API for repositories."""
    params = urlencode({"q": query, "sort": "updated", "order": "desc", "per_page": 30})
    url = f"https://api.github.com/search/repositories?{params}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Shizuku-Scanner/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:
            data = json.load(resp)
            return data.get("items", [])
    except Exception as exc:
        logger.warning("GitHub search failed for '%s': %s", query, exc)
        return []


def inspect_candidate_repo(repo_slug: str, api: GitHubAPI) -> dict[str, Any] | None:
    """Inspect upstream repo to verify Shizuku usage and extract latest APK release."""
    if repo_slug.lower().startswith("krishna3163/"):
        return None
    try:
        resp = api.get(f"/repos/{repo_slug}")
        if resp.status_code != 200:
            return None
        repo_data = resp.json()

        # Skip forks, archived, or disabled repositories
        if repo_data.get("archived") or repo_data.get("disabled"):
            return None

        # Fetch latest release
        latest_rel = api.get_latest_release(repo_slug)
        if not latest_rel:
            # Try fetching recent releases
            rels = api.get_releases(repo_slug, per_page=5)
            latest_rel = rels[0] if rels else None

        if not latest_rel:
            logger.debug("No releases found for %s", repo_slug)
            return None

        assets = latest_rel.get("assets", [])
        apk_assets = [
            a for a in assets
            if a.get("name", "").endswith(".apk") and not any(x in a.get("name", "").lower() for x in ("debug", "test", "unsigned"))
        ]

        if not apk_assets:
            # Fallback check any apk asset
            apk_assets = [a for a in assets if a.get("name", "").endswith(".apk")]

        if not apk_assets:
            logger.debug("No APK assets found in release %s for %s", latest_rel.get("tag_name"), repo_slug)
            return None

        name = repo_data.get("name", "").strip()
        desc = (repo_data.get("description") or "Shizuku-compatible Android tool.").strip()
        license_info = repo_data.get("license") or {}
        license_spdx = license_info.get("spdx_id") or license_info.get("name") or "See project"
        if license_spdx in {"NOASSERTION", "Other"}:
            license_spdx = "See project"

        topics = repo_data.get("topics", [])
        category = guess_category(name, desc, topics)

        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

        return {
            "name": name,
            "slug": slug,
            "repository": repo_slug,
            "description": desc,
            "license": license_spdx,
            "category": category,
            "stars": repo_data.get("stargazers_count", 0),
            "latest_release_tag": latest_rel.get("tag_name", ""),
            "latest_release_id": latest_rel.get("id"),
            "apk_assets": [a.get("name") for a in apk_assets],
            "html_url": repo_data.get("html_url", f"https://github.com/{repo_slug}"),
        }
    except Exception as exc:
        logger.warning("Error inspecting candidate %s: %s", repo_slug, exc)
        return None


def register_app_in_config(candidate: dict[str, Any]) -> bool:
    """Add newly discovered app to config/apps.json."""
    if not CONFIG_PATH.exists():
        return False

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        existing_slugs = {a.get("slug") for a in cfg.get("apps", [])}
        existing_repos = {a.get("repository", "").lower() for a in cfg.get("apps", [])}

        if candidate["slug"] in existing_slugs or candidate["repository"].lower() in existing_repos:
            return False

        new_entry = {
            "name": candidate["name"],
            "slug": candidate["slug"],
            "repository": candidate["repository"],
            "enabled": True,
            "shizuku": True,
            "release_strategy": "latest-stable",
            "asset_patterns": [".*\\.apk$"],
            "exclude_patterns": [".*debug.*", ".*unsigned.*", ".*test.*"],
        }

        cfg.setdefault("apps", []).append(new_entry)

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")

        logger.info("➕ Added %s to config/apps.json", candidate["name"])
        return True
    except Exception as exc:
        logger.error("Failed to register %s in config/apps.json: %s", candidate["name"], exc)
        return False


def register_app_in_readme(candidate: dict[str, Any]) -> bool:
    """Insert newly discovered app row into README.md."""
    if not README_PATH.exists():
        return False

    content = README_PATH.read_text(encoding="utf-8")
    app_url = candidate["html_url"]

    # Check if already present in README
    if app_url.lower() in content.lower():
        return False

    safe_name = candidate["name"]
    safe_desc = candidate["description"].replace("|", "\\|")
    safe_lic = candidate["license"]
    link_col = f"[GitHub]({app_url}) • [Releases]({app_url}/releases)"

    row = f"| **[{safe_name}]({app_url})** | {safe_desc} | {safe_lic} | {link_col} |"

    # Insert into AUTO-DISCOVERED-SHIZUKU-APPS table
    start_marker = "<!-- AUTO-DISCOVERED-SHIZUKU-APPS:START -->"
    end_marker = "<!-- AUTO-DISCOVERED-SHIZUKU-APPS:END -->"

    if start_marker in content and end_marker in content:
        start_idx = content.index(start_marker)
        end_idx = content.index(end_marker, start_idx)
        block = content[start_idx:end_idx]

        # Check if table header exists in block
        table_hdr = "|:---|:---|:---|:---|"
        if table_hdr in block:
            hdr_pos = block.index(table_hdr) + len(table_hdr)
            new_block = block[:hdr_pos] + "\n" + row + block[hdr_pos:]
            content = content[:start_idx] + new_block + content[end_idx:]
            README_PATH.write_text(content, encoding="utf-8")
            logger.info("➕ Appended %s to README.md auto-discovered table", safe_name)
            return True

    return False


def run_scanner_pipeline(
    auto_add: bool = False,
    sync_releases: bool = False,
    token: str = "",
) -> list[dict[str, Any]]:
    """Scan all sources, validate, register, and mirror APKs."""
    token = token or os.environ.get("GITHUB_TOKEN", "")
    api = GitHubAPI(token)

    logger.info("Scanning for new Shizuku apps across GitHub and ecosystem...")
    known_repos = load_known_repositories()
    logger.info("Currently tracking %d known repositories.", len(known_repos))

    candidate_slugs: set[str] = set()

    # 1. Scrape awesome-shizuku upstream list
    awesome_repos = fetch_awesome_shizuku_repos()
    for repo in awesome_repos:
        if repo.lower() not in known_repos:
            candidate_slugs.add(repo)

    logger.info("Found %d candidate(s) from awesome-shizuku.", len(candidate_slugs))

    # 2. Query GitHub Search API
    for q in SEARCH_QUERIES:
        logger.info("Querying GitHub Search API: '%s'...", q)
        items = query_github_search(q, token)
        for it in items:
            full_name = it.get("full_name", "")
            if full_name and full_name.lower() not in known_repos:
                candidate_slugs.add(full_name)

    logger.info("Total unique candidates to inspect: %d", len(candidate_slugs))

    discovered_apps: list[dict[str, Any]] = []

    # 3. Inspect each candidate for Shizuku usage and APK releases
    for slug in candidate_slugs:
        candidate = inspect_candidate_repo(slug, api)
        if candidate:
            logger.info("✨ Discovered valid Shizuku app: %s (%s) - %s", candidate["name"], slug, candidate["latest_release_tag"])
            discovered_apps.append(candidate)

    logger.info("Identified %d verified new Shizuku app(s) with APK releases.", len(discovered_apps))

    if not auto_add and not sync_releases:
        for app in discovered_apps:
            print(f"- {app['name']} [{app['category']}] ({app['license']}) -> {app['repository']} (Tag: {app['latest_release_tag']}, APKs: {len(app['apk_assets'])})")
        return discovered_apps

    # 4. Auto-register in config and README
    registered_count = 0
    for app in discovered_apps:
        c_ok = register_app_in_config(app)
        r_ok = register_app_in_readme(app)
        if c_ok or r_ok:
            registered_count += 1

    logger.info("Successfully registered %d new apps in repository catalog.", registered_count)

    # 5. Mirror releases and extract APKs
    if sync_releases and discovered_apps:
        logger.info("Starting automated release mirroring and APK extraction...")
        config = load_config()
        defaults = config.get("defaults", {})
        releases_db = load_releases_db()
        status_db = load_status_db()

        for app_candidate in discovered_apps:
            # Match registered config app
            matched_app = next((a for a in config.get("apps", []) if a.get("slug") == app_candidate["slug"]), None)
            if not matched_app:
                matched_app = {
                    "name": app_candidate["name"],
                    "slug": app_candidate["slug"],
                    "repository": app_candidate["repository"],
                    "enabled": True,
                    "shizuku": True,
                    "release_strategy": "latest-stable",
                    "asset_patterns": [".*\\.apk$"],
                    "exclude_patterns": [".*debug.*", ".*unsigned.*", ".*test.*"],
                }

            app_cfg = get_app_config(matched_app, defaults)
            try:
                logger.info("Mirroring APK for %s (%s)...", app_cfg["name"], app_cfg["repository"])
                res = sync_app(app_cfg, api, releases_db, status_db, dry_run=False)
                logger.info("Sync result for %s: %s", app_cfg["name"], res)
            except Exception as exc:
                logger.error("Failed to mirror APK for %s: %s", app_cfg["name"], exc)

        save_releases_db(releases_db)
        save_status_db(status_db)
        logger.info("APK extraction and mirror release pipeline complete.")

    return discovered_apps


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Multi-source Shizuku app scanner & release pipeline.")
    parser.add_argument("--auto-add", action="store_true", help="Add discovered apps to config/apps.json and README.md")
    parser.add_argument("--sync-releases", action="store_true", help="Full pipeline: scan, register, and mirror APKs to GitHub Releases")
    parser.add_argument("--token", default="", help="GitHub Personal Access Token")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    run_scanner_pipeline(
        auto_add=args.auto_add or args.sync_releases,
        sync_releases=args.sync_releases,
        token=token,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
