"""Morphe Patched Apps Auto-Builder & Synchronization for Non-Root & Shizuku Apps.

Synchronizes community patch bundles from https://morphe-patches.software,
fetches base APKs, builds patched packages using Morphe CLI with microG/GmsCore
support, publishes GitHub releases with version/prerelease/beta tags, replaces
old versions on update, and generates an interactive searchable downloads table in README.md.

Usage:
    python scripts/morphe_sync.py                                 # Sync all enabled Morphe apps
    python scripts/morphe_sync.py --app morphe-youtube-nonroot    # Sync single app
    python scripts/morphe_sync.py --dry-run                       # Check & build without publishing
    python scripts/morphe_sync.py --force-rebuild                 # Force re-generation
    python scripts/morphe_sync.py --channel beta                  # Filter by channel
    python scripts/morphe_sync.py --build-type autobuild          # Filter by build type
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_api import GitHubAPI
from morphe_builder import (
    BaseApkManager,
    MorpheAppConfig,
    MorpheBundleClient,
    MorphePatcher,
)

logger = logging.getLogger("morphe-sync")

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "morphe_apps.json"
DATA_DIR = ROOT / "data"
RELEASES_DB_PATH = DATA_DIR / "morphe-releases.json"
STATUS_DB_PATH = DATA_DIR / "morphe-status.json"
BUNDLES_CACHE_PATH = DATA_DIR / "morphe_bundles_cache.json"
README_PATH = ROOT / "README.md"

START_MARKER = "<!-- MORPHE-AUTOBP-APPS-START -->"
END_MARKER = "<!-- MORPHE-AUTOBP-APPS-END -->"


def setup_logging() -> None:
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        logger.error("Configuration file not found: %s", CONFIG_PATH)
        return {"apps": []}
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_json_db(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        logger.warning("Error reading %s: %s", path, e)
        return {}


def save_json_db(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def get_mirror_repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        return repo
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


def make_morphe_tag(slug: str, version: str, channel: str = "stable") -> str:
    clean_ver = re.sub(r"[^a-zA-Z0-9._-]", "-", version).strip("-")
    if channel in ("beta", "prerelease") and channel not in clean_ver.lower():
        return f"{slug}-{clean_ver}-{channel}"
    return f"{slug}-{clean_ver}"


def generate_morphe_release_body(
    app: MorpheAppConfig,
    version: str,
    bundle_info: Optional[dict[str, Any]],
    sha256: str,
    file_size: int,
    filename: str,
) -> str:
    bundle_repo = app.bundle_repo
    bundle_url = f"https://github.com/{bundle_repo}"
    size_mb = f"{file_size / (1024 * 1024):.2f} MB" if file_size else "unknown"
    patches_list = "\n".join(f"- {p}" for p in app.patches) if app.patches else "- Default recommended patches"

    return (
        f"# {app.name} `{version}` (Non-Root / GmsCore Compatible)\n\n"
        f"Automated build generated with official Morphe community patches from [{bundle_repo}]({bundle_url}).\n\n"
        f"## 🏷️ Release Details\n\n"
        f"- **Application:** `{app.package_name}`\n"
        f"- **Version:** `{version}`\n"
        f"- **Channel:** `{app.channel.upper()}` ({app.build_type})\n"
        f"- **Type:** `{app.app_type}` (No Root Required)\n"
        f"- **Patch Bundle:** [{app.bundle_name or bundle_repo}]({bundle_url})\n\n"
        f"## 🧩 Applied Patches\n\n"
        f"{patches_list}\n\n"
        f"## 📦 Asset Information\n\n"
        f"- **File:** `{filename}`\n"
        f"- **Size:** `{size_mb}`\n"
        f"- **SHA-256:** `{sha256}`\n\n"
        f"## 🚀 Installation Guide\n\n"
        f"- Install APK directly without root.\n"
        f"- For Google Account login in YouTube/YouTube Music, install **GmsCore / microG**.\n\n"
        f"---\n"
        f"*Synced and built automatically based on patch push from [morphe-patches.software](https://morphe-patches.software).* [Report Issue]({bundle_url}/issues)\n"
    )


DOCS_MORPHE_PATH = ROOT / "docs" / "MORPHE.md"
ROOT_MORPHE_PATH = ROOT / "MORPHE.md"
SITE_MORPHE_PATH = ROOT / "site" / "morphe.html"
SITE_INDEX_PATH = ROOT / "site" / "index.html"

FEATURED_SLUGS = {
    "morphe-youtube-nonroot",
    "morphe-youtube-music-nonroot",
    "piko-instagram-nonroot",
    "gboard-patches-nonroot",
    "morphe-spotify-nonroot",
    "morphe-reddit-nonroot",
    "metra-tiktok",
    "hoodles-adguard-nonroot",
    "akash-google-photos-nonroot",
    "doom-cloudflare-nonroot",
}


def generate_morphe_readme_table(
    releases_db: dict[str, Any],
    status_db: dict[str, Any],
    apps_config: list[dict[str, Any]],
) -> str:
    mirror_repo = get_mirror_repo()
    lines = [
        "",
        '<details id="morphe-downloads" open>',
        "<summary><h2>⚡ Morphe Patched Apps & AutoBuilds (Non-Root)</h2></summary>",
        "",
        "> 🚀 **Auto-generated and synchronized based on patch pushes from [morphe-patches.software](https://morphe-patches.software/).**",
        "> No root required! Patched with Morphe community bundles for ad-free streaming, privacy, and background playback.",
        "",
        '<div align="center" class="morphe-navigation-links">',
        "",
        "### 📖 [Browse Full 69+ Apps Catalog (docs/MORPHE.md)](docs/MORPHE.md) • 🌐 [Interactive Web Portal (site/morphe.html)](https://krishna3163.github.io/best_shizuku_apps_for_android_no_root/morphe.html) • 📦 [277 Community Bundles](docs/MORPHE.md#-community-patch-bundles)",
        "",
        "**🔍 Quick Filter by Status:**",
        "[ **All** ](docs/MORPHE.md) • "
        "[ **📦 Release** ](docs/MORPHE.md#-status-filter) • "
        "[ **🚀 AutoBuild** ](docs/MORPHE.md#-status-filter) • "
        "[ **⚡ AutoGenerated** ](docs/MORPHE.md#-status-filter) • "
        "[ **🧪 Beta** ](docs/MORPHE.md#-status-filter) • "
        "[ **🚧 PreRelease** ](docs/MORPHE.md#-status-filter)",
        "",
        "</div>",
        "",
        "### ⭐ Featured Top Builds",
        "",
        "| App | Status / Channel | Version | Bundle Source | Key Patches | Download | SHA-256 | Updated |",
        "|:---|:---|:---|:---|:---|:---|:---|:---|",
    ]

    valid_apps = [a for a in apps_config if a.get("enabled", True) and a.get("slug") in releases_db]
    if len(valid_apps) <= 10:
        display_apps = valid_apps
    else:
        display_apps = [a for a in valid_apps if a.get("slug") in FEATURED_SLUGS]
        if not display_apps:
            display_apps = valid_apps[:8]

    has_entries = False
    for app_raw in sorted(display_apps, key=lambda a: a.get("name", "").lower()):
        slug = app_raw.get("slug", "")
        entry = releases_db.get(slug)
        if not entry:
            continue

        has_entries = True
        name = app_raw.get("name", slug)
        pkg = app_raw.get("package_name", "")
        version = entry.get("version", "latest")
        channel = entry.get("channel", app_raw.get("channel", "stable")).lower()
        build_type = entry.get("build_type", app_raw.get("build_type", "autobuild"))

        if channel == "beta":
            status_badge = "`🧪 Beta` `AutoBuild`"
        elif channel == "prerelease":
            status_badge = "`🚧 PreRelease` `AutoBuild`"
        elif build_type == "autogenerated":
            status_badge = "`⚡ AutoGenerated`"
        elif build_type == "release":
            status_badge = "`📦 Release`"
        else:
            status_badge = "`🚀 AutoBuild`"

        bundle_repo = app_raw.get("bundle_repo", "MorpheApp/morphe-patches")
        bundle_name = app_raw.get("bundle_name") or bundle_repo.split("/")[-1]
        bundle_link = f"[{bundle_name}](https://github.com/{bundle_repo})"

        patches = app_raw.get("patches", [])
        if patches:
            patches_str = "<br>".join(f"• {p}" for p in patches[:2])
            if len(patches) > 2:
                patches_str += f"<br>_and {len(patches)-2} more…_"
        else:
            patches_str = "Default patches"

        mirror_tag = entry.get("release_tag", "")
        if mirror_repo and mirror_tag:
            download_url = f"https://github.com/{mirror_repo}/releases/tag/{mirror_tag}"
            download_link = f"[⬇️ **Download**]({download_url})"
        else:
            download_link = "—"

        sha256 = entry.get("sha256", "")
        sha_str = f"`{sha256[:10]}…`" if sha256 else "—"
        updated_at = entry.get("updated_at", "")[:10] or "—"

        lines.append(
            f"| **{name}**<br><sub>`{pkg}`</sub> | {status_badge} | `{version}` | {bundle_link} | {patches_str} | {download_link} | {sha_str} | {updated_at} |"
        )

    if not has_entries:
        lines.append("| _No Morphe APKs generated yet. Run autobuild workflow to initialize._ | — | — | — | — | — | — | — |")

    lines.append("")
    lines.append(
        "> 💡 **Looking for all 69+ patched APKs and 277 community patch bundles?**  \n"
        "> 👉 **[View the Complete Morphe Catalog on Dedicated docs/MORPHE.md →](docs/MORPHE.md)**  \n"
        "> 🌐 **[Open Interactive Web Portal (site/morphe.html) →](site/morphe.html)**"
    )
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def generate_morphe_docs_page(
    releases_db: dict[str, Any],
    status_db: dict[str, Any],
    apps_config: list[dict[str, Any]],
) -> str:
    mirror_repo = get_mirror_repo()
    lines = [
        "# ⚡ Morphe Patched Apps & Community Bundles Hub (Non-Root)",
        "",
        "> 🚀 **Official catalog of auto-built, non-root Morphe APKs and 277+ community patch bundles.**",
        "> Synchronized in real time with [morphe-patches.software](https://morphe-patches.software/).",
        "",
        "[![AutoBuild](https://img.shields.io/badge/Pipeline-AutoBuild-0284c7?style=flat-square)](docs/MORPHE.md)",
        "[![AutoGenerated](https://img.shields.io/badge/Channel-AutoGenerated-f59e0b?style=flat-square)](docs/MORPHE.md)",
        "[![Release](https://img.shields.io/badge/Release-Verified-16a34a?style=flat-square)](docs/MORPHE.md)",
        "[![Beta](https://img.shields.io/badge/Channel-Beta-9333ea?style=flat-square)](docs/MORPHE.md)",
        "[![PreRelease](https://img.shields.io/badge/Channel-PreRelease-e11d48?style=flat-square)](docs/MORPHE.md)",
        "",
        "---",
        "",
        "## 🧭 Quick Navigation",
        "",
        "- [📱 Complete Patched Apps Directory](#-complete-patched-apps-directory)",
        "- [📦 Community Patch Bundles (277+)](#-community-patch-bundles)",
        "- [🚀 Installation & Setup Guide](#-installation--setup-guide)",
        "- [🌐 Interactive Web Portal (site/morphe.html)](../site/morphe.html)",
        "",
        "---",
        "",
        '<span id="-status-filter"></span>',
        "## 🔍 Quick Filter by Status",
        "",
        "- `📦 Release` : Stable verified builds.",
        "- `🚀 AutoBuild` : Automatically patched and compiled from upstream patch repositories.",
        "- `⚡ AutoGenerated` : Regenerated on newer patch pushes or upstream base APK updates.",
        "- `🧪 Beta` : Fast-tracked builds testing the latest beta patches.",
        "- `🚧 PreRelease` : Pre-release canary builds for cutting-edge fixes.",
        "",
        "---",
        "",
        "## 📱 Complete Patched Apps Directory",
        "",
        "| App | Package Name | Status / Channel | Version | Bundle Source | Key Patches | Download APK | SHA-256 Checksum | Last Updated |",
        "|:---|:---|:---|:---|:---|:---|:---|:---|:---|",
    ]

    for app_raw in sorted(apps_config, key=lambda a: a.get("name", "").lower()):
        slug = app_raw.get("slug", "")
        if not app_raw.get("enabled", True):
            continue

        entry = releases_db.get(slug)
        if not entry:
            continue

        name = app_raw.get("name", slug)
        pkg = app_raw.get("package_name", "")
        version = entry.get("version", "latest")
        channel = entry.get("channel", app_raw.get("channel", "stable")).lower()
        build_type = entry.get("build_type", app_raw.get("build_type", "autobuild"))

        if channel == "beta":
            status_badge = "`🧪 Beta` `AutoBuild`"
        elif channel == "prerelease":
            status_badge = "`🚧 PreRelease` `AutoBuild`"
        elif build_type == "autogenerated":
            status_badge = "`⚡ AutoGenerated`"
        elif build_type == "release":
            status_badge = "`📦 Release`"
        else:
            status_badge = "`🚀 AutoBuild`"

        bundle_repo = app_raw.get("bundle_repo", "MorpheApp/morphe-patches")
        bundle_name = app_raw.get("bundle_name") or bundle_repo.split("/")[-1]
        bundle_link = f"[{bundle_name}](https://github.com/{bundle_repo})"

        patches = app_raw.get("patches", [])
        if patches:
            patches_str = "<br>".join(f"• {p}" for p in patches[:3])
            if len(patches) > 3:
                patches_str += f"<br>_and {len(patches)-3} more…_"
        else:
            patches_str = "Default patches"

        mirror_tag = entry.get("release_tag", "")
        if mirror_repo and mirror_tag:
            download_url = f"https://github.com/{mirror_repo}/releases/tag/{mirror_tag}"
            download_link = f"[⬇️ **Download**]({download_url})"
        else:
            download_link = "—"

        sha256 = entry.get("sha256", "")
        sha_str = f"`{sha256[:12]}…`" if sha256 else "—"
        updated_at = entry.get("updated_at", "")[:10] or "—"

        lines.append(
            f"| **{name}** | `{pkg}` | {status_badge} | `{version}` | {bundle_link} | {patches_str} | {download_link} | {sha_str} | {updated_at} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 📦 Community Patch Bundles",
        "",
        "All 277+ community patch bundles indexed from [morphe-patches.software](https://morphe-patches.software/). You can add any of these sources directly to the Morphe Manager app.",
        "",
        "| Bundle Name | Author | Repository | Target Applications | Patches | Morphe Deep Link |",
        "|:---|:---|:---|:---|:---|:---|",
    ])

    bundles = []
    if BUNDLES_CACHE_PATH.exists():
        try:
            with open(BUNDLES_CACHE_PATH, "r", encoding="utf-8") as fh:
                bdata = json.load(fh)
                bundles = bdata.get("bundles", [])
        except Exception as e:
            logger.warning("Error reading bundles cache: %s", e)

    for b in sorted(bundles, key=lambda x: x.get("name", "").lower()):
        b_name = b.get("name", "")
        b_author = b.get("author", "")
        b_repo = b.get("repo", "")
        b_targets = ", ".join(f"`{t}`" for t in b.get("targetApps", [])[:3])
        if len(b.get("targetApps", [])) > 3:
            b_targets += f" *(+{len(b.get('targetApps'))-3} more)*"
        patch_cnt = b.get("patchCount", len(b.get("patches", [])))
        deep_link = b.get("deepLink") or f"https://morphe.software/add-source?github={b_repo}"
        repo_link = f"[{b_repo}](https://github.com/{b_repo})" if "/" in b_repo else b_repo

        lines.append(
            f"| **{b_name}** | `{b_author}` | {repo_link} | {b_targets or 'Universal'} | {patch_cnt} | [➕ Add to Morphe]({deep_link}) |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 🚀 Installation & Setup Guide",
        "",
        "### 1. Non-Root Direct Installation",
        "- All packages in this repository are compiled with non-root hooks and compatibility layers.",
        "- Simply download the `.apk` from the table above and install it like any standard Android application.",
        "- No root, Magisk, or KernelSU privileges are necessary.",
        "",
        "### 2. MicroG / GmsCore (For YouTube & YouTube Music)",
        "- If you use YouTube or YouTube Music and want to log in with your Google account, you must install **GmsCore / MicroG**.",
        "- Recommended GmsCore: [MorpheApp/MicroG-RE](https://github.com/MorpheApp/MicroG-RE/releases) or [ReVanced/GmsCore](https://github.com/ReVanced/GmsCore/releases).",
        "- For other patched apps (Instagram, TikTok, Twitter, Reddit, Spotify, Gboard, AdGuard), GmsCore is **not** required.",
        "",
        "### 3. SHA-256 Checksum Verification",
        "Verify the integrity of downloaded APKs on your computer or Android terminal:",
        "```bash",
        "sha256sum <downloaded-file>.apk",
        "```",
        "Compare the printed hash with the SHA-256 column in the table above.",
        "",
        "---",
        "",
        "*Automated synchronization and builds maintained by [krishna3163](https://github.com/krishna3163).*",
        "",
    ])

    return "\n".join(lines)


def generate_morphe_site_page(
    releases_db: dict[str, Any],
    status_db: dict[str, Any],
    apps_config: list[dict[str, Any]],
) -> str:
    mirror_repo = get_mirror_repo()
    apps_json = []
    for app_raw in sorted(apps_config, key=lambda a: a.get("name", "").lower()):
        slug = app_raw.get("slug", "")
        if not app_raw.get("enabled", True):
            continue
        entry = releases_db.get(slug, {})
        mirror_tag = entry.get("release_tag", "")
        download_url = f"https://github.com/{mirror_repo}/releases/tag/{mirror_tag}" if mirror_repo and mirror_tag else "#"
        apps_json.append({
            "name": app_raw.get("name", slug),
            "slug": slug,
            "package_name": app_raw.get("package_name", ""),
            "version": entry.get("version", "latest"),
            "channel": entry.get("channel", app_raw.get("channel", "stable")).lower(),
            "build_type": entry.get("build_type", app_raw.get("build_type", "autobuild")).lower(),
            "bundle_name": app_raw.get("bundle_name") or app_raw.get("bundle_repo", "").split("/")[-1],
            "bundle_repo": app_raw.get("bundle_repo", ""),
            "patches": app_raw.get("patches", []),
            "download_url": download_url,
            "sha256": entry.get("sha256", ""),
            "updated_at": (entry.get("updated_at") or "")[:10],
        })

    bundles_json = []
    if BUNDLES_CACHE_PATH.exists():
        try:
            with open(BUNDLES_CACHE_PATH, "r", encoding="utf-8") as fh:
                bdata = json.load(fh)
                for b in bdata.get("bundles", []):
                    bundles_json.append({
                        "name": b.get("name", ""),
                        "author": b.get("author", ""),
                        "repo": b.get("repo", ""),
                        "patchCount": b.get("patchCount", len(b.get("patches", []))),
                        "stars": b.get("stars", 0),
                        "targetApps": b.get("targetApps", []),
                        "deepLink": b.get("deepLink") or f"https://morphe.software/add-source?github={b.get('repo')}",
                    })
        except Exception as e:
            logger.warning("Error serializing bundles for site: %s", e)

    return f"""<!doctype html>
