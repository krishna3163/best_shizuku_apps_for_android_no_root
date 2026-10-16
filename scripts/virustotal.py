"""Automated VirusTotal / Malware Scan on Synced APKs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from .apk import calculate_sha256
except ImportError:
    from apk import calculate_sha256

logger = logging.getLogger("virustotal")
VT_API_BASE = "https://www.virustotal.com/api/v3"


def get_file_report(sha256: str, api_key: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Query VirusTotal API v3 for an existing file report by SHA-256.

    Returns the analysis stats dict if found, or None if not found or no API key.
    """
    key = api_key or os.environ.get("VIRUSTOTAL_API_KEY", "").strip()
    if not key:
        logger.debug("No VIRUSTOTAL_API_KEY provided; skipping live API query.")
        return None

    url = f"{VT_API_BASE}/files/{sha256}"
    request = Request(
        url,
        headers={
            "x-apikey": key,
            "Accept": "application/json",
            "User-Agent": "Shizuku-Mirror-VirusTotal/1.0",
        },
    )

    try:
        with urlopen(request, timeout=15) as resp:
            data = json.load(resp)
            return data.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
    except HTTPError as exc:
        if exc.code == 404:
            logger.info("File hash %s not yet analyzed on VirusTotal.", sha256)
        else:
            logger.warning("VirusTotal API error: HTTP %s: %s", exc.code, exc.reason)
        return None
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Failed to connect to VirusTotal API: %s", exc)
        return None


def generate_vt_badge(sha256: str, stats: Optional[dict[str, Any]] = None) -> str:
    """Generate a Markdown badge for VirusTotal detection status."""
    vt_url = f"https://www.virustotal.com/gui/file/{sha256}"
    if not stats:
        return f"[![VirusTotal](https://img.shields.io/badge/VirusTotal-Scan%20Report-blue?style=flat&logo=virustotal)]({vt_url})"

    malicious = stats.get("malicious", 0)
    suspicious = stats.get("suspicious", 0)
    total = sum(stats.values()) or 70

    if malicious == 0 and suspicious == 0:
        color = "brightgreen"
        text = f"0%2F{total}%20Clean"
    elif malicious <= 1:
        color = "yellow"
        text = f"{malicious}%2F{total}%20Notice"
    else:
        color = "red"
        text = f"{malicious}%2F{total}%20Warning"

    return f"[![VirusTotal](https://img.shields.io/badge/VirusTotal-{text}-{color}?style=flat&logo=virustotal)]({vt_url})"


def generate_vt_summary(sha256: str, stats: Optional[dict[str, Any]] = None) -> str:
    """Generate a markdown report section for the release body."""
    vt_url = f"https://www.virustotal.com/gui/file/{sha256}"
    lines = [
        "### 🛡️ VirusTotal Safety Inspection",
        "",
        f"- **SHA-256:** `{sha256}`",
    ]
    if stats:
        malicious = stats.get("malicious", 0)
        harmless = stats.get("harmless", 0)
        undetected = stats.get("undetected", 0)
        total = sum(stats.values()) or (malicious + harmless + undetected)
        status_text = "✅ 0 Detections (Clean)" if malicious == 0 else f"⚠️ {malicious} Detection(s)"
        lines.extend([
            f"- **Detection Ratio:** `{malicious}/{total}` vendors",
            f"- **Status:** {status_text}",
        ])
    else:
        lines.append("- **Status:** 🔍 Hash submitted for community scanning")

    lines.extend([
        f"- **Official Scan Report:** [View on VirusTotal]({vt_url})",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Check an APK or SHA-256 hash on VirusTotal.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--hash", help="SHA-256 hash to check")
    group.add_argument("--file", help="Path to APK file to inspect")
    parser.add_argument("--api-key", help="VirusTotal API Key (or set VIRUSTOTAL_API_KEY env)")
    parser.add_argument("--badge-only", action="store_true", help="Print only markdown badge")

    args = parser.parse_args()

    sha256 = args.hash
    if args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"File not found: {args.file}", file=sys.stderr)
            return 1
        sha256 = calculate_sha256(str(path))

    stats = get_file_report(sha256, api_key=args.api_key)

    if args.badge_only:
        print(generate_vt_badge(sha256, stats))
    else:
        print(generate_vt_summary(sha256, stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
