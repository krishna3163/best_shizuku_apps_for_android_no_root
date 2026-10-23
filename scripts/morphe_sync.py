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
        '<div align="center" class="morphe-search-filter">',
        "",
        "**🔍 Quick Filter by Status:**",
        "[ **All** ](#morphe-downloads) • "
        "[ **📦 Release** ](#morphe-downloads) • "
        "[ **🚀 AutoBuild** ](#morphe-downloads) • "
        "[ **⚡ AutoGenerated** ](#morphe-downloads) • "
        "[ **🧪 Beta** ](#morphe-downloads) • "
        "[ **🚧 PreRelease** ](#morphe-downloads)",
        "",
        "</div>",
        "",
        "| App | Status / Channel | Version | Bundle Source | Key Patches | Download | SHA-256 | Updated |",
        "|:---|:---|:---|:---|:---|:---|:---|:---|",
    ]

    has_entries = False
    for app_raw in sorted(apps_config, key=lambda a: a.get("name", "").lower()):
        slug = app_raw.get("slug", "")
        if not app_raw.get("enabled", True):
            continue

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
        sha_str = f"`{sha256[:10]}…`" if sha256 else "—"
        updated_at = entry.get("updated_at", "")[:10] or "—"

        lines.append(
            f"| **{name}**<br><sub>`{pkg}`</sub> | {status_badge} | `{version}` | {bundle_link} | {patches_str} | {download_link} | {sha_str} | {updated_at} |"
        )

    if not has_entries:
        lines.append("| _No Morphe APKs generated yet. Run autobuild workflow to initialize._ | — | — | — | — | — | — | — |")

    lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


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

    readme_table = generate_morphe_readme_table(releases_db, status_db, apps_data)
    update_readme_content(readme_table)
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
