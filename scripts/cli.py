#!/usr/bin/env python3
"""Shizuku Ecosystem CLI & Android ADB Companion.

Search 500+ curated Android apps, inspect metadata, download mirrored APKs,
activate Shizuku on connected devices, and install tools via ADB.

Usage:
    shizuku search <query>             # Search apps by name or description
    shizuku list [--category <name>]   # Browse catalog
    shizuku categories                 # View all category breakdowns
    shizuku info <app>                 # Detailed app card & download links
    shizuku top                        # View curated Top Picks
    shizuku activate                   # 1-Click activate Shizuku via ADB
    shizuku status                     # Check connected devices & Shizuku status
    shizuku download <app>             # Download verified mirrored APK
    shizuku install <app>              # Download & install APK directly via ADB
    shizuku feeds                      # F-Droid & Obtainium feed URLs
    shizuku bot                        # Telegram Bot status & help
    shizuku interactive                # Open interactive TUI prompt
"""

from __future__ import annotations

import argparse
import cmd
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
APPS_CONFIG_PATH = ROOT / "config" / "apps.json"
RELEASES_DB_PATH = ROOT / "data" / "releases.json"

LINK_REGEX = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

# ANSI Terminal Colors & Styling
C_YELLOW = "\033[1;33m"
C_GREEN = "\033[1;32m"
C_CYAN = "\033[1;36m"
C_RED = "\033[1;31m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"

NON_CAT_SECTIONS = {
    "FAQ", "Frequently Asked Questions", "🤖", "AI & Citation", "📬",
    "Connect with Maintainer", "👥", "Contributors", "🤝", "Join the Community",
    "💬", "Community Chat", "License", "Show Your Support", "⚠️", "Disclaimer",
    "🔄", "Automatic APK Updates", "⚡", "1-Click PC Activator", "📱 OEM Device Setup",
    "🔑 Key Features", "✨ Why This List?", "🔥 Popular Search Topics", "🚀 Quick Setup",
}


def print_banner() -> None:
    banner = f"""{C_YELLOW}
   ███████╗██╗  ██╗██╗███████╗██╗   ██╗██╗  ██╗██╗   ██╗
   ██╔════╝██║  ██║██║╚══███╔╝██║   ██║██║ ██╔╝██║   ██║
   ███████╗███████║██║  ███╔╝ ██║   ██║█████╔╝ ██║   ██║
   ╚════██║██╔══██║██║ ███╔╝  ██║   ██║██╔═██╗ ██║   ██║
   ███████║██║  ██║██║███████╗╚██████╔╝██║  ██╗╚██████╔╝
   ╚══════╝╚═╝  ╚═╝╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝{C_RESET}
   {C_BOLD}Privileged Android Tools & Verified APK Mirror CLI{C_RESET}
   {C_DIM}Curated by Krishna (@kk3163019) • 500+ Curated Apps • Zero Pip Dependencies{C_RESET}
"""
    print(banner)


