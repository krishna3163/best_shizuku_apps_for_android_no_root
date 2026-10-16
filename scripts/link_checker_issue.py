"""Automated Broken Link & 404 Auto-Issue Creator.

Checks all URLs in README.md, records their line numbers, tests their HTTP status,
and automatically opens or updates a GitHub issue when broken links are detected.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("link-checker")
ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
GITHUB_API_BASE = "https://api.github.com"


def find_urls_with_lines(file_path: Path) -> list[dict[str, Any]]:
    """Extract all HTTP/HTTPS URLs with line numbers from markdown file."""
    items = []
    content = file_path.read_text(encoding="utf-8")
    url_pattern = re.compile(r"https?://[^\s)\]\"'>]+")

    for line_idx, line in enumerate(content.splitlines(), start=1):
        for match in url_pattern.finditer(line):
            url = match.group(0).rstrip(".,;")
            items.append({"url": url, "line": line_idx, "context": line.strip()[:80]})
    return items


def check_url(item: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    """Test URL reachability."""
    url = item["url"]
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 ShizukuLinkCheck/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urlopen(req, timeout=timeout) as resp:
            status = resp.status
            return {**item, "ok": True, "status": status, "error": None}
    except HTTPError as exc:
        # Ignore 429 / 403 bot blocks (e.g., Telegram, Reddit, LinkedIn, XDA) as false positives
        is_hard_404 = exc.code in {404, 410, 502, 503}
        return {
            **item,
            "ok": not is_hard_404,
            "status": exc.code,
            "error": f"HTTP {exc.code} {exc.reason}",
            "is_dead": is_hard_404,
        }
    except Exception as exc:
        return {
            **item,
            "ok": False,
            "status": 0,
            "error": str(exc),
            "is_dead": True,
        }


def check_all_links(file_path: Path, max_workers: int = 8, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Check all links concurrently."""
    items = find_urls_with_lines(file_path)
    if limit:
        items = items[:limit]

    # Deduplicate checking while keeping line references
    unique_urls = {}
    for item in items:
        unique_urls.setdefault(item["url"], []).append(item["line"])

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_url, {"url": url, "line": lines[0]}): (url, lines) for url, lines in unique_urls.items()}
        for future in as_completed(futures):
            res = future.result()
            url, lines = futures[future]
            res["lines"] = lines
            results.append(res)

    return results


def format_issue_body(broken_links: list[dict[str, Any]]) -> str:
    """Format a GitHub issue description with broken link details."""
    lines = [
        "## 🚨 Automated Broken Link & 404 Report",
        "",
        "The automated weekly link checker detected unreachable URLs or dead repositories in `README.md`.",
        "",
        "| Status | URL | Line Numbers | Error |",
        "|:---|:---|:---|:---|",
    ]
    for b in broken_links:
        line_refs = ", ".join(f"`L{ln}`" for ln in b.get("lines", [b.get("line")]))
        lines.append(f"| `{b.get('status', 'ERR')}` | {b['url']} | {line_refs} | {b.get('error', '')} |")

    lines.extend([
        "",
        "### 🛠️ Suggested Actions",
        "- Verify if the repository was renamed or moved.",
        "- Update the link in `README.md` or mark the app as archived/unlisted.",
        "- Close this issue once fixed.",
        "",
        "_Reported automatically by `.github/workflows/weekly-link-check.yml`_",
    ])
    return "\n".join(lines)


def create_or_update_issue(broken_links: list[dict[str, Any]], repo_slug: str, token: str) -> None:
    """Create a new GitHub issue or update an existing open one."""
    if not broken_links or not token:
        return

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Shizuku-Link-Checker/1.0",
    }

    issue_title = "🚨 [Automated] Broken Links / 404 Detected in README.md"
    body = format_issue_body(broken_links)

    # Check for existing open issue
    list_url = f"{GITHUB_API_BASE}/repos/{repo_slug}/issues?state=open"
    req = Request(list_url, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            issues = json.load(resp)
            for iss in issues:
                if iss.get("title") == issue_title:
                    logger.info("Found existing issue #%s, updating with latest scan...", iss["number"])
                    patch_url = f"{GITHUB_API_BASE}/repos/{repo_slug}/issues/{iss['number']}"
                    patch_req = Request(patch_url, data=json.dumps({"body": body}).encode("utf-8"), headers=headers, method="PATCH")
                    with urlopen(patch_req, timeout=15) as patch_resp:
                        logger.info("Updated issue #%s successfully.", iss["number"])
                    return

        # Open new issue
        create_url = f"{GITHUB_API_BASE}/repos/{repo_slug}/issues"
        post_req = Request(
            create_url,
            data=json.dumps({"title": issue_title, "body": body, "labels": ["bug", "documentation"]}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(post_req, timeout=15) as post_resp:
            res = json.load(post_resp)
            logger.info("Created new issue #%s successfully.", res.get("number"))
    except Exception as exc:
        logger.warning("Failed to create or update GitHub issue: %s", exc)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Check broken links and optionally create GitHub issue.")
    parser.add_argument("--create-issue", action="store_true", help="Create GitHub issue if broken links found")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "krishna3163/best_shizuku_apps_for_android_no_root"))
    parser.add_argument("--limit", type=int, help="Limit number of URLs to check (for testing)")
    args = parser.parse_args()

    results = check_all_links(README_PATH, limit=args.limit)
    broken = [r for r in results if r.get("is_dead")]

    print(f"Checked {len(results)} URLs; {len(broken)} broken links detected.")
    if broken:
        for b in broken:
            print(f"  ❌ Line {b['line']}: {b['url']} -> {b.get('error')}")

        if args.create_issue:
            token = os.environ.get("GITHUB_TOKEN", "").strip()
            create_or_update_issue(broken, args.repo, token)
        return 1

    print("✅ All checked links are healthy!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
