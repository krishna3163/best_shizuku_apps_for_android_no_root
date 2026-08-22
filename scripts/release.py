"""Release detection, selection, and mirror-release generation."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger("apk-sync")


# Valid release strategies
VALID_STRATEGIES = {"latest", "latest-stable", "latest-prerelease", "latest-any"}


def pick_release(
    releases: list[dict[str, Any]],
    strategy: str = "latest-stable",
) -> Optional[dict[str, Any]]:
    """Select the appropriate release based on *strategy*.

    ``latest-stable``  → first non-draft, non-prerelease release
    ``latest``         → alias for latest-stable
    ``latest-prerelease`` → first non-draft prerelease
    ``latest-any``     → first non-draft release regardless of prerelease flag
    """
    if strategy not in VALID_STRATEGIES:
        logger.warning("Unknown strategy '%s', defaulting to 'latest-stable'.", strategy)
        strategy = "latest-stable"

    for release in releases:
        # Always skip drafts
        if release.get("draft", False):
            continue

        is_prerelease = release.get("prerelease", False)

        if strategy in ("latest", "latest-stable"):
            if not is_prerelease:
                return release
        elif strategy == "latest-prerelease":
            if is_prerelease:
                return release
        elif strategy == "latest-any":
            return release

    return None


def extract_version(release: dict[str, Any]) -> str:
    """Extract a version string from a release.

    Prefers ``tag_name``, falls back to ``name``, then ``id``.
    """
    tag = release.get("tag_name", "").strip()
    if tag:
        return tag

    name = release.get("name", "").strip()
    if name:
        # Try to find a version-like pattern in the name
        match = re.search(r"v?\d+[\d.]+", name)
        if match:
            return match.group(0)
        return name

    return f"release-{release.get('id', 'unknown')}"


def make_mirror_tag(slug: str, version: str) -> str:
    """Generate a safe Git tag for the mirrored release.

    Format: ``<slug>-<version>``
    """
    # Clean up version
    version = version.strip()
    # Remove unsafe characters for Git tags
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", version)
    safe = re.sub(r"-+", "-", safe).strip("-")

    tag = f"{slug}-{safe}"
    return tag


def make_release_title(app_name: str, version: str) -> str:
    """Generate a human-readable release title."""
    return f"{app_name} {version}"


def generate_release_body(
    app_name: str,
    version: str,
    source_repo: str,
    source_tag: str,
    assets_info: list[dict[str, Any]],
    license_info: str = "",
) -> str:
    """Generate a structured release description with full attribution."""
    source_url = f"https://github.com/{source_repo}"
    release_url = f"{source_url}/releases/tag/{source_tag}"

    body_lines = [
        f"# {app_name} {version}",
        "",
        "Automatically synchronized from the original GitHub repository.",
        "",
        "## Source",
        "",
        f"- **Original repository:** [{source_repo}]({source_url})",
        f"- **Original release:** [{source_tag}]({release_url})",
        "",
        "## Version",
        "",
        f"`{version}`",
        "",
    ]

    # APK details
    if assets_info:
        body_lines.append("## APK Assets")
        body_lines.append("")
        for asset in assets_info:
            filename = asset.get("filename", "unknown")
            sha256 = asset.get("sha256", "unknown")
            arch = asset.get("architecture", "unknown")
            size = asset.get("file_size", 0)
            size_str = f"{size / 1024 / 1024:.1f} MB" if size else "unknown"

            body_lines.append(f"### {filename}")
            body_lines.append("")
            body_lines.append(f"- **Architecture:** {arch}")
            body_lines.append(f"- **Size:** {size_str}")
            body_lines.append(f"- **SHA-256:** `{sha256}`")
            body_lines.append("")

    # License
    if license_info:
        body_lines.extend([
            "## License",
            "",
            f"{license_info}",
            "",
        ])

    # Disclaimer
    body_lines.extend([
        "## Important",
        "",
        "This repository mirrors the original APK for easier access. "
        "The APK is distributed **without modification**. "
        "Please refer to the original project for source code, license, "
        "release notes, and developer information.",
        "",
        f"🔗 [Visit original project]({source_url})",
    ])

    return "\n".join(body_lines)
