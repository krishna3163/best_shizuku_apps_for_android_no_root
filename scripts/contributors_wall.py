"""Dynamic Stargazers & Contributors Wall Generator.

Generates a pure vector assets/contributors.svg with zero external image dependencies,
ensuring 100% compatibility with GitHub's strict SVG image sanitizer.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

logger = logging.getLogger("contributors-wall")
ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"
SVG_PATH = ASSETS_DIR / "contributors.svg"

GRADIENT_PALETTES = [
    ("#3B82F6", "#1D4ED8"),  # Blue
    ("#8B5CF6", "#6D28D9"),  # Purple
    ("#EC4899", "#BE185D"),  # Pink
    ("#10B981", "#047857"),  # Emerald
    ("#F59E0B", "#B45309"),  # Amber
    ("#06B6D4", "#0E7490"),  # Cyan
    ("#6366F1", "#4338CA"),  # Indigo
]


def fetch_contributors(repo_slug: str, token: Optional[str] = None) -> list[dict[str, Any]]:
    """Fetch contributors list from GitHub API."""
    token = token or os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Shizuku-Contributors-Wall/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repo_slug}/contributors?per_page=100"
    req = Request(url, headers=headers)

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.load(resp)
            if isinstance(data, list) and data:
                return data
    except Exception as exc:
        logger.warning("Could not fetch contributors from GitHub: %s", exc)

    return [
        {"login": "krishna3163", "contributions": 120, "role": "Maintainer"},
        {"login": "RikkaApps", "contributions": 50, "role": "Shizuku Creator"},
        {"login": "timschneeb", "contributions": 30, "role": "Catalog Contributor"},
        {"login": "samolego", "contributions": 25, "role": "Canta Developer"},
    ]


def get_initials(login: str) -> str:
    """Generate 1-2 character monogram for avatar circle."""
    clean = login.replace("-", " ").replace("_", " ").strip()
    parts = clean.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return login[:2].upper() if len(login) >= 2 else login[:1].upper()


def generate_svg(contributors: list[dict[str, Any]]) -> str:
    """Generate 100% pure vector SVG with no external raster or HTTP images."""
    if not contributors:
        contributors = [
            {"login": "krishna3163", "contributions": 120, "role": "Maintainer"},
            {"login": "RikkaApps", "contributions": 50, "role": "Shizuku Creator"},
            {"login": "timschneeb", "contributions": 30, "role": "Catalog Contributor"},
            {"login": "samolego", "contributions": 25, "role": "Canta Developer"},
        ]

    card_width = 820
    chip_width = 180
    chip_height = 64
    gap_x = 16
    gap_y = 16
    start_x = 24
    start_y = 80
    cols = 4

    rows = (len(contributors) + cols - 1) // cols
    card_height = max(180, start_y + (rows * (chip_height + gap_y)) + 16)

    # Build gradient definitions
    defs = ["  <defs>"]
    for idx, (c1, c2) in enumerate(GRADIENT_PALETTES):
        defs.append(f"""    <linearGradient id="grad-{idx}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{c1}"/>
      <stop offset="100%" stop-color="{c2}"/>
    </linearGradient>""")
    defs.append("  </defs>")

    svg = [
        f'<svg xmlns="http://www.w3.org/2005/svg" width="{card_width}" height="{card_height}" viewBox="0 0 {card_width} {card_height}" fill="none">',
        '  <style>',
        '    .title { font: 700 18px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; fill: #0f172a; }',
        '    .subtitle { font: 400 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; fill: #64748b; }',
        '    .chip-bg { fill: #f8fafc; stroke: #e2e8f0; stroke-width: 1px; rx: 12px; }',
        '    .chip-name { font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; fill: #1e293b; }',
        '    .chip-role { font: 400 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; fill: #64748b; }',
        '    .avatar-text { font: 700 15px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; fill: #ffffff; text-anchor: middle; dominant-baseline: central; }',
        '    @media (prefers-color-scheme: dark) {',
        '      .title { fill: #f8fafc; }',
        '      .subtitle { fill: #94a3b8; }',
        '      .chip-bg { fill: #1e293b; stroke: #334155; }',
        '      .chip-name { fill: #f8fafc; }',
        '      .chip-role { fill: #94a3b8; }',
        '    }',
        '  </style>',
        "\n".join(defs),
        f'  <rect width="{card_width}" height="{card_height}" rx="16" fill="#ffffff" fill-opacity="0.04" stroke="#cbd5e1" stroke-width="1"/>',
        '  <text x="24" y="38" class="title">👥 Project Contributors &amp; Community Heroes</text>',
        f'  <text x="24" y="58" class="subtitle">Thank you to everyone helping curate, build, and support the Android Shizuku ecosystem! ({len(contributors)} contributors)</text>',
    ]

    for idx, c in enumerate(contributors):
        col = idx % cols
        row = idx // cols
        x = start_x + col * (chip_width + gap_x)
        y = start_y + row * (chip_height + gap_y)

        login = html.escape(c.get("login", "user"))
        role = c.get("role")
        if not role:
            count = c.get("contributions", 1)
            role = "Maintainer" if login.lower() == "krishna3163" else f"{count} contributions"

        grad_idx = idx % len(GRADIENT_PALETTES)
        initials = html.escape(get_initials(login))

        avatar_cx = x + 26
        avatar_cy = y + (chip_height // 2)

        svg.extend([
            f'  <a href="https://github.com/{login}" target="_blank">',
            f'    <rect x="{x}" y="{y}" width="{chip_width}" height="{chip_height}" class="chip-bg" />',
            f'    <circle cx="{avatar_cx}" cy="{avatar_cy}" r="18" fill="url(#grad-{grad_idx})"/>',
            f'    <text x="{avatar_cx}" y="{avatar_cy}" class="avatar-text">{initials}</text>',
            f'    <text x="{x + 52}" y="{y + 26}" class="chip-name">{login[:14]}</text>',
            f'    <text x="{x + 52}" y="{y + 44}" class="chip-role">{role[:18]}</text>',
            f'  </a>',
        ])

    svg.append("</svg>")
    return "\n".join(svg)


def update_contributors_wall(repo_slug: str, token: Optional[str] = None) -> Path:
    """Fetch contributors and save clean vector SVG."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    contributors = fetch_contributors(repo_slug, token=token)
    svg_content = generate_svg(contributors)
    SVG_PATH.write_text(svg_content, encoding="utf-8")
    return SVG_PATH


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Generate pure vector contributors wall SVG.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "krishna3163/best_shizuku_apps_for_android_no_root"))
    parser.add_argument("--token", help="GitHub API Token")
    args = parser.parse_args()

    out = update_contributors_wall(args.repo, token=args.token)
    print(f"✅ Generated clean vector contributors wall at {out}")
    return 0


if __name__ == "__main__":
    main()