def load_catalog() -> list[dict[str, Any]]:
    """Parse apps from README.md tables and merge config/apps.json + releases.json."""
    apps: list[dict[str, Any]] = []
    app_index: dict[str, int] = {}

    mirrored_map: dict[str, Any] = {}
    if APPS_CONFIG_PATH.exists():
        try:
            with open(APPS_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for item in cfg.get("apps", []):
                    slug = item.get("slug", "").strip().lower()
                    if slug:
                        mirrored_map[slug] = item
                    name = item.get("name", "").strip().lower()
                    if name:
                        mirrored_map[name] = item
        except Exception:
            pass

    releases_map: dict[str, Any] = {}
    if RELEASES_DB_PATH.exists():
        try:
            with open(RELEASES_DB_PATH, "r", encoding="utf-8") as f:
                releases_map = json.load(f)
        except Exception:
            pass

    if not README_PATH.exists():
        return apps

    content = README_PATH.read_text(encoding="utf-8")
    category = "General"
    in_skip_section = False

    for line in content.splitlines():
        # Skip 6-column release mirror tables
        if '<details id="apk-downloads"' in line or '<details id="recent-updates"' in line:
            in_skip_section = True
            continue
        if in_skip_section:
            if "</details>" in line:
                in_skip_section = False
            continue

        # Header parsing for categories
        if line.startswith("<summary><h2>🔍 Auto-Discovered"):
            category = "Auto-Discovered"
            continue

        if line.startswith("### "):
            candidate = line.lstrip("# ").strip()
            if not any(stop in candidate for stop in NON_CAT_SECTIONS):
                category = candidate
            continue

        if line.startswith("## "):
            candidate = line.lstrip("# ").strip()
            if not any(stop in candidate for stop in NON_CAT_SECTIONS):
                if candidate not in {"Apps", "Development libraries", "Miscellaneous content"}:
                    category = candidate
            continue

        # Catalog tables have strictly 4 columns: | App | Description | License | Links |
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 6 or parts[0] != "" or parts[-1] != "":
            continue

        raw_name, raw_desc, raw_license, raw_links = parts[1:5]
        if raw_name in {"App", "---", ":---", "Library"} or raw_desc == "Description" or raw_name.startswith(":-"):
            continue

        name_match = LINK_REGEX.search(raw_name)
        clean_name = name_match.group(1) if name_match else raw_name.strip("*_` ")
        primary_link = name_match.group(2) if name_match else ""

        all_links = LINK_REGEX.findall(raw_links)
        for l_name, l_url in all_links:
            if "github.com" in l_url or "gitlab.com" in l_url or "source" in l_name.lower() or "code" in l_name.lower():
                primary_link = l_url
                break
        if not primary_link and all_links:
            primary_link = all_links[0][1]

        slug = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-")
        key = clean_name.lower()

        if not primary_link or "play.google.com" in primary_link:
            cfg_item = mirrored_map.get(slug) or mirrored_map.get(key)
            if cfg_item and cfg_item.get("repository"):
                primary_link = f"https://github.com/{cfg_item['repository']}"

        is_mirrored = slug in mirrored_map or key in mirrored_map or slug in releases_map
        rel_info = releases_map.get(slug, {})

        entry = {
            "name": clean_name,
            "slug": slug,
            "category": category,
            "description": raw_desc,
            "license": raw_license,
            "primary_link": primary_link,
            "links": all_links,
            "is_mirrored": is_mirrored,
            "release": rel_info,
        }

        if key in app_index:
            existing_idx = app_index[key]
            existing = apps[existing_idx]
            # Upgrade entry if existing is generic Auto-Discovered and new has a curated category
            if existing["category"] == "Auto-Discovered" and category != "Auto-Discovered":
                apps[existing_idx] = entry
            elif len(raw_desc) > len(existing["description"]):
                apps[existing_idx]["description"] = raw_desc
            if not existing["license"] or existing["license"] == "See project":
                apps[existing_idx]["license"] = raw_license
        else:
            app_index[key] = len(apps)
            apps.append(entry)

    return apps


def cmd_search(query: str, catalog: list[dict[str, Any]]) -> None:
    """Search apps by keyword."""
    q = query.lower().strip()
    if not q:
        print(f"{C_RED}[!] Error: Please provide a search term (e.g. 'shizuku search canta'){C_RESET}")
        return

    matches = []
    for app in catalog:
        if (
            q in app["name"].lower()
            or q in app["description"].lower()
            or q in app["category"].lower()
            or q in app["slug"]
        ):
            matches.append(app)

    print(f"\n{C_BOLD}🔍 Search Results for '{query}' ({len(matches)} found):{C_RESET}\n")
    if not matches:
        print(f"  {C_DIM}No apps found matching your query. Try 'debloat', 'dns', 'battery', or 'freeze'.{C_RESET}\n")
        return

    print(f"  {C_YELLOW}{'APP NAME':<24} {'CATEGORY':<24} {'LICENSE':<12} {'MIRROR':<8}{C_RESET}")
    print("  " + "─" * 74)
    for a in matches[:25]:
        mirror_badge = f"{C_GREEN}YES{C_RESET}" if a["is_mirrored"] else f"{C_DIM}NO{C_RESET}"
        name_str = a["name"][:22]
        cat_str = a["category"][:22]
        lic_str = a["license"][:11]
        print(f"  {C_BOLD}{name_str:<24}{C_RESET} {cat_str:<24} {lic_str:<12} {mirror_badge}")

    if len(matches) > 25:
        print(f"\n  {C_DIM}... and {len(matches) - 25} more. Refine your query or use 'shizuku info <slug>'.{C_RESET}")
    print(f"\n{C_DIM}Tip: Run 'shizuku info <app>' to inspect detailed use case and APK links.{C_RESET}\n")


def cmd_list(catalog: list[dict[str, Any]], category_filter: Optional[str] = None, limit: int = 30) -> None:
    """Browse catalog apps."""
    filtered = catalog
    if category_filter:
        c_filter = category_filter.lower()
        filtered = [a for a in catalog if c_filter in a["category"].lower()]

    header = f"Catalog Browser: {category_filter}" if category_filter else "Catalog Browser"
    print(f"\n{C_BOLD}📋 {header} ({len(filtered)} apps):{C_RESET}\n")
    print(f"  {C_YELLOW}{'APP NAME':<24} {'CATEGORY':<24} {'LICENSE':<12} {'MIRROR':<8}{C_RESET}")
    print("  " + "─" * 74)
    for a in filtered[:limit]:
        mirror_badge = f"{C_GREEN}YES{C_RESET}" if a["is_mirrored"] else f"{C_DIM}NO{C_RESET}"
        name_str = a["name"][:22]
        cat_str = a["category"][:22]
        lic_str = a["license"][:11]
        print(f"  {C_BOLD}{name_str:<24}{C_RESET} {cat_str:<24} {lic_str:<12} {mirror_badge}")

    if len(filtered) > limit:
        print(f"\n  {C_DIM}... showing {limit} of {len(filtered)}. Use --limit <n> or filter by category.{C_RESET}")
    print()


def cmd_categories(catalog: list[dict[str, Any]]) -> None:
    """Show breakdown of all categories."""
    cats: dict[str, int] = {}
    for a in catalog:
        cats[a["category"]] = cats.get(a["category"], 0) + 1

    sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)
    print(f"\n{C_BOLD}📂 Available Catalog Categories ({len(sorted_cats)}):{C_RESET}\n")
    for name, count in sorted_cats:
        print(f"  {C_YELLOW}•{C_RESET} {C_BOLD}{name:<32}{C_RESET} : {count} apps")
    print(f"\n{C_DIM}Run 'shizuku list --category \"{sorted_cats[0][0]}\"' to view apps in that category.{C_RESET}\n")


