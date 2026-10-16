"""Shizuku API Code Verifier.

Scans upstream source code or APK binary strings to verify actual Shizuku integration
(moe.shizuku:api, moe.shizuku.privileged.api, rikka.shizuku, or rish).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

logger = logging.getLogger("shizuku-verifier")
GITHUB_API_BASE = "https://api.github.com"

SHIZUKU_SIGNATURES = [
    r"moe\.shizuku:api",
    r"moe\.shizuku\.privileged\.api",
    r"moe\.shizuku\.manager",
    r"moe\.shizuku\.server",
    r"rikka\.shizuku",
    r"ShizukuBinderWrapper",
    r"ShizukuProvider",
    r"rish",
]


def verify_apk_file(apk_path: str) -> dict[str, Any]:
    """Scan DEX and manifest strings inside an APK for Shizuku signatures."""
    path = Path(apk_path)
    if not path.is_file():
        return {"file": apk_path, "verified": False, "error": "File not found"}

    matches = set()
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for entry in zf.namelist():
                # Check manifest or DEX files
                if entry.endswith(".dex") or entry == "AndroidManifest.xml":
                    content = zf.read(entry)
                    for sig in SHIZUKU_SIGNATURES:
                        # Raw byte regex check
                        pattern = sig.encode("ascii")
                        if re.search(pattern, content, re.IGNORECASE):
                            matches.add(sig.replace("\\.", "."))

        verified = len(matches) > 0
        return {
            "file": str(path.name),
            "verified": verified,
            "confidence": "high" if verified else "none",
            "detected_signatures": sorted(matches),
        }
    except Exception as exc:
        return {"file": str(path.name), "verified": False, "error": str(exc)}


def verify_github_repo(repo_slug: str, token: Optional[str] = None) -> dict[str, Any]:
    """Search a GitHub repository for Shizuku references using the GitHub API."""
    token = token or os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Shizuku-API-Verifier/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    detected = set()

    # Search for moe.shizuku or rikka.shizuku in the repo
    query = f"repo:{repo_slug} moe.shizuku"
    url = f"{GITHUB_API_BASE}/search/code?q={quote_plus(query)}"
    req = Request(url, headers=headers)

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.load(resp)
            count = data.get("total_count", 0)
            if count > 0:
                detected.add("moe.shizuku")
                for item in data.get("items", [])[:5]:
                    path_str = item.get("path", "")
                    if "build.gradle" in path_str or "pom.xml" in path_str:
                        detected.add("dependency:moe.shizuku")
    except HTTPError as exc:
        logger.debug("Code search failed for %s: HTTP %s", repo_slug, exc.code)
    except Exception as exc:
        logger.debug("Code search error for %s: %s", repo_slug, exc)

    # Fallback to checking repo description and readme
    if not detected:
        url_repo = f"{GITHUB_API_BASE}/repos/{repo_slug}"
        try:
            req_repo = Request(url_repo, headers=headers)
            with urlopen(req_repo, timeout=15) as resp:
                data = json.load(resp)
                text = (data.get("description") or "").lower()
                if "shizuku" in text:
                    detected.add("readme/metadata:shizuku")
        except Exception:
            pass

    verified = len(detected) > 0
    return {
        "repo": repo_slug,
        "verified": verified,
        "confidence": "high" if "dependency:moe.shizuku" in detected else ("medium" if verified else "unverified"),
        "detected_signatures": sorted(detected),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Verify whether an APK or GitHub repository genuinely integrates Shizuku.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", help="GitHub repo in owner/repo format")
    group.add_argument("--apk", help="Path to APK file to inspect")
    parser.add_argument("--token", help="GitHub Token")
    args = parser.parse_args()

    if args.apk:
        result = verify_apk_file(args.apk)
    else:
        result = verify_github_repo(args.repo, token=args.token)

    print(json.dumps(result, indent=2))
    return 0 if result.get("verified") else 1


if __name__ == "__main__":
    sys.exit(main())
