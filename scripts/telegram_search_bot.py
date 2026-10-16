"""Telegram App Search Bot for Shizuku & Root Ecosystem.

Allows users to search Android tools, privileged apps, and mirrored releases directly via Telegram.
Uses only the Python standard library so it runs in any environment without pip dependencies.

Usage:
    # Run interactive bot daemon:
    python scripts/telegram_search_bot.py --token "YOUR_TELEGRAM_BOT_TOKEN"

    # Or with environment variable:
    export TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
    python scripts/telegram_search_bot.py

    # One-shot query test (CLI mode):
    python scripts/telegram_search_bot.py --query "canta"
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("telegram-bot")

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
APPS_CONFIG_PATH = ROOT / "config" / "apps.json"

ROW_REGEX = re.compile(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \| (.+) \|\s*$")
LINK_REGEX = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

MAINTAINER_HANDLE = "@kk3163019"
MAINTAINER_LINK = "https://t.me/kk3163019"
REPO_URL = "https://github.com/krishna3163/best_shizuku_apps_for_android_no_root"
WEB_URL = "https://shizuku-web.onrender.com"
DISCUSSIONS_URL = f"{REPO_URL}/discussions"
FDROID_REPO_URL = "https://krishna3163.github.io/best_shizuku_apps_for_android_no_root/fdroid/repo"
OBTAINIUM_URL = "https://krishna3163.github.io/best_shizuku_apps_for_android_no_root/obtainium.json"


def load_catalog() -> list[dict[str, Any]]:
    """Parse apps from README.md tables and apps.json metadata."""
    apps: list[dict[str, Any]] = []
    seen_names = set()

    # Read config/apps.json for mirrored repo slugs
    mirrored_slugs = set()
    if APPS_CONFIG_PATH.exists():
        try:
            with open(APPS_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for item in cfg.get("apps", []):
                    mirrored_slugs.add(item.get("name", "").lower())
                    mirrored_slugs.add(item.get("slug", "").lower())
        except Exception as e:
            logger.warning("Could not read apps.json: %s", e)

    if not README_PATH.exists():
        return apps

    current_category = "General"
    content = README_PATH.read_text(encoding="utf-8")

    for line in content.splitlines():
        if line.startswith("## "):
            current_category = line.lstrip("# ").strip()
            continue

        m = ROW_REGEX.match(line)
        if not m:
            continue

        raw_name, raw_desc, raw_license, raw_links = m.groups()
        raw_name = raw_name.strip()
        raw_desc = raw_desc.strip()
        raw_license = raw_license.strip()
        raw_links = raw_links.strip()

        if raw_name in {"App", "---", ":---", "Library"} or raw_desc == "Description":
            continue

        # Extract markdown link from name if present
        name_link_match = LINK_REGEX.search(raw_name)
        clean_name = name_link_match.group(1) if name_link_match else raw_name
        primary_link = name_link_match.group(2) if name_link_match else ""

        # Extract extra links from the links column
        all_links = LINK_REGEX.findall(raw_links)
        if not primary_link and all_links:
            primary_link = all_links[0][1]

        # Key for deduplication
        key = clean_name.lower().strip()
        if key in seen_names:
            continue
        seen_names.add(key)

        is_mirrored = key in mirrored_slugs or any(m_slug in key for m_slug in mirrored_slugs)

        apps.append({
            "name": clean_name,
            "category": current_category,
            "description": raw_desc,
            "license": raw_license,
            "primary_link": primary_link,
            "links": all_links,
            "is_mirrored": is_mirrored,
        })

    return apps


def search_apps(query: str, catalog: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    """Search catalog by name, category, or description."""
    q = query.lower().strip()
    if not q:
        return []

    exact_matches: list[dict[str, Any]] = []
    starts_with: list[dict[str, Any]] = []
    contains_name: list[dict[str, Any]] = []
    contains_desc: list[dict[str, Any]] = []

    for app in catalog:
        name_l = app["name"].lower()
        desc_l = app["description"].lower()
        cat_l = app["category"].lower()

        if name_l == q:
            exact_matches.append(app)
        elif name_l.startswith(q):
            starts_with.append(app)
        elif q in name_l:
            contains_name.append(app)
        elif q in desc_l or q in cat_l:
            contains_desc.append(app)

    results = exact_matches + starts_with + contains_name + contains_desc
    return results[:limit]


def format_app_card(app: dict[str, Any]) -> str:
    """Format single app details with HTML markup for Telegram."""
    name = html.escape(app["name"])
    category = html.escape(app["category"])
    desc = html.escape(app["description"])
    lic = html.escape(app["license"])

    badge = "📦 <b>Mirrored APK Available</b>" if app.get("is_mirrored") else "🌐 <b>Direct Source</b>"

    text = f"📱 <b>{name}</b> ({lic})\n"
    text += f"🏷️ <i>{category}</i> • {badge}\n"
    text += f"📝 {desc}\n\n"

    # Action links
    link_parts: list[str] = []
    if app.get("primary_link"):
        link_parts.append(f"<a href='{html.escape(app['primary_link'])}'>🔗 Upstream Repo</a>")

    if app.get("is_mirrored"):
        release_link = f"{REPO_URL}/releases"
        link_parts.append(f"<a href='{release_link}'>⬇️ Mirrored Releases</a>")

    for label, url in app.get("links", []):
        if url != app.get("primary_link"):
            link_parts.append(f"<a href='{html.escape(url)}'>{html.escape(label)}</a>")

    if link_parts:
        text += " • ".join(link_parts) + "\n"

    return text


def build_welcome_message() -> str:
    """Generate bot welcome / start message."""
    return (
        "⚡ <b>Welcome to the Shizuku & Root Android Catalog Bot!</b>\n\n"
        "Search through 60+ curated privileged apps, debloaters, firewalls, and no-root tools with mirrored verified APKs.\n\n"
        "<b>Available Commands:</b>\n"
        "• 🔍 <code>/search &lt;name&gt;</code> or type an app name (e.g. <code>canta</code>, <code>dns</code>, <code>hail</code>)\n"
        "• ⭐ <code>/top</code> - Browse top recommended privileged apps\n"
        "• 📊 <code>/stats</code> - View catalog and mirror metrics\n"
        "• 📦 <code>/fdroid</code> - F-Droid & Obtainium setup links\n"
        "• 💬 <code>/community</code> - Join the community chat & discussions\n"
        "• ℹ️ <code>/help</code> - Show this guide\n\n"
        f"🌐 <b>Web Companion:</b> <a href='{WEB_URL}'>shizuku-web</a>\n"
        f"🐙 <b>GitHub:</b> <a href='{REPO_URL}'>best_shizuku_apps_for_android_no_root</a>\n"
        f"👤 <b>Maintainer:</b> {MAINTAINER_HANDLE}"
    )


def build_stats_message(catalog: list[dict[str, Any]]) -> str:
    """Generate stats summary."""
    total = len(catalog)
    mirrored = sum(1 for a in catalog if a.get("is_mirrored"))
    categories = len({a["category"] for a in catalog})

    return (
        "📊 <b>Ecosystem Catalog Statistics</b>\n\n"
        f"• <b>Total Curated Apps:</b> <code>{total}</code>\n"
        f"• <b>Mirrored & Verified Releases:</b> <code>{mirrored}</code>\n"
        f"• <b>Categories:</b> <code>{categories}</code>\n"
        "• <b>Android Support:</b> Android 8.0 - Android 15 (VanillaIceCream)\n"
        "• <b>Architectures:</b> arm64-v8a, armeabi-v7a, x86_64, Universal\n"
        "• <b>VirusTotal / Malware Scanned:</b> 100% Automated\n\n"
        f"🔗 <b>GitHub Repo:</b> <a href='{REPO_URL}'>Browse on GitHub</a>\n"
        f"💬 <b>Discussions:</b> <a href='{DISCUSSIONS_URL}'>Join Discussions</a>"
    )


def build_fdroid_message() -> str:
    """Generate F-Droid / Obtainium guidance."""
    return (
        "📦 <b>One-Tap Updates & Feeds Setup</b>\n\n"
        "<b>1. F-Droid / Neo-Store / Droid-ify:</b>\n"
        "Add this third-party repository URL into your F-Droid client:\n"
        f"<code>{FDROID_REPO_URL}</code>\n\n"
        "<b>2. Obtainium:</b>\n"
        "Import the multi-app JSON feed into Obtainium for automatic in-app updates:\n"
        f"<code>{OBTAINIUM_URL}</code>\n\n"
        "<b>3. Atom RSS Feed:</b>\n"
        f"<code>{REPO_URL}/raw/main/releases.atom</code>"
    )


def build_community_message() -> str:
    """Generate community chat links."""
    return (
        "💬 <b>Community Chat & Discussions</b>\n\n"
        f"• <b>Maintainer Telegram:</b> <a href='{MAINTAINER_LINK}'>{MAINTAINER_HANDLE}</a>\n"
        f"• <b>GitHub Discussions:</b> <a href='{DISCUSSIONS_URL}'>Open a Thread / Q&amp;A</a>\n"
        "• <b>Instagram:</b> <a href='https://www.instagram.com/krishna.0858/?hl=en'>@krishna.0858</a>\n"
        "• <b>LinkedIn:</b> <a href='https://www.linkedin.com/in/krishna0858/'>Krishna's Profile</a>\n\n"
        "Feel free to request apps, suggest automations, or ask troubleshooting questions!"
    )


def call_telegram_api(token: str, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Send an HTTP POST request to Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "ShizukuSearchBot/1.0"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except HTTPError as e:
        logger.error("HTTP %s on %s: %s", e.code, method, e.read().decode("utf-8", "ignore"))
    except URLError as e:
        logger.error("Network error on %s: %s", method, e.reason)
    except Exception as e:
        logger.error("Unexpected error on %s: %s", method, e)
    return None


def send_reply(token: str, chat_id: int | str, text: str, disable_preview: bool = True) -> None:
    """Helper to send HTML-formatted message to chat."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    call_telegram_api(token, "sendMessage", payload)