def find_app(query: str, catalog: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Lookup app by exact slug, name, or substring."""
    q = query.lower().strip()
    for a in catalog:
        if a["slug"] == q or a["name"].lower() == q:
            return a
    for a in catalog:
        if q in a["slug"] or q in a["name"].lower():
            return a
    return None


def cmd_info(query: str, catalog: list[dict[str, Any]]) -> None:
    """Show rich app card."""
    target = find_app(query, catalog)
    if not target:
        print(f"{C_RED}[!] App '{query}' not found in catalog.{C_RESET}")
        return

    name = target["name"]
    category = target["category"]
    desc = target["description"]
    lic = target["license"]
    repo = target["primary_link"]
    mirrored = target["is_mirrored"]
    rel = target.get("release", {})

    print(f"\n{C_YELLOW}╔═══════════════════════════════════════════════════════════════════╗{C_RESET}")
    print(f"{C_YELLOW}║{C_RESET}  {C_BOLD}📱 {name:<60}{C_RESET}{C_YELLOW}║{C_RESET}")
    print(f"{C_YELLOW}╚═══════════════════════════════════════════════════════════════════╝{C_RESET}")
    print(f"  {C_BOLD}Category:{C_RESET}     {category}")
    print(f"  {C_BOLD}License:{C_RESET}      {lic}")
    print(f"  {C_BOLD}Source Repo:{C_RESET}  {repo if repo else 'N/A'}")
    print(f"  {C_BOLD}Mirrored:{C_RESET}     {'✅ YES (Verified Release Mirror)' if mirrored else '🌐 Direct upstream only'}")

    source_tag = rel.get("source_tag") or rel.get("tag_name")
    if source_tag:
        print(f"  {C_BOLD}Version:{C_RESET}      {source_tag}")

    mirror_tag = rel.get("mirror_release_tag")
    if mirror_tag:
        print(f"  {C_BOLD}Mirror Tag:{C_RESET}   {mirror_tag}")

    assets = rel.get("assets", [])
    if assets:
        print(f"\n  {C_BOLD}Available Mirror APK Assets:{C_RESET}")
        for ast in assets:
            fname = ast.get("filename") or ast.get("name", "app.apk")
            size_bytes = ast.get("file_size") or ast.get("size", 0)
            size_kb = size_bytes // 1024
            arch = ast.get("architecture")
            arch_str = f" [{arch}]" if arch else ""
            print(f"    • {C_CYAN}{fname}{C_RESET} ({size_kb} KB){arch_str}")
            sha = ast.get("sha256")
            if sha:
                print(f"      {C_DIM}SHA256: {sha}{C_RESET}")

    print(f"\n  {C_BOLD}Description & Capabilities:{C_RESET}")
    print(f"  {desc}")

    print(f"\n  {C_BOLD}Commands:{C_RESET}")
    if mirrored and assets:
        print(f"    {C_CYAN}shizuku download {target['slug']}{C_RESET}   Download latest verified APK")
        print(f"    {C_CYAN}shizuku install {target['slug']}{C_RESET}    Download and install directly to phone via ADB")
    elif repo:
        print(f"    {C_DIM}Visit upstream releases: {repo}/releases{C_RESET}")
    print()


def cmd_top(catalog: list[dict[str, Any]]) -> None:
    """Show curated Top Picks."""
    top_picks = [
        ("Canta", "Safe debloating engine with Universal Android Debloater community lists"),
        ("Hail", "Freeze and hide apps to eliminate background battery drain"),
        ("Athena", "Global system DNS and firewall manager without requiring VPN"),
        ("App Manager", "Comprehensive package manager with AppOps and tracker blocking"),
        ("Mythara", "Local-first Android AI assistant with device execution tools"),
        ("ShizukuPlus", "Combined Dhizuku & Shizuku with app-hiding and anti-detection"),
        ("Neo-Store", "Modern neo-brutalist F-Droid client with silent installs"),
        ("OmniPrompt", "Keyboard command palette for apps, shell, and system shortcuts"),
    ]

    print(f"\n{C_BOLD}⭐ Curated Top Picks (Essential No-Root Tools):{C_RESET}\n")
    for name, reason in top_picks:
        match = find_app(name, catalog)
        status = f"{C_GREEN}[Mirrored]{C_RESET}" if match and match["is_mirrored"] else ""
        print(f"  {C_YELLOW}★{C_RESET} {C_BOLD}{name:<16}{C_RESET} {status}")
        print(f"    {C_DIM}{reason}{C_RESET}")
        if match and match.get("primary_link"):
            print(f"    {C_CYAN}🔗 {match['primary_link']}{C_RESET}")
        print()


def cmd_status() -> None:
    """Check ADB connection and Shizuku status."""
    print(f"\n{C_BOLD}🔌 Android Device & Shizuku Status:{C_RESET}\n")

    if not shutil.which("adb"):
        print(f"  {C_RED}[X] ADB command not found in PATH.{C_RESET}")
        print("      Please install android-tools (e.g. 'sudo dnf install android-tools' or 'sudo apt install adb').")
        return

    try:
        proc = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        lines = [l.strip() for l in proc.stdout.splitlines() if l.strip() and not l.startswith("List")]
        if not lines:
            print(f"  {C_YELLOW}[!] No Android devices connected.{C_RESET}")
            print("      Connect your phone via USB or Wireless ADB with USB Debugging enabled.")
            return

        print(f"  {C_GREEN}[+] Detected {len(lines)} device(s):{C_RESET}")
        for l in lines:
            parts = l.split()
            serial = parts[0]
            st = parts[1] if len(parts) > 1 else "unknown"
            color = C_GREEN if st == "device" else C_RED
            print(f"      • Serial: {C_BOLD}{serial}{C_RESET} ({color}{st}{C_RESET})")

            if st == "device":
                model = subprocess.run(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], capture_output=True, text=True, timeout=5).stdout.strip()
                version = subprocess.run(["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"], capture_output=True, text=True, timeout=5).stdout.strip()
                sdk = subprocess.run(["adb", "-s", serial, "shell", "getprop", "ro.build.version.sdk"], capture_output=True, text=True, timeout=5).stdout.strip()
                print(f"        Model:   {model} (Android {version}, SDK {sdk})")

                ps_check = subprocess.run(["adb", "-s", serial, "shell", "ps", "-ef", "|", "grep", "shizuku"], capture_output=True, text=True, timeout=5).stdout
                if "moe.shizuku.privileged.api" in ps_check:
                    print(f"        Shizuku: {C_GREEN}● ACTIVE & RUNNING{C_RESET}")
                else:
                    print(f"        Shizuku: {C_YELLOW}○ NOT RUNNING (run 'shizuku activate' to start){C_RESET}")

    except Exception as exc:
        print(f"  {C_RED}[X] Error checking ADB: {exc}{C_RESET}")
    print()


def cmd_activate() -> None:
    """Run Shizuku starter process via ADB."""
    print(f"\n{C_BOLD}⚡ Activating Shizuku on connected device...{C_RESET}\n")

    if not shutil.which("adb"):
        print(f"  {C_RED}[!] ADB is not installed in PATH.{C_RESET}")
        return

    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip() and not l.startswith("List")]
        if not lines or all("device" not in l for l in lines):
            print(f"  {C_RED}[!] No authorized Android device detected.{C_RESET}")
            print("      1. Plug in your phone via USB cable.")
            print("      2. Turn ON Developer Options -> USB Debugging.")
            print("      3. On MIUI / HyperOS: Turn ON 'USB debugging (Security settings)'.")
            return

        print(f"  {C_GREEN}[+] Device found. Sending starter commands...{C_RESET}")

        cmd1 = ["adb", "shell", "sh", "/sdcard/Android/data/moe.shizuku.privileged.api/starter.sh"]
        p1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=15)

        if p1.returncode != 0:
            print("  [*] Primary path failed, trying user_de fallback path...")
            cmd2 = ["adb", "shell", "sh", "/data/user_de/0/moe.shizuku.privileged.api/starter.sh"]
            p2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=15)
            if p2.stdout:
                print(p2.stdout)
        else:
            if p1.stdout:
                print(p1.stdout)

        print(f"  {C_GREEN}✅ Activation command finished.{C_RESET}")
        print("  Open the Shizuku app on your phone to verify it shows 'Shizuku is running (ADB)'.\n")

    except Exception as exc:
        print(f"  {C_RED}[X] Failed to activate Shizuku: {exc}{C_RESET}")


def cmd_download(query: str, catalog: list[dict[str, Any]], dest_dir: str = ".") -> str | None:
    """Download mirrored APK for an app."""
    target = find_app(query, catalog)
    if not target:
        print(f"{C_RED}[!] App '{query}' not found in catalog.{C_RESET}")
        return None

    rel = target.get("release", {})
    assets = rel.get("assets", [])
    apk_asset = next((a for a in assets if (a.get("filename") or a.get("name", "")).endswith(".apk")), None)

    if not apk_asset:
        print(f"{C_YELLOW}[*] App '{target['name']}' does not have a mirrored APK locally.{C_RESET}")
        if target.get("primary_link"):
            print(f"    Download directly from upstream: {target['primary_link']}/releases")
        return None

    mirror_tag = rel.get("mirror_release_tag")
    file_name = apk_asset.get("filename") or apk_asset.get("name", f"{target['slug']}.apk")
    expected_sha256 = apk_asset.get("sha256")

    if mirror_tag:
        apk_url = f"https://github.com/krishna3163/best_shizuku_apps_for_android_no_root/releases/download/{mirror_tag}/{file_name}"
    else:
        apk_url = apk_asset.get("browser_download_url") or apk_asset.get("url")

    if not apk_url:
        print(f"{C_RED}[!] Could not determine download URL for '{target['name']}'.{C_RESET}")
        return None

    dest_folder = Path(dest_dir).resolve()
    dest_folder.mkdir(parents=True, exist_ok=True)
    out_path = dest_folder / file_name

    print(f"\n{C_BOLD}⬇️ Downloading {target['name']} ({file_name})...{C_RESET}")
    print(f"   URL: {apk_url}")

    try:
        req = Request(apk_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShizukuCLI/1.0"})
        hasher = hashlib.sha256()
        with urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if total_size:
                    percent = downloaded * 100 // total_size
                    sys.stdout.write(f"\r   Progress: {percent}% ({downloaded // 1024} / {total_size // 1024} KB)")
                    sys.stdout.flush()

        print(f"\n{C_GREEN}✅ Successfully saved APK to:{C_RESET} {out_path}")

        # Checksum verification
        actual_sha = hasher.hexdigest()
        if expected_sha256:
            if actual_sha.lower() == expected_sha256.lower():
                print(f"  {C_GREEN}🛡️ SHA256 Verified:{C_RESET} {actual_sha[:16]}...")
            else:
                print(f"  {C_RED}⚠️ SHA256 MISMATCH:{C_RESET} Expected {expected_sha256} but got {actual_sha}")
        print()
        return str(out_path)
    except Exception as exc:
        print(f"\n{C_RED}[X] Download failed: {exc}{C_RESET}")
        return None


def cmd_install(query: str, catalog: list[dict[str, Any]]) -> None:
    """Download and install app via ADB."""
    apk_path = cmd_download(query, catalog, dest_dir="/tmp")
    if not apk_path:
        return

    print(f"{C_BOLD}📲 Installing APK onto connected Android device via ADB...{C_RESET}")
    try:
        res = subprocess.run(["adb", "install", "-r", apk_path], capture_output=True, text=True, timeout=60)
        if "Success" in res.stdout:
            print(f"{C_GREEN}✅ App installed successfully on phone!{C_RESET}\n")
        else:
            print(f"{C_RED}[!] ADB installation output:{C_RESET} {res.stdout.strip()} {res.stderr.strip()}\n")
    except Exception as exc:
        print(f"{C_RED}[X] ADB installation failed: {exc}{C_RESET}\n")


def cmd_feeds() -> None:
    """Display ecosystem feeds & links."""
    print(f"\n{C_BOLD}📦 Ecosystem Feeds & Repository Links:{C_RESET}\n")
    print(f"  {C_YELLOW}• F-Droid Third-Party Repo URL:{C_RESET}")
    print("    https://krishna3163.github.io/best_shizuku_apps_for_android_no_root/fdroid/repo")
    print(f"\n  {C_YELLOW}• Obtainium Multi-App Feed JSON:{C_RESET}")
    print("    https://krishna3163.github.io/best_shizuku_apps_for_android_no_root/obtainium.json")
    print(f"\n  {C_YELLOW}• Atom RSS Feed:{C_RESET}")
    print("    https://github.com/krishna3163/best_shizuku_apps_for_android_no_root/raw/main/releases.atom")
    print(f"\n  {C_YELLOW}• Web Portal Companion:{C_RESET}")
    print("    https://shizuku-web.onrender.com")
    print(f"\n  {C_YELLOW}• Main GitHub Repository:{C_RESET}")
    print("    https://github.com/krishna3163/best_shizuku_apps_for_android_no_root")
    print()


def cmd_bot() -> None:
    """Display Telegram bot information."""
    print(f"\n{C_BOLD}🤖 Telegram Search Bot (@krishna0858bot):{C_RESET}\n")
    print("  • Handle:        https://t.me/krishna0858bot")
    print("  • Maintainer:    @kk3163019")
    print("  • Inline Mode:   Type '@krishna0858bot <query>' in ANY chat to share apps")
    print("  • Local Service: systemctl --user status shizuku-telegram-bot.service")
    print()


class InteractivePrompt(cmd.Cmd):
    """Interactive TUI shell for Shizuku CLI."""
    intro = f"{C_BOLD}Welcome to Shizuku Interactive Shell. Type 'help' or 'search <app>' to begin. Type 'exit' to quit.{C_RESET}\n"
    prompt = f"{C_YELLOW}shizuku>{C_RESET} "

    def __init__(self, catalog: list[dict[str, Any]]) -> None:
        super().__init__()
        self.catalog = catalog

    def do_search(self, arg: str) -> None:
        """Search apps: search <keyword>"""
        cmd_search(arg, self.catalog)

    def do_list(self, arg: str) -> None:
        """List apps: list [category]"""
        cmd_list(self.catalog, category_filter=arg if arg else None)

    def do_categories(self, arg: str) -> None:
        """View categories: categories"""
        cmd_categories(self.catalog)

    def do_info(self, arg: str) -> None:
        """View app details: info <app_name>"""
        cmd_info(arg, self.catalog)

    def do_top(self, arg: str) -> None:
        """View top picks: top"""
        cmd_top(self.catalog)

    def do_status(self, arg: str) -> None:
        """Check ADB and Shizuku status: status"""
        cmd_status()

    def do_activate(self, arg: str) -> None:
        """Activate Shizuku on connected phone: activate"""
        cmd_activate()

    def do_download(self, arg: str) -> None:
        """Download mirrored APK: download <app_name>"""
        cmd_download(arg, self.catalog)

    def do_install(self, arg: str) -> None:
        """Install app directly via ADB: install <app_name>"""
        cmd_install(arg, self.catalog)

    def do_feeds(self, arg: str) -> None:
        """View F-Droid & Obtainium feeds: feeds"""
        cmd_feeds()

    def do_exit(self, arg: str) -> bool:
        """Exit interactive shell."""
        print(f"{C_DIM}Goodbye!{C_RESET}")
        return True

    def do_quit(self, arg: str) -> bool:
        """Exit interactive shell."""
        return self.do_exit(arg)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Shizuku Ecosystem CLI & Android ADB Companion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # search
    p_search = subparsers.add_parser("search", aliases=["s"], help="Search apps by keyword")
    p_search.add_argument("query", help="Keyword or app name")

    # list
    p_list = subparsers.add_parser("list", aliases=["ls", "l"], help="Browse catalog")
    p_list.add_argument("--category", "-c", default="", help="Filter by category")
    p_list.add_argument("--limit", "-n", type=int, default=30, help="Maximum items to display")

    # categories
    subparsers.add_parser("categories", aliases=["cats"], help="List all categories")

    # info
    p_info = subparsers.add_parser("info", help="View app details and download links")
    p_info.add_argument("app", help="App name or slug")

    # top
    subparsers.add_parser("top", help="View curated Top Picks")

    # activate
    subparsers.add_parser("activate", aliases=["start"], help="1-Click activate Shizuku via ADB")

    # status
    subparsers.add_parser("status", help="Check ADB device & Shizuku status")

    # download
    p_download = subparsers.add_parser("download", help="Download mirrored APK")
    p_download.add_argument("app", help="App name or slug")
    p_download.add_argument("--output", "-o", default=".", help="Output directory")

    # install
    p_install = subparsers.add_parser("install", help="Download & install APK directly via ADB")
    p_install.add_argument("app", help="App name or slug")

    # feeds
    subparsers.add_parser("feeds", help="View F-Droid & Obtainium feed URLs")

    # bot
    subparsers.add_parser("bot", help="View Telegram Bot status & help")

    # interactive
    subparsers.add_parser("interactive", aliases=["i"], help="Open interactive TUI shell")

    args = parser.parse_args()

    catalog = load_catalog()

    if not args.subcommand or args.subcommand in {"interactive", "i"}:
        print_banner()
        InteractivePrompt(catalog).cmdloop()
        return 0

    if args.subcommand in {"search", "s"}:
        cmd_search(args.query, catalog)
    elif args.subcommand in {"list", "ls", "l"}:
        cmd_list(catalog, category_filter=args.category, limit=args.limit)
    elif args.subcommand in {"categories", "cats"}:
        cmd_categories(catalog)
    elif args.subcommand == "info":
        cmd_info(args.app, catalog)
    elif args.subcommand == "top":
        cmd_top(catalog)
    elif args.subcommand in {"activate", "start"}:
        cmd_activate()
    elif args.subcommand == "status":
        cmd_status()
    elif args.subcommand == "download":
        cmd_download(args.app, catalog, dest_dir=args.output)
    elif args.subcommand == "install":
        cmd_install(args.app, catalog)
    elif args.subcommand == "feeds":
        cmd_feeds()
    elif args.subcommand == "bot":
        cmd_bot()

    return 0


if __name__ == "__main__":
    sys.exit(main())