<html lang="en" class="scroll-smooth">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>⚡ Morphe Patched Apps & Bundles Hub (Non-Root)</title>
  <meta name="description" content="Explore and download 69+ Morphe auto-built non-root patched APKs and 277+ community patch bundles.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      theme: {{
        extend: {{
          colors: {{
            paper: '#fcfaf6',
            ink: '#1d1b16',
            postyellow: '#ffd000',
            postamber: '#f5a623',
            badgebrown: '#666053',
            badgeyellow: '#fff3b0'
          }},
          fontFamily: {{
            sans: ['Inter', 'system-ui', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace']
          }},
          boxShadow: {{
            'brutal-sm': '2px 2px 0px #1d1b16',
            'brutal': '3px 3px 0px #1d1b16',
            'brutal-lg': '5px 5px 0px #1d1b16'
          }}
        }}
      }}
    }}
  </script>
  <style>
    body {{
      background-color: #fcfaf6;
      color: #1d1b16;
      background-image: radial-gradient(#e5dfd3 1px, transparent 1px);
      background-size: 24px 24px;
    }}
    .neo-card {{
      background: #ffffff;
      border: 2px solid #1d1b16;
      box-shadow: 3px 3px 0px #1d1b16;
      transition: all 0.15s ease;
    }}
    .neo-card:hover {{
      transform: translate(-2px, -2px);
      box-shadow: 5px 5px 0px #1d1b16;
    }}
    .neo-btn {{
      border: 2px solid #1d1b16;
      box-shadow: 2px 2px 0px #1d1b16;
      font-weight: 700;
      transition: all 0.1s ease;
    }}
    .neo-btn:hover {{
      transform: translate(-1px, -1px);
      box-shadow: 3px 3px 0px #1d1b16;
    }}
    .neo-btn:active {{
      transform: translate(2px, 2px);
      box-shadow: 0px 0px 0px #1d1b16;
    }}
    .tab-active {{
      background-color: #ffd000 !important;
      border-color: #1d1b16 !important;
      box-shadow: 3px 3px 0px #1d1b16 !important;
    }}
  </style>
</head>
<body class="min-h-screen flex flex-col font-sans">
  <div class="bg-[#ffd000] border-b-2 border-[#1d1b16] py-2 px-4 text-center font-mono text-xs font-bold flex items-center justify-center gap-2">
    <span>⚡ 69+ Morphe Non-Root APKs • 277 Community Bundles • Live AutoBuilds</span>
  </div>

  <header class="sticky top-0 z-40 bg-[#fcfaf6]/95 backdrop-blur-md border-b-2 border-[#1d1b16]">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-18 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <a href="index.html" class="neo-btn bg-white px-3 py-1.5 rounded-lg text-xs flex items-center gap-1.5">
          <span>←</span> <span>Shizuku Catalog</span>
        </a>
        <div class="flex items-center gap-2">
          <span class="font-black text-xl tracking-tight">⚡ Morphe Hub</span>
          <span class="bg-[#ffd000] text-[#1d1b16] text-[11px] font-mono font-bold px-2 py-0.5 rounded border border-[#1d1b16]">Non-Root</span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <a href="https://krishna3163.github.io/OpenDiscover/#/morphe" target="_blank" class="neo-btn bg-[#ffd000] px-3.5 py-1.5 rounded-lg text-xs">
          OpenDiscover Morphe ↗
        </a>
        <a href="https://github.com/krishna3163/best_shizuku_apps_for_android_no_root" target="_blank" class="neo-btn bg-white px-3 py-1.5 rounded-lg text-xs hidden sm:flex">
          GitHub
        </a>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1">
    <div class="mb-8 text-center max-w-3xl mx-auto">
      <h1 class="text-3xl sm:text-4xl font-black text-[#1d1b16] tracking-tight mb-3">
        Morphe Patched Apps & Community Bundles
      </h1>
      <p class="text-[#666053] font-medium text-sm sm:text-base">
        Browse auto-generated ad-free, enhanced APK builds and explore 277 community patch sources with instant 1-click addition to Morphe Manager.
      </p>
    </div>

    <!-- View Switcher -->
    <div class="flex justify-center gap-3 mb-6">
      <button id="tab-apps-btn" onclick="switchTab('apps')" class="neo-btn tab-active px-5 py-2.5 rounded-xl font-bold text-sm flex items-center gap-2">
        <span>📱 Patched APKs</span>
        <span class="bg-[#1d1b16] text-[#ffd000] text-xs px-2 py-0.5 rounded font-mono" id="apps-count-badge">69</span>
      </button>
      <button id="tab-bundles-btn" onclick="switchTab('bundles')" class="neo-btn bg-white px-5 py-2.5 rounded-xl font-bold text-sm flex items-center gap-2">
        <span>📦 Community Bundles</span>
        <span class="bg-[#1d1b16] text-[#ffd000] text-xs px-2 py-0.5 rounded font-mono" id="bundles-count-badge">277</span>
      </button>
    </div>

    <!-- Search & Channel Filters -->
    <div class="mb-6 space-y-4 max-w-4xl mx-auto">
      <div class="relative">
        <input id="search-input" type="search" placeholder="🔍 Search by app name, package, bundle source, patch name..." oninput="handleSearch()" class="w-full bg-white border-2 border-[#1d1b16] rounded-xl px-4 py-3 shadow-brutal-sm font-medium placeholder-[#666053] focus:outline-none focus:ring-2 focus:ring-[#ffd000]">
      </div>

      <div id="channel-filters" class="flex flex-wrap items-center justify-center gap-2 pt-1">
        <button onclick="setChannelFilter('all')" class="channel-chip neo-btn bg-[#ffd000] px-3 py-1 rounded-lg text-xs" data-channel="all">All Channels</button>
        <button onclick="setChannelFilter('autobuild')" class="channel-chip neo-btn bg-white px-3 py-1 rounded-lg text-xs" data-channel="autobuild">🚀 AutoBuild</button>
        <button onclick="setChannelFilter('autogenerated')" class="channel-chip neo-btn bg-white px-3 py-1 rounded-lg text-xs" data-channel="autogenerated">⚡ AutoGenerated</button>
        <button onclick="setChannelFilter('release')" class="channel-chip neo-btn bg-white px-3 py-1 rounded-lg text-xs" data-channel="release">📦 Release</button>
        <button onclick="setChannelFilter('beta')" class="channel-chip neo-btn bg-white px-3 py-1 rounded-lg text-xs" data-channel="beta">🧪 Beta</button>
        <button onclick="setChannelFilter('prerelease')" class="channel-chip neo-btn bg-white px-3 py-1 rounded-lg text-xs" data-channel="prerelease">🚧 PreRelease</button>
      </div>
    </div>

    <!-- Apps View -->
    <section id="apps-view">
      <div id="apps-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"></div>
      <div id="apps-empty" class="hidden text-center py-16 text-[#666053] font-mono text-sm">
        No patched APKs match your search or filters.
      </div>
    </section>

    <!-- Bundles View -->
    <section id="bundles-view" class="hidden">
      <div id="bundles-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"></div>
      <div id="bundles-empty" class="hidden text-center py-16 text-[#666053] font-mono text-sm">
        No patch bundles match your search.
      </div>
    </section>
  </main>

  <footer class="border-t-2 border-[#1d1b16] bg-white py-6 mt-12 text-center text-xs text-[#666053] font-mono">
    AutoBuild & Synchronization powered by Morphe Engine • Maintained with ❤️ by krishna3163
  </footer>

  <script>
    const APPS_DATA = {json.dumps(apps_json)};
    const BUNDLES_DATA = {json.dumps(bundles_json)};

    let currentTab = 'apps';
    let currentChannel = 'all';
    let searchQuery = '';

    function switchTab(tab) {{
      currentTab = tab;
      document.getElementById('tab-apps-btn').className = tab === 'apps' ? 'neo-btn tab-active px-5 py-2.5 rounded-xl font-bold text-sm flex items-center gap-2' : 'neo-btn bg-white px-5 py-2.5 rounded-xl font-bold text-sm flex items-center gap-2';
      document.getElementById('tab-bundles-btn').className = tab === 'bundles' ? 'neo-btn tab-active px-5 py-2.5 rounded-xl font-bold text-sm flex items-center gap-2' : 'neo-btn bg-white px-5 py-2.5 rounded-xl font-bold text-sm flex items-center gap-2';
      document.getElementById('apps-view').className = tab === 'apps' ? '' : 'hidden';
      document.getElementById('bundles-view').className = tab === 'bundles' ? '' : 'hidden';
      document.getElementById('channel-filters').className = tab === 'apps' ? 'flex flex-wrap items-center justify-center gap-2 pt-1' : 'hidden';
      render();
    }}

    function setChannelFilter(ch) {{
      currentChannel = ch;
      document.querySelectorAll('.channel-chip').forEach(btn => {{
        if (btn.getAttribute('data-channel') === ch) {{
          btn.className = 'channel-chip neo-btn bg-[#ffd000] px-3 py-1 rounded-lg text-xs';
        }} else {{
          btn.className = 'channel-chip neo-btn bg-white px-3 py-1 rounded-lg text-xs';
        }}
      }});
      render();
    }}

    function handleSearch() {{
      searchQuery = document.getElementById('search-input').value.toLowerCase().trim();
      render();
    }}

    function copyHash(btn, hash) {{
      navigator.clipboard.writeText(hash).then(() => {{
        const orig = btn.innerText;
        btn.innerText = 'Copied!';
        setTimeout(() => {{ btn.innerText = orig; }}, 1500);
      }});
    }}

    function render() {{
      if (currentTab === 'apps') {{
        const filtered = APPS_DATA.filter(app => {{
          const matchesChannel = currentChannel === 'all' || 
            (app.channel === currentChannel) || 
            (app.build_type === currentChannel);
          const matchesQuery = !searchQuery || 
            app.name.toLowerCase().includes(searchQuery) || 
            app.package_name.toLowerCase().includes(searchQuery) || 
            app.bundle_name.toLowerCase().includes(searchQuery) ||
            app.patches.some(p => p.toLowerCase().includes(searchQuery));
          return matchesChannel && matchesQuery;
        }});

        const grid = document.getElementById('apps-grid');
        const empty = document.getElementById('apps-empty');
        grid.innerHTML = '';
        if (filtered.length === 0) {{
          empty.className = 'text-center py-16 text-[#666053] font-mono text-sm';
        }} else {{
          empty.className = 'hidden';
          filtered.forEach(app => {{
            let badgeBg = 'bg-sky-100 text-sky-800 border-sky-400';
            let badgeLabel = 'AutoBuild';
            if (app.channel === 'beta') {{ badgeBg = 'bg-purple-100 text-purple-800 border-purple-400'; badgeLabel = 'Beta'; }}
            else if (app.channel === 'prerelease') {{ badgeBg = 'bg-rose-100 text-rose-800 border-rose-400'; badgeLabel = 'PreRelease'; }}
            else if (app.build_type === 'autogenerated') {{ badgeBg = 'bg-amber-100 text-amber-800 border-amber-400'; badgeLabel = 'AutoGenerated'; }}
            else if (app.build_type === 'release') {{ badgeBg = 'bg-emerald-100 text-emerald-800 border-emerald-400'; badgeLabel = 'Release'; }}

            const patchesList = app.patches.slice(0, 3).map(p => `<li>• ${{p}}</li>`).join('');
            const morePatches = app.patches.length > 3 ? `<li class="italic text-[#666053]">+ ${{app.patches.length - 3}} more patches</li>` : '';

            const card = document.createElement('div');
            card.className = 'neo-card p-5 rounded-2xl flex flex-col justify-between';
            card.innerHTML = `
              <div>
                <div class="flex items-start justify-between gap-2 mb-2">
                  <h3 class="font-extrabold text-lg leading-snug">${{app.name}}</h3>
                  <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${{badgeBg}} whitespace-nowrap">${{badgeLabel}}</span>
                </div>
                <div class="text-xs font-mono text-[#666053] mb-3 truncate" title="${{app.package_name}}">${{app.package_name}}</div>
                <div class="flex items-center gap-2 text-xs font-mono mb-4">
                  <span class="bg-[#f4f0e6] px-2 py-0.5 rounded border border-[#1d1b16] font-bold">v${{app.version}}</span>
                  <span class="text-[#666053]">via <a href="https://github.com/${{app.bundle_repo}}" target="_blank" class="underline font-bold text-[#1d1b16]">${{app.bundle_name}}</a></span>
                </div>
                <div class="bg-[#fcfaf6] border border-[#1d1b16] rounded-xl p-3 mb-4">
                  <span class="text-[10px] font-bold font-mono uppercase tracking-wider text-[#666053] block mb-1.5">Key Patches:</span>
                  <ul class="text-xs space-y-1 font-medium">${{patchesList}}${{morePatches}}</ul>
                </div>
              </div>
              <div>
                <div class="flex items-center justify-between gap-2 pt-2 border-t border-[#1d1b16]/10">
                  <button onclick="copyHash(this, '${{app.sha256}}')" class="neo-btn bg-white px-2.5 py-1.5 rounded-lg text-[11px] font-mono font-bold text-[#666053] hover:text-[#1d1b16]">
                    SHA-256
                  </button>
                  <a href="${{app.download_url}}" target="_blank" class="neo-btn bg-[#ffd000] px-4 py-1.5 rounded-lg text-xs font-extrabold flex items-center gap-1.5 hover:bg-[#f5a623]">
                    <span>⬇️ Download APK</span>
                  </a>
                </div>
              </div>
            `;
            grid.appendChild(card);
          }});
        }}
      }} else {{
        const filtered = BUNDLES_DATA.filter(b => {{
          return !searchQuery || 
            b.name.toLowerCase().includes(searchQuery) || 
            b.author.toLowerCase().includes(searchQuery) || 
            b.repo.toLowerCase().includes(searchQuery) ||
            b.targetApps.some(t => t.toLowerCase().includes(searchQuery));
        }});

        const grid = document.getElementById('bundles-grid');
        const empty = document.getElementById('bundles-empty');
        grid.innerHTML = '';
        if (filtered.length === 0) {{
          empty.className = 'text-center py-16 text-[#666053] font-mono text-sm';
        }} else {{
          empty.className = 'hidden';
          filtered.forEach(b => {{
            const targetsHtml = b.targetApps.slice(0, 3).map(t => `<span class="bg-[#f4f0e6] px-1.5 py-0.5 rounded border border-[#1d1b16] text-[10px] font-mono">${{t}}</span>`).join(' ');
            const moreTargets = b.targetApps.length > 3 ? `<span class="text-[10px] text-[#666053] font-mono">+${{b.targetApps.length - 3}}</span>` : '';

            const card = document.createElement('div');
            card.className = 'neo-card p-5 rounded-2xl flex flex-col justify-between';
            card.innerHTML = `
              <div>
                <div class="flex items-start justify-between gap-2 mb-2">
                  <h3 class="font-extrabold text-lg leading-snug">${{b.name}}</h3>
                  <span class="text-xs font-mono font-bold bg-[#ffd000] px-2 py-0.5 rounded border border-[#1d1b16]">★ ${{b.stars}}</span>
                </div>
                <div class="text-xs font-mono text-[#666053] mb-3">by <span class="font-bold text-[#1d1b16]">${{b.author}}</span></div>
                <div class="mb-4">
                  <span class="text-[10px] font-bold font-mono uppercase tracking-wider text-[#666053] block mb-1.5">Targets (${{b.patchCount}} patches):</span>
                  <div class="flex flex-wrap gap-1">${{targetsHtml}} ${{moreTargets}}</div>
                </div>
              </div>
              <div class="flex items-center justify-between gap-2 pt-3 border-t border-[#1d1b16]/10">
                <a href="https://github.com/${{b.repo}}" target="_blank" class="neo-btn bg-white px-3 py-1.5 rounded-lg text-xs font-bold text-[#666053]">GitHub</a>
                <a href="${{b.deepLink}}" class="neo-btn bg-[#ffd000] px-3.5 py-1.5 rounded-lg text-xs font-extrabold hover:bg-[#f5a623] flex items-center gap-1">
                  <span>➕ Add to Morphe</span>
                </a>
              </div>
            `;
            grid.appendChild(card);
          }});
        }}
      }}
    }}

    document.getElementById('apps-count-badge').innerText = APPS_DATA.length;
    document.getElementById('bundles-count-badge').innerText = BUNDLES_DATA.length;
    render();
  </script>
</body>
</html>
"""


def update_all_morphe_pages(
    releases_db: dict[str, Any],
    status_db: dict[str, Any],
    apps_config: list[dict[str, Any]],
) -> None:
    # 1. Update README table
    readme_table = generate_morphe_readme_table(releases_db, status_db, apps_config)
    update_readme_content(readme_table)

    # 2. Generate docs/MORPHE.md and root MORPHE.md
    DOCS_MORPHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    docs_content = generate_morphe_docs_page(releases_db, status_db, apps_config)
    DOCS_MORPHE_PATH.write_text(docs_content, encoding="utf-8")
    ROOT_MORPHE_PATH.write_text(docs_content, encoding="utf-8")
    logger.info("Updated %s and %s", DOCS_MORPHE_PATH, ROOT_MORPHE_PATH)

    # 3. Generate site/morphe.html
    SITE_MORPHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    site_content = generate_morphe_site_page(releases_db, status_db, apps_config)
    SITE_MORPHE_PATH.write_text(site_content, encoding="utf-8")
    logger.info("Updated %s", SITE_MORPHE_PATH)

    # 4. Ensure site/index.html navbar links to morphe.html
    if SITE_INDEX_PATH.exists():
        index_html = SITE_INDEX_PATH.read_text(encoding="utf-8")
        if "morphe.html" not in index_html and "Shizuku Web Companion" in index_html:
            morphe_nav_btn = (
                '<a href="morphe.html" class="posthog-btn-white px-3 py-1.5 sm:px-3.5 sm:py-2 rounded-xl text-xs sm:text-sm flex items-center gap-1.5 font-bold mr-2">'
                '<span>⚡ Morphe Hub</span>'
                '<span class="bg-[#ffd000] text-[#1d1b16] text-[10px] px-1.5 py-0.2 rounded font-mono font-bold">69+ APKs</span>'
                '</a>'
            )
            # Insert before Shizuku Web Companion Button
            index_html = index_html.replace(
                '<!-- Shizuku Web Companion Button -->',
                f'{morphe_nav_btn}\n        <!-- Shizuku Web Companion Button -->'
            )
            SITE_INDEX_PATH.write_text(index_html, encoding="utf-8")
            logger.info("Added Morphe Hub button to %s navbar", SITE_INDEX_PATH)


def update_readme_content(new_table: str) -> bool:
    if not README_PATH.exists():
        logger.error("README.md not found at %s", README_PATH)
        return False

    content = README_PATH.read_text(encoding="utf-8")

    if START_MARKER in content and END_MARKER in content:
        start_idx = content.find(START_MARKER)
        end_idx = content.find(END_MARKER) + len(END_MARKER)
        updated_content = content[:start_idx] + START_MARKER + new_table + END_MARKER + content[end_idx:]
    else:
        insert_marker = "<!-- AUTO-GENERATED-APPS-START -->"
        if insert_marker in content:
            idx = content.find(insert_marker)
            updated_content = (
                content[:idx]
                + START_MARKER + new_table + END_MARKER + "\n\n"
                + content[idx:]
            )
        else:
            updated_content = content + "\n\n" + START_MARKER + new_table + END_MARKER + "\n"

    if updated_content != content:
        README_PATH.write_text(updated_content, encoding="utf-8")
        logger.info("README.md updated with latest Morphe generated APKs table.")
        return True
    return False


def sync_morphe_apps(
    target_app: Optional[str] = None,
    dry_run: bool = False,
    force_rebuild: bool = False,
    channel_filter: Optional[str] = None,
    build_type_filter: Optional[str] = None,
) -> None:
    config = load_config()
    apps_data = config.get("apps", [])
    defaults = config.get("defaults", {})

    releases_db = load_json_db(RELEASES_DB_PATH)
    status_db = load_json_db(STATUS_DB_PATH)

    bundle_client = MorpheBundleClient(cache_file=BUNDLES_CACHE_PATH)
    bundle_client.fetch_catalog()

    patcher = MorphePatcher()
    api = GitHubAPI()
    mirror_repo = get_mirror_repo()

    updated_count = 0

    with tempfile.TemporaryDirectory(prefix="morphe_build_shizuku_") as tmp_dir:
        patcher.locate_or_download_cli(tmp_dir)

        for raw_app in apps_data:
            slug = raw_app.get("slug", "")
            if not slug or not raw_app.get("enabled", True):
                continue
            if target_app and target_app not in (slug, raw_app.get("package_name", "")):
                continue

            channel = raw_app.get("channel", defaults.get("channel", "stable")).lower()
            if channel_filter and channel_filter.lower() != "all" and channel != channel_filter.lower():
                continue

            build_type = raw_app.get("build_type", defaults.get("build_type", "autobuild")).lower()
            if build_type_filter and build_type_filter.lower() != "all" and build_type != build_type_filter.lower():
                continue

            app = MorpheAppConfig(
                name=raw_app["name"],
                slug=slug,
                package_name=raw_app["package_name"],
                bundle_repo=raw_app["bundle_repo"],
                bundle_name=raw_app.get("bundle_name", ""),
                category=raw_app.get("category", "Tools & Utilities"),
                app_type=raw_app.get("app_type", defaults.get("app_type", "non-root")),
                build_type=build_type,
                channel=channel,
                recommended_version=raw_app.get("recommended_version", "latest"),
                patches=raw_app.get("patches", []),
                enabled=raw_app.get("enabled", True),
                base_apk_url=raw_app.get("base_apk_url"),
                icon_url=raw_app.get("icon_url", ""),
                description=raw_app.get("description", ""),
            )

            version = app.recommended_version
            if version == "latest":
                compat_versions = bundle_client.get_compatible_versions(app.package_name)
                if compat_versions:
                    version = compat_versions[0]
                else:
                    version = "1.0.0"

            release_tag = make_morphe_tag(app.slug, version, app.channel)
            prev_entry = releases_db.get(app.slug)

            needs_build = force_rebuild
            if not needs_build:
                if not prev_entry:
                    needs_build = True
                elif prev_entry.get("version") != version or prev_entry.get("release_tag") != release_tag:
                    needs_build = True

            logger.info("Processing Morphe App: %s (%s) v%s [Needs Build: %s]", app.name, app.slug, version, needs_build)

            if not needs_build:
                continue

            try:
                base_apk = BaseApkManager.fetch_base_apk(
                    app.package_name, version, tmp_dir, source_url=app.base_apk_url
                )
            except Exception as e:
                logger.error("Failed to acquire base APK for %s: %s", app.slug, e)
                status_db[app.slug] = {
                    "last_attempt": datetime.now(timezone.utc).isoformat(),
                    "status": "failed",
                    "error": str(e),
                }
                continue

            bundle_mpp = patcher.fetch_patch_bundle(app.bundle_repo, tmp_dir)
            output_apk_name = f"{app.slug}-{version}.apk"
            output_apk_path = os.path.join(tmp_dir, output_apk_name)
            success, msg = patcher.patch_apk(base_apk, bundle_mpp, output_apk_path, app.patches)

            if not success:
                logger.error("Patching failed for %s: %s", app.slug, msg)
                status_db[app.slug] = {
                    "last_attempt": datetime.now(timezone.utc).isoformat(),
                    "status": "failed",
                    "error": msg,
                }
                continue

            sha256 = BaseApkManager.calculate_sha256(output_apk_path)
            file_size = os.path.getsize(output_apk_path)
            checksum_path = output_apk_path + ".sha256"
            with open(checksum_path, "w", encoding="utf-8") as f:
                f.write(f"{sha256}  {output_apk_name}\n")

            logger.info("Successfully produced %s (SHA-256: %s, %d bytes)", output_apk_name, sha256[:12], file_size)

            if not dry_run and mirror_repo:
                is_prerelease = app.channel in ("beta", "prerelease")
                rel_title = f"{app.name} {version} ({app.channel.capitalize()})"
                rel_body = generate_morphe_release_body(
                    app, version, bundle_client.get_bundle_by_repo(app.bundle_repo), sha256, file_size, output_apk_name
                )
                try:
                    logger.info("Publishing GitHub release %s in %s", release_tag, mirror_repo)
                    existing_rel = api.get_repo_release_by_tag(mirror_repo, release_tag)
                    if existing_rel:
                        upload_url = existing_rel.get("upload_url", "")
                    else:
                        rel = api.create_release(
                            mirror_repo, release_tag, rel_title, rel_body, prerelease=is_prerelease
                        )
                        upload_url = rel.get("upload_url", "")

                    if upload_url:
                        api.upload_release_asset(upload_url, output_apk_path)
                        api.upload_release_asset(upload_url, checksum_path)
                except Exception as e:
                    logger.error("Error creating/uploading release %s: %s", release_tag, e)

            # REPLACE IN DATABASE: Replaces old version on update
            now_iso = datetime.now(timezone.utc).isoformat()
            releases_db[app.slug] = {
                "name": app.name,
                "slug": app.slug,
                "package_name": app.package_name,
                "version": version,
                "release_tag": release_tag,
                "bundle_repo": app.bundle_repo,
                "bundle_name": app.bundle_name,
                "channel": app.channel,
                "build_type": app.build_type,
                "app_type": app.app_type,
                "sha256": sha256,
                "file_size": file_size,
                "filename": output_apk_name,
                "updated_at": now_iso,
                "patches": app.patches,
            }
            status_db[app.slug] = {
                "last_attempt": now_iso,
                "status": "success",
                "version": version,
                "release_tag": release_tag,
            }
            updated_count += 1

    save_json_db(RELEASES_DB_PATH, releases_db)
    save_json_db(STATUS_DB_PATH, status_db)

    update_all_morphe_pages(releases_db, status_db, apps_data)
    logger.info("Morphe synchronization completed for Shizuku repo. Updated %d apps.", updated_count)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Synchronize and Auto-Build Morphe Patched Apps for Shizuku")
    parser.add_argument("--app", help="Application slug or package name to sync")
    parser.add_argument("--dry-run", action="store_true", help="Build without publishing releases")
    parser.add_argument("--force-rebuild", action="store_true", help="Force rebuild regardless of existing tags")
    parser.add_argument("--channel", help="Filter by channel: stable, beta, prerelease, all")
    parser.add_argument("--build-type", help="Filter by build type: autobuild, autogenerated, release, all")
    args = parser.parse_args()

    sync_morphe_apps(
        target_app=args.app,
        dry_run=args.dry_run,
        force_rebuild=args.force_rebuild,
        channel_filter=args.channel,
        build_type_filter=args.build_type,
    )


if __name__ == "__main__":
    main()
