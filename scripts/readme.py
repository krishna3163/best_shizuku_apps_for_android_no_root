"""README auto-update for the APK download index."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("apk-sync")

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"

# Markers for auto-generated content
START_MARKER = "<!-- AUTO-GENERATED-APPS-START -->"
END_MARKER = "<!-- AUTO-GENERATED-APPS-END -->"


def _get_mirror_repo() -> str:
    """Try to detect the mirror repository from environment or git remote."""
    import os
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        return repo
    # Fallback: try parsing git remote
    try:
        import subprocess
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        url = result.stdout.strip()
        match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def generate_apps_table(
    releases_db: dict[str, Any],
    status_db: dict[str, Any],
    apps_config: list[dict[str, Any]],
) -> str:
    """Generate the markdown table for all synced apps.

    Returns the table as a string (without markers).
    """
    mirror_repo = _get_mirror_repo()

    lines = [
        "",
        "## 📦 APK Downloads",
        "",
        "> Automatically synced from upstream GitHub releases. APKs are unmodified.",
        "",
        "| App | Developer | Version | Updated | APK | Source |",
        "|:---|:---|:---|:---|:---|:---|",
    ]

    has_entries = False

    for app in sorted(apps_config, key=lambda a: a.get("name", "").lower()):
        slug = app.get("slug", "")
        if not app.get("enabled", True):
            continue

        release_entry = releases_db.get(slug)
        status_entry = status_db.get(slug)

        if not release_entry:
            continue

        has_entries = True
        name = app.get("name", slug)
        repo = app.get("repository", "")
        owner = repo.split("/")[0] if "/" in repo else "Unknown"
        version = release_entry.get("source_tag", "unknown")
        synced_at = release_entry.get("synced_at", "")
        updated = synced_at[:10] if synced_at else "—"
        mirror_tag = release_entry.get("mirror_release_tag", "")

        # Download link
        if mirror_repo and mirror_tag:
            download_url = f"https://github.com/{mirror_repo}/releases/tag/{mirror_tag}"
            download_link = f"[⬇️ Download]({download_url})"
        else:
            download_link = "—"

        # Source link
        source_url = f"https://github.com/{repo}"
        source_link = f"[GitHub]({source_url})"

        lines.append(
            f"| **{name}** | {owner} | `{version}` | {updated} | {download_link} | {source_link} |"
        )

    if not has_entries:
        lines.append("| _No APKs synced yet._ | — | — | — | — | — |")

    lines.append("")
    return "\n".join(lines)


def update_readme(
    releases_db: dict[str, Any],
    status_db: dict[str, Any],
    apps_config: list[dict[str, Any]],
) -> bool:
    """Update the README.md with the auto-generated apps table.

    Only modifies content between the START and END markers.
    Returns True if the README was changed.
    """
    if not README_PATH.exists():
        logger.warning("README.md not found at %s", README_PATH)
        return False

    content = README_PATH.read_text(encoding="utf-8")

    if START_MARKER not in content or END_MARKER not in content:
        logger.warning("Auto-generation markers not found in README.md")
        return False

    start_idx = content.index(START_MARKER) + len(START_MARKER)
    end_idx = content.index(END_MARKER)

    table = generate_apps_table(releases_db, status_db, apps_config)

    new_content = content[:start_idx] + "\n" + table + content[end_idx:]

    if new_content == content:
        logger.info("README.md is already up-to-date.")
        return False

    README_PATH.write_text(new_content, encoding="utf-8")
    logger.info("README.md updated with latest APK download table.")
    return True
