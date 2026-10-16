"""Automated Abandonment & Archived Repo Detector.

Queries GitHub API for listed repositories to check if a repo was archived,
deleted, or has had no commits in >2 years.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("archive-detector")
ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "apps.json"
README_FILE = ROOT / "README.md"
GITHUB_API_BASE = "https://api.github.com"


def extract_github_repos_from_text(content: str) -> set[str]:
    """Extract all owner/repo pairs from markdown text."""
    pattern = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
    repos = set()
    for match in pattern.finditer(content):
        owner, repo = match.group(1), match.group(2)
        # Exclude special github pages or user-level URLs
        if owner.lower() in {"topics", "features", "pricing", "marketplace"}:
            continue
        repo = repo.rstrip("/").rstrip(".git")
        repos.add(f"{owner}/{repo}")
    return repos


def load_tracked_repos() -> list[str]:
    """Collect unique repos from config/apps.json and README.md."""
    repos = set()
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for app in data.get("apps", []):
                source = (app.get("repository") or app.get("source_repo") or "").strip()
                if source and "/" in source:
                    repos.add(source)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", CONFIG_FILE, exc)

    if README_FILE.exists():
        content = README_FILE.read_text(encoding="utf-8")
        repos.update(extract_github_repos_from_text(content))

    return sorted(repos)


def inspect_repository(repo_slug: str, token: Optional[str] = None) -> dict[str, Any]:
    """Query GitHub API for repository metadata."""
    token = token or os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Shizuku-Archive-Detector/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{GITHUB_API_BASE}/repos/{repo_slug}"
    req = Request(url, headers=headers)

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.load(resp)
            pushed_at_str = data.get("pushed_at")
            is_archived = bool(data.get("archived", False))
            days_inactive = -1
            if pushed_at_str:
                pushed_dt = datetime.datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
                days_inactive = (datetime.datetime.now(datetime.timezone.utc) - pushed_dt).days

            return {
                "repo": repo_slug,
                "status": "active" if not is_archived and days_inactive < 730 else ("archived" if is_archived else "stale"),
                "archived": is_archived,
                "stars": data.get("stargazers_count", 0),
                "pushed_at": pushed_at_str,
                "days_inactive": days_inactive,
                "description": data.get("description") or "",
                "license": (data.get("license") or {}).get("spdx_id") or "Unknown",
            }
    except HTTPError as exc:
        if exc.code == 404:
            return {"repo": repo_slug, "status": "deleted_or_moved", "error": "HTTP 404"}
        return {"repo": repo_slug, "status": "error", "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"repo": repo_slug, "status": "error", "error": str(exc)}


def run_detector(max_repos: Optional[int] = None, token: Optional[str] = None) -> dict[str, Any]:
    """Scan repositories and generate summary."""
    repos = load_tracked_repos()
    if max_repos:
        repos = repos[:max_repos]

    results = []
    archived = []
    stale = []
    deleted = []

    for repo in repos:
        info = inspect_repository(repo, token=token)
        results.append(info)
        status = info.get("status")
        if status == "archived":
            archived.append(info)
        elif status == "stale":
            stale.append(info)
        elif status == "deleted_or_moved":
            deleted.append(info)

    return {
        "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_scanned": len(results),
        "archived_count": len(archived),
        "stale_count": len(stale),
        "deleted_count": len(deleted),
        "archived": archived,
        "stale": stale,
        "deleted": deleted,
        "details": results,
    }


def generate_markdown_report(report: dict[str, Any]) -> str:
    """Generate human-readable markdown report."""
    lines = [
        "# 🛡️ Repository Health & Abandonment Report",
        "",
        f"- **Generated:** `{report['scanned_at']}`",
        f"- **Total Scanned:** {report['total_scanned']}",
        f"- **Archived:** {report['archived_count']}",
        f"- **Inactive (>2 yrs):** {report['stale_count']}",
        f"- **Deleted / 404:** {report['deleted_count']}",
        "",
    ]

    if report["archived"]:
        lines.extend([
            "## 📦 Archived Upstream Repositories",
            "",
            "| Repository | Stars | Last Push | License |",
            "|:---|:---|:---|:---|",
        ])
        for r in report["archived"]:
            lines.append(f"| [{r['repo']}](https://github.com/{r['repo']}) | {r.get('stars', 0)} | {r.get('pushed_at', '')[:10]} | {r.get('license', 'Unknown')} |")
        lines.append("")

    if report["deleted"]:
        lines.extend([
            "## ⚠️ Deleted or Renamed (404) Repositories",
            "",
            "| Repository | Error |",
            "|:---|:---|",
        ])
        for r in report["deleted"]:
            lines.append(f"| [{r['repo']}](https://github.com/{r['repo']}) | {r.get('error', '404')} |")
        lines.append("")

    if report["stale"]:
        lines.extend([
            "## ⏳ Inactive Repositories (>2 Years)",
            "",
            "| Repository | Days Inactive | Last Push |",
            "|:---|:---|:---|",
        ])
        for r in report["stale"]:
            lines.append(f"| [{r['repo']}](https://github.com/{r['repo']}) | {r.get('days_inactive')} | {r.get('pushed_at', '')[:10]} |")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Scan tracked repos for archival and abandonment.")
    parser.add_argument("--output-json", help="Path to save output JSON")
    parser.add_argument("--output-md", help="Path to save markdown report")
    parser.add_argument("--limit", type=int, help="Limit number of scanned repos (for testing)")
    args = parser.parse_args()

    report = run_detector(max_repos=args.limit)

    if args.output_json:
        out_p = Path(args.output_json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote JSON report to {args.output_json}")

    if args.output_md:
        out_p = Path(args.output_md)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(generate_markdown_report(report), encoding="utf-8")
        print(f"Wrote Markdown report to {args.output_md}")

    if not args.output_json and not args.output_md:
        print(generate_markdown_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