def handle_text_message(token: str, chat_id: int | str, text: str, catalog: list[dict[str, Any]]) -> None:
    """Route user text message to appropriate command handler."""
    t = text.strip()

    if t in {"/start", "/help"}:
        send_reply(token, chat_id, build_welcome_message(), disable_preview=False)
        return

    if t in {"/stats", "/info"}:
        send_reply(token, chat_id, build_stats_message(catalog))
        return

    if t in {"/fdroid", "/obtainium", "/feed"}:
        send_reply(token, chat_id, build_fdroid_message())
        return

    if t in {"/community", "/chat", "/contact", "/maintainer"}:
        send_reply(token, chat_id, build_community_message(), disable_preview=False)
        return

    if t in {"/top", "/popular"}:
        top_names = ["Shizuku", "Canta", "App Manager", "Hail", "Athena", "ShizukuPlus"]
        matching = [a for a in catalog if a["name"] in top_names]
        reply = "⭐ <b>Top Recommended Shizuku Apps:</b>\n\n"
        for app in matching:
            reply += format_app_card(app) + "\n"
        reply += f"🔍 <i>Type any keyword to search {len(catalog)}+ more apps!</i>"
        send_reply(token, chat_id, reply)
        return

    # Treat as query
    query = t
    if query.startswith("/search"):
        query = query.replace("/search", "", 1).strip()

    if not query:
        send_reply(token, chat_id, "💡 Please specify a name to search, e.g. <code>/search canta</code>")
        return

    results = search_apps(query, catalog)
    if not results:
        reply = (
            f"❌ No apps matching '<b>{html.escape(query)}</b>' found.\n\n"
            f"💡 Try searching for: <code>canta</code>, <code>battery</code>, <code>dns</code>, <code>manager</code>, <code>backup</code>\n"
            f"Or browse all apps at <a href='{WEB_URL}'>shizuku-web</a> or <a href='{REPO_URL}'>GitHub</a>."
        )
        send_reply(token, chat_id, reply)
        return

    reply = f"🔍 <b>Found {len(results)} matching app(s) for '{html.escape(query)}':</b>\n\n"
    for app in results:
        reply += format_app_card(app) + "\n"

    reply += f"🌐 <a href='{WEB_URL}'>Browse full interactive catalog online</a>"
    send_reply(token, chat_id, reply)


