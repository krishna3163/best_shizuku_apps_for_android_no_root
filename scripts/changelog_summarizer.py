"""Auto-Generated Upstream Changelog Summarizer.

Fetches and formats release notes from upstream GitHub releases for inclusion in mirrored releases.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

logger = logging.getLogger("changelog-summarizer")
GITHUB_API_BASE = "https://api.github.com"


def clean_markdown_changelog(raw_text: str, max_length: int = 3000) -> str:
    """Clean and sanitize raw release notes."""
    if not raw_text or not raw_text.strip():
        return "_No upstream release notes provided for this version._"

    text = raw_text.strip()

    # Normalize carriage returns
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove excessive repeated blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Truncate if exceptionally long
    if len(text) > max_length:
        text = text[:max_length] + "\n\n... _(Release notes truncated. View full changelog upstream)_"

    return text


def fetch_upstream_release_notes(repo_slug: str, tag: str, token: Optional[str] = None) -> str:
    """Fetch release notes for a specific tag from GitHub API."""
    token = token or os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Shizuku-Changelog-Summarizer/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{GITHUB_API_BASE}/repos/{repo_slug}/releases/tags/{tag}"
    req = Request(url, headers=headers)

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.load(resp)
            return clean_markdown_changelog(data.get("body", ""))
    except HTTPError as exc:
        if exc.code == 404:
            # Fallback to latest release if tag is custom
            try:
                latest_url = f"{GITHUB_API_BASE}/repos/{repo_slug}/releases/latest"
                with urlopen(Request(latest_url, headers=headers), timeout=15) as l_resp:
                    l_data = json.load(l_resp)
                    return clean_markdown_changelog(l_data.get("body", ""))
            except Exception:
                pass
        return "_Could not retrieve release notes from upstream repository._"
    except Exception as exc:
        logger.warning("Failed to fetch release notes: %s", exc)
        return "_Release notes unavailable._"


def format_changelog_section(version: str, notes: str) -> str:
    """Wrap changelog in a collapsible Markdown block."""
    cleaned = clean_markdown_changelog(notes)
    return (
        f"## 📝 What's New in {version} (Upstream Changelog)\n\n"
        f"<details open>\n"
        f"<summary>Click to view release notes</summary>\n\n"
        f"{cleaned}\n\n"
        f"</details>\n"
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Fetch and format upstream release notes.")
    parser.add_argument("--repo", required=True, help="Upstream repo (owner/repo)")
    parser.add_argument("--tag", required=True, help="Release tag name")
    parser.add_argument("--token", help="GitHub Token")
    args = parser.parse_args()

    notes = fetch_upstream_release_notes(args.repo, args.tag, token=args.token)
    print(format_changelog_section(args.tag, notes))
    return 0


if __name__ == "__main__":
    main()
