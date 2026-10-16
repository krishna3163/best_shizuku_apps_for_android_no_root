"""App Suggestion Issue-to-PR Automation Bot.

Parses issue body from app-suggestion.yml, validates repo, and updates config/apps.json
and README.md to prepare automated pull requests.
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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

logger = logging.getLogger("issue-to-pr")
ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
CONFIG_PATH = ROOT / "config" / "apps.json"


def parse_issue_form(body: str) -> dict[str, str]:
    """Extract form values from GitHub issue body text."""
    fields = {}

    patterns = {
        "name": r"### App name\s*\n\s*([^\n\r#]+)",
        "link": r"### Official project or app link\s*\n\s*([^\n\r#]+)",
        "license": r"### License\s*\n\s*([^\n\r#]+)",
        "description": r"### Description and Shizuku use case\s*\n\s*([\s\S]+?)(?=\n###|\Z)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            fields[key] = match.group(1).strip()
        else:
            fields[key] = ""

    return fields


def validate_and_fetch_repo_info(url: str, token: Optional[str] = None) -> dict[str, Any]:
    """If URL is a GitHub repo, fetch metadata from GitHub API."""
    match = re.search(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", url)
    if not match:
        return {"is_github": False, "url": url}

    owner, repo = match.group(1), match.group(2).rstrip("/").rstrip(".git")
    slug = f"{owner}/{repo}"

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Shizuku-Issue-To-PR/1.0"}
    token = token or os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = f"https://api.github.com/repos/{slug}"
    req = Request(api_url, headers=headers)

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.load(resp)
            license_id = (data.get("license") or {}).get("spdx_id") or "Open Source"
            if license_id == "NOASSERTION":
                license_id = "Open Source"

            return {
                "is_github": True,
                "owner": owner,
                "repo": repo,
                "slug": slug,
                "stars": data.get("stargazers_count", 0),
                "description": data.get("description") or "",
                "license": license_id,
                "archived": data.get("archived", False),
                "url": f"https://github.com/{slug}",
            }
    except Exception as exc:
        logger.warning("Could not fetch info for %s: %s", slug, exc)
        return {"is_github": True, "slug": slug, "url": f"https://github.com/{slug}"}


def add_suggestion_to_catalog(data: dict[str, str], token: Optional[str] = None) -> tuple[bool, str]:
    """Add validated app to config/apps.json and README.md."""
    name = data.get("name")
    link = data.get("link")
    desc = data.get("description")
    license_val = data.get("license") or "Open Source"

    if not name or not link:
        return False, "Missing required fields (name or link)"

    repo_info = validate_and_fetch_repo_info(link, token=token)
    if repo_info.get("archived"):
        return False, f"Repository {link} is archived upstream."

    app_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    # Update config/apps.json if GitHub repo
    if repo_info.get("is_github") and repo_info.get("slug"):
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            existing = {a.get("slug") for a in config.get("apps", [])}
            if app_slug not in existing:
                config["apps"].append({
                    "slug": app_slug,
                    "name": name,
                    "repository": repo_info["slug"],
                    "asset_patterns": [r"(?i).*\.apk$"],
                    "release_strategy": "latest-stable",
                })
                CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
                logger.info("Added %s to config/apps.json", app_slug)
        except Exception as exc:
            logger.warning("Failed to update config/apps.json: %s", exc)

    # Insert into README.md
    readme_content = README_PATH.read_text(encoding="utf-8")
    clean_desc = desc.replace("|", "\\|")
    table_row = f"| **[{name}]({link})** | {clean_desc} | `{license_val}` | [GitHub]({link}) |"

    # Avoid duplicate
    if f"[{name}]" in readme_content:
        return True, f"App {name} already exists in README.md"

    # Insert into Miscellaneous content table
    target_header = "### Miscellaneous content"
    if target_header in readme_content:
        idx = readme_content.index(target_header)
        # Find the table header after target_header
        table_start = readme_content.find("|:---|", idx)
        if table_start != -1:
            line_end = readme_content.find("\n", table_start) + 1
            new_content = readme_content[:line_end] + table_row + "\n" + readme_content[line_end:]
            README_PATH.write_text(new_content, encoding="utf-8")
            return True, f"Successfully added {name} to catalog!"

    return True, f"Parsed {name}, but please specify category location manually."


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse app suggestion issue and update catalog.")
    parser.add_argument("--issue-body-file", help="Path to file containing issue body markdown")
    parser.add_argument("--issue-body", help="Issue body string")
    parser.add_argument("--token", help="GitHub token")
    args = parser.parse_args()

    body = args.issue_body or ""
    if args.issue_body_file:
        body = Path(args.issue_body_file).read_text(encoding="utf-8")
    elif not body:
        body = os.environ.get("ISSUE_BODY", "")

    if not body:
        print("Empty issue body.", file=sys.stderr)
        return 1

    parsed = parse_issue_form(body)
    success, msg = add_suggestion_to_catalog(parsed, token=args.token)
    print(f"Result: {msg}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
