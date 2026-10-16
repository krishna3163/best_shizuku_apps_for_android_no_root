"""Validate and maintain the no-root Shizuku app catalog."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
START = "<!-- AUTO-DISCOVERED-SHIZUKU-APPS:START -->"
END = "<!-- AUTO-DISCOVERED-SHIZUKU-APPS:END -->"
ROW = re.compile(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \| (.+) \|\s*$")


def read() -> tuple[str, list[dict[str, str]]]:
    content = README.read_text(encoding="utf-8")
    entries = []
    for line in content.splitlines():
        match = ROW.match(line)
        if match and match.group(1) not in {"App", "---", ":---", "Library"} and match.group(2) != "Description":
            entries.append(dict(name=match.group(1).strip(), description=match.group(2).strip(), license=match.group(3).strip(), links=match.group(4).strip()))
    return content, entries


def heading_anchors(content: str) -> set[str]:
    anchors = set()
    for heading in re.findall(r"^#{1,6} (.+)$", content, re.MULTILINE):
        plain = re.sub(r"[^a-z0-9 -]", "", heading.lower()).strip()
        normalized = re.sub(r"\s+", "-", plain)
        anchors.add(normalized)
        if heading[:1] and not heading[0].isascii():
            anchors.add(f"-{normalized}")
        if " & " in heading:
            anchors.add(normalized.replace("-", "--", 1))
            anchors.add(f"-{normalized.replace('-', '--', 1)}")
    return anchors


def check(task: str) -> None:
    content, entries = read()
    urls = re.findall(r"https?://[^)\s<>]+", content)
    if task == "links":
        bad = [url for url in urls if any(x in url for x in ("file+.vscode-resource", "vscode-resource", "bit.ly/", "tinyurl.com/"))]
        if bad:
            raise ValueError(f"Unsafe or local URLs: {', '.join(bad)}")
    elif task == "duplicates":
        names = [entry["name"].lower() for entry in entries]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        for name in duplicates:
            print(f"WARN repeated app name across categories: {name}")
    elif task == "toc":
        anchors = set(re.findall(r"\]\(#([^)]+)\)", content))
        headings = heading_anchors(content)
        headings.update(re.findall(r'<details id="([^"]+)">', content))
        missing = sorted(anchors - headings)
        if missing:
            raise ValueError(f"Missing TOC anchors: {', '.join(missing)}")
    elif task == "tables":
        if not entries:
            raise ValueError("No app table rows found")
        print(f"Parsed {len(entries)} app rows")
    elif task == "licenses":
        missing = [entry["name"] for entry in entries if not entry["license"]]
        if missing:
            raise ValueError(f"Missing licenses: {', '.join(missing)}")
    elif task == "labels":
        for entry in entries:
            if entry["name"] == "_No new projects discovered yet._":
                continue
            if entry["links"] in {"See project page", "See project"}:
                continue
            if not re.search(r"\[[^]]+\]\(https?://", entry["links"]):
                raise ValueError(f"Missing link label: {entry['name']}")
    elif task == "shizuku":
        if "shizuku" not in content.lower() or "no root" not in content.lower():
            raise ValueError("Shizuku/no-root context is missing")
    elif task == "security":
        if any(url.lower().startswith(("javascript:", "data:")) for url in urls):
            raise ValueError("Unsafe URL scheme found")
    elif task == "featured":
        if any(not entry["description"] for entry in entries if "⭐" in entry["name"]):
            raise ValueError("Featured app has no description")
    elif task == "stats":
        print(f"Apps: {len(entries)}; links: {len(urls)}")
    elif task == "sort":
        print("Sorting check is advisory because categories and featured apps define ordering.")
    elif task == "issue-form":
        if not (ROOT / ".github/ISSUE_TEMPLATE/app-suggestion.yml").exists():
            raise ValueError("App suggestion form is missing")
    elif task == "workflow":
        if not list((ROOT / ".github/workflows").glob("*.yml")):
            raise ValueError("No workflows found")
    elif task == "site":
        if not (ROOT / "scripts/build_site.py").exists():
            raise ValueError("Site generator is missing")
    elif task == "discovery":
        if START not in content or END not in content:
            raise ValueError("Auto-discovery markers are missing")
    else:
        raise ValueError(f"Unknown task: {task}")
    print(f"PASS: {task}")


def search() -> list[dict[str, str]]:
    content, _ = read()
    known = {url.lower().rstrip("/") for url in re.findall(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", content)}
    found = {}
    queries = ("shizuku android app", "shizuku android tool", "android wireless adb app", "android debloat shizuku")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "shizuku-catalog-discovery/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for query in queries:
        params = urlencode({"q": query, "sort": "updated", "order": "desc", "per_page": 20})
        request = Request(f"https://api.github.com/search/repositories?{params}", headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                for item in json.load(response).get("items", []):
                    url = item.get("html_url", "").rstrip("/")
                    if url.lower() not in known and not item.get("fork") and not item.get("archived") and item.get("name"):
                        found[url.lower()] = {"name": item["name"], "description": item.get("description") or "Shizuku-compatible Android project discovered by the daily scanner.", "url": url}
        except Exception as exc:
            print(f"WARN search failed for query '{query}': {exc}", file=sys.stderr)
    return sorted(found.values(), key=lambda item: item["name"].lower())


def update(entries: list[dict[str, str]]) -> None:
    content = README.read_text(encoding="utf-8")
    start = content.index(START) + len(START)
    end = content.index(END, start)

    # Preserve already discovered entries so daily scanner doesn't clobber them
    block = content[start:end]
    existing_entries: dict[str, dict[str, str]] = {}
    for line in block.splitlines():
        match = ROW.match(line)
        if match and match.group(1).strip() not in {"App", "---", ":---", "_No new projects discovered yet._"}:
            raw_app = match.group(1).strip()
            link_match = re.search(r"\((https://github\.com/[^)]+)\)", raw_app)
            if not link_match:
                link_match = re.search(r"\((https://github\.com/[^)]+)\)", match.group(4))
            url = link_match.group(1).rstrip("/") if link_match else ""
            clean_name = re.sub(r"\[|\]|\*|\([^)]+\)", "", raw_app).strip()
            if url:
                existing_entries[url.lower()] = {
                    "name": clean_name,
                    "description": match.group(2).strip(),
                    "license": match.group(3).strip(),
                    "url": url,
                }

    for item in entries:
        url_key = item["url"].lower().rstrip("/")
        if url_key not in existing_entries:
            existing_entries[url_key] = item

    all_entries = sorted(existing_entries.values(), key=lambda item: item["name"].lower())

    rows = [
        '<details id="discovered-apps">',
        "<summary><h2>🔍 Auto-Discovered Shizuku Apps</h2></summary>",
        "",
        "| App | Description | License | Links |",
        "|:---|:---|:---|:---|",
    ]
    if all_entries:
        for item in all_entries:
            clean_desc = item["description"].replace("|", "\\|")
            rows.append(f"| **[{item['name']}]({item['url']})** | {clean_desc} | {item.get('license', 'See project')} | [GitHub]({item['url']}) |")
    else:
        rows.append("| _No new projects discovered yet._ | The daily scanner will add matching projects here. | — | — |")
    rows.append("")
    rows.append("</details>")
    README.write_text(content[:start] + "\n\n" + "\n".join(rows) + "\n\n" + content[end:], encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task")
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()
    try:
        if args.discover:
            update(search())
        else:
            check(args.task)
    except (ValueError, HTTPError, URLError) as error:
        print(f"FAIL: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())