def handle_inline_query(token: str, inline_query: dict[str, Any], catalog: list[dict[str, Any]]) -> None:
    """Handle inline queries (@krishna0858bot <query>) for inline sharing across any chat."""
    query_id = inline_query.get("id")
    raw_query = inline_query.get("query", "").strip()

    if not raw_query:
        top_names = ["Shizuku", "Canta", "App Manager", "Hail", "Athena", "ShizukuPlus"]
        matching = [a for a in catalog if a["name"] in top_names]
    else:
        matching = search_apps(raw_query, catalog, limit=10)

    results: list[dict[str, Any]] = []
    for app in matching:
        app_name = app["name"]
        desc = app["description"]
        lic = app["license"]
        card_text = format_app_card(app)

        buttons = []
        if app.get("primary_link"):
            buttons.append({"text": "🔗 Source Repo", "url": app["primary_link"]})
        if app.get("is_mirrored"):
            buttons.append({"text": "⬇️ Download APK", "url": f"{REPO_URL}/releases"})

        item: dict[str, Any] = {
            "type": "article",
            "id": f"app_{abs(hash(app_name))}",
            "title": f"📱 {app_name} ({lic})",
            "description": desc[:100],
            "input_message_content": {
                "message_text": card_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        }
        if buttons:
            item["reply_markup"] = {"inline_keyboard": [buttons]}

        results.append(item)

    payload = {
        "inline_query_id": query_id,
        "results": results,
        "cache_time": 300,
        "is_personal": False,
    }
    call_telegram_api(token, "answerInlineQuery", payload)


def run_long_polling(token: str) -> None:
    """Run interactive long polling loop to receive updates."""
    logger.info("Loading catalog...")
    catalog = load_catalog()
    logger.info("Loaded %d apps into catalog. Starting Telegram poll...", len(catalog))

    offset = 0
    while True:
        try:
            payload = {"offset": offset, "timeout": 25, "allowed_updates": ["message", "inline_query"]}
            resp = call_telegram_api(token, "getUpdates", payload)
            if not resp or not resp.get("ok"):
                time.sleep(3)
                continue

            updates = resp.get("result", [])
            for upd in updates:
                offset = max(offset, upd["update_id"] + 1)

                # Check for inline queries
                inline_q = upd.get("inline_query")
                if inline_q:
                    logger.info("Inline query from %s: %s", inline_q.get("from", {}).get("id"), inline_q.get("query"))
                    handle_inline_query(token, inline_q, catalog)
                    continue

                msg = upd.get("message")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                text = msg.get("text", "")

                if chat_id and text:
                    logger.info("Incoming from %s: %s", chat_id, text)
                    handle_text_message(token, chat_id, text, catalog)

        except KeyboardInterrupt:
            logger.info("Shutting down Telegram Bot...")
            break
        except Exception as e:
            logger.error("Polling loop exception: %s", e)
            time.sleep(3)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Telegram App Search Bot for Shizuku.")
    parser.add_argument("--token", default="", help="Telegram bot token")
    parser.add_argument("--query", default="", help="One-shot search query (CLI mode)")
    args = parser.parse_args()

    token = args.token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

    # CLI one-shot query mode
    if args.query:
        catalog = load_catalog()
        print(f"Catalog contains {len(catalog)} apps.")
        results = search_apps(args.query, catalog)
        print(f"Results for '{args.query}' ({len(results)}):")
        for app in results:
            print(f"- {app['name']} [{app['category']}] ({app['license']}): {app['primary_link']}")
        return 0

    if not token:
        print("Error: Telegram bot token must be provided via --token or TELEGRAM_BOT_TOKEN environment variable.")
        print("Example: python scripts/telegram_search_bot.py --token '123456:ABC-DEF...'")
        print("Or test in CLI query mode: python scripts/telegram_search_bot.py --query 'canta'")
        return 1

    run_long_polling(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
