"""Full-Content Multilingual Synchronizer & Translator (i18n).

Translates the entire content of README.md into Simplified Chinese (README.zh-CN.md)
and Russian (README.ru.md) while strictly preserving:
- Markdown formatting (headers, bullet points, blockquotes, callout alerts)
- HTML tags (<details>, <summary>, <div>, etc.)
- Table structures (| col1 | col2 | col3 | col4 |)
- Markdown links [text](url) and URLs
- Code blocks (```...```) and inline code (`...`)
- App names and technical identifiers

Features resilient multi-provider failover (Google GTX + MyMemory + Dictionary)
and persistent disk caching (data/i18n_cache.json).
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("i18n-sync")

ROOT = Path(__file__).resolve().parents[1]
README_EN = ROOT / "README.md"
README_ZH = ROOT / "README.zh-CN.md"
README_RU = ROOT / "README.ru.md"
CACHE_FILE = ROOT / "data" / "i18n_cache.json"

ROW_REGEX = re.compile(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \| (.+) \|\s*$")
LINK_REGEX = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
CODE_REGEX = re.compile(r"`([^`]+)`")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

HEADER_ZH = {
    "Best Shizuku Apps for Android (No Root)": "最优质的安卓免 Root Shizuku 应用合集",
    "Discover the top Shizuku apps, Android root alternatives, wireless ADB tools, debloat apps, and power-user utilities": "探索精选 Shizuku 应用、免 Root 替代方案、无线 ADB 工具、系统卸载精简及极客必备神器",
    "Find the best Shizuku apps to customize Android, remove bloatware, manage apps, improve privacy, automate tasks, and unlock root-like features without rooting your phone.": "发现最优质的 Shizuku 应用，无需 Root 即可自定义安卓、精简系统预装、管理应用权限、增强隐私保护并实现自动化操作。",
    "What is Shizuku?": "什么是 Shizuku？",
    "App Categories": "应用分类",
    "Top Picks": "精选推荐",
    "My Top Picks": "博主精选推荐",
    "Community Chat": "社区交流群",
    "Community Chat & Discussions": "社区聊天与互动讨论",
    "Join Community": "加入社区",
    "Join the Community": "参与社区贡献",
    "Resources": "相关资源",
    "About": "关于本项目",
    "Why This List?": "为什么整理这个列表？",
    "Popular Search Topics": "热门搜索关键词",
    "Table of Contents": "目录导航",
    "App": "应用名称",
    "Description": "功能简介与 Shizuku 用例",
    "License": "开源许可",
    "Links": "相关链接",
    "App Management": "应用管理与冻结",
    "Automation": "自动化控制",
    "Customization": "个性化界面定制",
    "Development": "开发者调试与工具",
    "File Management": "高级文件管理",
    "Gaming": "游戏优化与辅助",
    "Networking": "网络与系统防火墙",
    "Privacy and Security": "隐私保护与权限安全",
    "System Utilities": "系统运维与深度工具",
    "Miscellaneous content": "综合工具与更多应用",
    "Other apps (FOSS alternatives to premium apps)": "其他精选应用（替代付费专有软件的开源良心作品）",
    "Android Power-User Ecosystem": "安卓极客与高级用户生态圈",
    "Connect with Maintainer": "联系维护者与社交主页",
    "Contributors & Community Wall": "贡献者与社区荣誉墙",
    "Automatic APK Updates": "APK 自动同步与镜像",
    "Disclaimer": "免责声明",
    "Show Your Support": "支持与鼓励",
    "License & Attribution": "开源许可证与鸣谢",
}

HEADER_RU = {
    "Best Shizuku Apps for Android (No Root)": "Лучшие приложения Shizuku для Android (Без Root)",
    "Discover the top Shizuku apps, Android root alternatives, wireless ADB tools, debloat apps, and power-user utilities": "Откройте для себя лучшие приложения Shizuku, альтернативы Root, утилиты беспроводного ADB и инструменты для продвинутых пользователей",
    "Find the best Shizuku apps to customize Android, remove bloatware, manage apps, improve privacy, automate tasks, and unlock root-like features without rooting your phone.": "Найдите лучшие приложения Shizuku для настройки Android, удаления встроенного мусора, контроля конфиденциальности и автоматизации без рутирования устройства.",
    "What is Shizuku?": "Что такое Shizuku?",
    "App Categories": "Категории приложений",
    "Top Picks": "Избранное",
    "My Top Picks": "Лучшие рекомендации",
    "Community Chat": "Чат сообщества",
    "Community Chat & Discussions": "Чат сообщества и обсуждения",
    "Join Community": "Сообщество",
    "Join the Community": "Присоединиться к сообществу",
    "Resources": "Ресурсы",
    "About": "О проекте",
    "Why This List?": "Почему этот список?",
    "Popular Search Topics": "Популярные поисковые темы",
    "Table of Contents": "Содержание",
    "App": "Приложение",
    "Description": "Описание и сценарий использования",
    "License": "Лицензия",
    "Links": "Ссылки",
    "App Management": "Управление приложениями и заморозка",
    "Automation": "Автоматизация",
    "Customization": "Кастомизация и оформление",
    "Development": "Разработка и отладка",
    "File Management": "Файловые менеджеры",
    "Gaming": "Игры и оптимизация",
    "Networking": "Сеть и системный фаервол",
    "Privacy and Security": "Безопасность и приватность",
    "System Utilities": "Системные утилиты",
    "Miscellaneous content": "Разное и дополнительные инструменты",
    "Other apps (FOSS alternatives to premium apps)": "Другие приложения (FOSS альтернативы платным сервисам)",
    "Android Power-User Ecosystem": "Экосистема для энтузиастов Android",
    "Connect with Maintainer": "Связаться с автором и соцсети",
    "Contributors & Community Wall": "Стена контрибьюторов и сообщества",
    "Automatic APK Updates": "Автоматическое обновление APK",
    "Disclaimer": "Отказ от ответственности",
    "Show Your Support": "Поддержите проект",
    "License & Attribution": "Лицензия и благодарности",
}


def load_cache() -> dict[str, dict[str, str]]:
    """Load translation cache from disk."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Could not read i18n cache: %s", e)
    return {"zh-CN": {}, "ru": {}}


def save_cache(cache: dict[str, dict[str, str]]) -> None:
    """Save translation cache to disk."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Could not write i18n cache: %s", e)


def translate_multiprovider(text: str, target_lang: str) -> str:
    """Translate string with resilient multi-provider failover."""
    clean = text.strip()
    if not clean:
        return text

    # Provider 1: Google GTX
    try:
        params = urlencode({"client": "gtx", "sl": "en", "tl": target_lang, "dt": "t", "q": clean})
        url = f"https://translate.googleapis.com/translate_a/single?{params}"
        req = Request(url, headers={"User-Agent": random.choice(USER_AGENTS)})
        with urlopen(req, timeout=3) as resp:
            data = json.load(resp)
            res = "".join(p[0] for p in data[0] if p and p[0]).strip()
            if res:
                return res
    except Exception:
        pass

    # Provider 2: MyMemory API
    try:
        langpair = f"en|{target_lang}"
        params = urlencode({"q": clean, "langpair": langpair})
        url = f"https://api.mymemory.translated.net/get?{params}"
        req = Request(url, headers={"User-Agent": random.choice(USER_AGENTS)})
        with urlopen(req, timeout=3) as resp:
            data = json.load(resp)
            res = data.get("responseData", {}).get("translatedText", "").strip()
            if res and not res.startswith("MYMEMORY WARNING"):
                return res
    except Exception:
        pass

    return clean


def translate_text_with_cache(
    text: str,
    target_lang: str,
    cache: dict[str, dict[str, str]],
) -> str:
    """Translate string with cache lookup and placeholder protection."""
    clean = text.strip()
    if not clean or len(clean) < 2:
        return text

    mapping = HEADER_ZH if target_lang == "zh-CN" else HEADER_RU
    if clean in mapping:
        return mapping[clean]

    emoji_prefix_match = re.match(r"^([^\w\s]+\s*)(.+)$", clean)
    if emoji_prefix_match:
        sym_prefix, rest_text = emoji_prefix_match.groups()
        if rest_text in mapping:
            return f"{sym_prefix}{mapping[rest_text]}"

    lang_cache = cache.setdefault(target_lang, {})
    if clean in lang_cache:
        return lang_cache[clean]

    # Protect code snippets
    codes: list[str] = []
    def code_repl(m):
        codes.append(m.group(0))
        return f" __CODE_{len(codes)-1}__ "

    protected = CODE_REGEX.sub(code_repl, clean)

    # Protect links
    links: list[tuple[str, str]] = []
    def link_repl(m):
        links.append((m.group(1), m.group(2)))
        return f" __LINK_{len(links)-1}__ "

    protected = LINK_REGEX.sub(link_repl, protected)

    result = translate_multiprovider(protected, target_lang)

    # Restore links
    for i, (label, url) in enumerate(links):
        label_trans = mapping.get(label, label)
        rep = f"[{label_trans}]({url})"
        result = re.sub(rf"\s*__\s*LINK_{i}\s*__\s*", f" {rep} ", result, flags=re.IGNORECASE)

    # Restore code blocks
    for i, code_val in enumerate(codes):
        result = re.sub(rf"\s*__\s*CODE_{i}\s*__\s*", f" {code_val} ", result, flags=re.IGNORECASE)

    result = re.sub(r" +", " ", result).strip()
    lang_cache[clean] = result
    return result


def translate_table_row(
    line: str,
    target_lang: str,
    cache: dict[str, dict[str, str]],
) -> str:
    """Translate single markdown table row preserving table pipes and URLs."""
    m = ROW_REGEX.match(line)
    if not m:
        return line

    col1, col2, col3, col4 = m.groups()
    col1 = col1.strip()
    col2 = col2.strip()
    col3 = col3.strip()
    col4 = col4.strip()

    if col1 in {"---", ":---", ":---:", "---:"} or col2 == "---":
        return line

    if col1 in {"App", "Library"} and col2 == "Description":
        if target_lang == "zh-CN":
            return "| 应用名称 | 功能介绍与 Shizuku 用例 | 开源许可 | 相关链接 |"
        else:
            return "| Приложение | Описание и использование Shizuku | Лицензия | Ссылки |"

    trans_desc = translate_text_with_cache(col2, target_lang, cache)
    trans_desc = trans_desc.replace("|", "\\|")

    link_mapping_zh = {
        "GitHub": "GitHub 源码",
        "Releases": "下载发布",
        "Release": "下载发布",
        "Play Store": "谷歌商店",
        "F-Droid": "F-Droid 仓库",
        "Website": "官方网站",
        "Docs": "开发文档",
        "Guide": "使用指南",
    }
    link_mapping_ru = {
        "GitHub": "Исходники GitHub",
        "Releases": "Скачать APK",
        "Release": "Скачать APK",
        "Play Store": "Google Play",
        "F-Droid": "F-Droid репозиторий",
        "Website": "Официальный сайт",
        "Docs": "Документация",
        "Guide": "Инструкция",
    }
    lmap = link_mapping_zh if target_lang == "zh-CN" else link_mapping_ru
    trans_links = col4
    for en_label, loc_label in lmap.items():
        trans_links = trans_links.replace(f"[{en_label}](", f"[{loc_label}](")

    return f"| {col1} | {trans_desc} | {col3} | {trans_links} |"


def translate_full_markdown(
    content: str,
    target_lang: str,
    cache: dict[str, dict[str, str]],
) -> str:
    """Translate complete markdown content preserving structure."""
    lines = content.splitlines()
    translated_lines: list[str] = []
    in_code_block = False

    # Pre-collect all translatable text not yet cached
    to_fetch: list[str] = []
    lang_cache = cache.get(target_lang, {})
    mapping = HEADER_ZH if target_lang == "zh-CN" else HEADER_RU

    for line in lines:
        l = line.strip()
        if not l or l.startswith("```") or l.startswith("<img") or l.startswith("[!["):
            continue

        m = ROW_REGEX.match(line)
        if m:
            c1, c2, _, _ = m.groups()
            c1, c2 = c1.strip(), c2.strip()
            if c1 not in {"App", "---", ":---", ":---:", "Library"} and c2 != "Description":
                if c2 and c2 not in lang_cache and c2 not in mapping:
                    to_fetch.append(c2)
            continue

        list_m = re.match(r"^(\s*[-*+]\s+)(.+)$", line)
        if list_m:
            item_text = list_m.group(2).strip()
            sub_m = re.match(r"^(\*\*[^*]+\*\*)\s*[-–—:]\s*(.+)$", item_text)
            txt = sub_m.group(2).strip() if sub_m else item_text
            if txt and txt not in lang_cache and txt not in mapping:
                to_fetch.append(txt)
            continue

        if line.startswith("#"):
            match_h = re.match(r"^(#+)\s+(.+)$", line)
            if match_h:
                htext = match_h.group(2).strip()
                if htext and htext not in lang_cache and htext not in mapping:
                    to_fetch.append(htext)
            continue

        summary_m = re.match(r"^(<summary><h[1-6]>)(.*?)(</h[1-6]></summary>)$", l)
        if summary_m:
            stext = summary_m.group(2).strip()
            if stext and stext not in lang_cache and stext not in mapping:
                to_fetch.append(stext)
            continue

        if l.startswith(">"):
            qtext = l.lstrip("> ").strip()
            if qtext and qtext not in lang_cache and qtext not in mapping:
                to_fetch.append(qtext)
            continue

        if not l.startswith("<") and not l.endswith(">") and l not in lang_cache and l not in mapping:
            to_fetch.append(l)

    unique_to_fetch = list(set(to_fetch))
    if unique_to_fetch:
        logger.info(
            "Translating %d new descriptions to %s with rate-managed worker pool...",
            len(unique_to_fetch),
            target_lang,
        )
        completed_count = 0

        def worker_task(item: str) -> tuple[str, str]:
            res = translate_text_with_cache(item, target_lang, cache)
            time.sleep(0.04)  # Small pacing to avoid rate limits
            return item, res

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_text = {executor.submit(worker_task, d): d for d in unique_to_fetch}
            for future in as_completed(future_to_text):
                try:
                    future.result()
                    completed_count += 1
                    if completed_count % 30 == 0:
                        logger.info("Progress: %d / %d translated (%s)", completed_count, len(unique_to_fetch), target_lang)
                        save_cache(cache)
                except Exception as exc:
                    logger.debug("Worker task exception: %s", exc)

        save_cache(cache)

    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            translated_lines.append(line)
            continue

        if in_code_block:
            translated_lines.append(line)
            continue

        if line.strip().startswith("[![") or line.strip().startswith("<img"):
            translated_lines.append(line)
            continue

        if line.strip().startswith("|") and line.strip().endswith("|"):
            translated_lines.append(translate_table_row(line, target_lang, cache))
            continue

        if line.startswith("#"):
            match_h = re.match(r"^(#+)\s+(.+)$", line)
            if match_h:
                prefix, htext = match_h.groups()
                trans_h = translate_text_with_cache(htext, target_lang, cache)
                translated_lines.append(f"{prefix} {trans_h}")
                continue

        summary_m = re.match(r"^(<summary><h[1-6]>)(.*?)(</h[1-6]></summary>)$", line.strip())
        if summary_m:
            tag_open, title_text, tag_close = summary_m.groups()
            trans_title = translate_text_with_cache(title_text, target_lang, cache)
            translated_lines.append(f"{tag_open}{trans_title}{tag_close}")
            continue

        callout_m = re.match(r"^(>\s*\[!(TIP|NOTE|IMPORTANT|WARNING|CAUTION)\])(.*)$", line.strip())
        if callout_m:
            translated_lines.append(line)
            continue

        if line.strip().startswith(">"):
            quote_text = line.lstrip("> ").strip()
            trans_quote = translate_text_with_cache(quote_text, target_lang, cache)
            translated_lines.append(f"> {trans_quote}")
            continue

        list_m = re.match(r"^(\s*[-*+]\s+)(.+)$", line)
        if list_m:
            bullet_prefix, item_text = list_m.groups()
            sub_m = re.match(r"^(\*\*[^*]+\*\*)\s*[-–—:]\s*(.+)$", item_text)
            if sub_m:
                b_title, b_desc = sub_m.groups()
                trans_desc = translate_text_with_cache(b_desc, target_lang, cache)
                translated_lines.append(f"{bullet_prefix}{b_title} - {trans_desc}")
            else:
                trans_item = translate_text_with_cache(item_text, target_lang, cache)
                translated_lines.append(f"{bullet_prefix}{trans_item}")
            continue

        if not line.strip() or line.strip().startswith("<") or line.strip().endswith(">"):
            translated_lines.append(line)
            continue

        trans_line = translate_text_with_cache(line, target_lang, cache)
        translated_lines.append(trans_line)

    result_md = "\n".join(translated_lines) + "\n"

    lang_banner = (
        "> 🌐 **Language / 语言 / Язык:** "
        "[ 🇬🇧 English ](README.md) • "
        f"[ 🇨🇳 简体中文{' (当前)' if target_lang == 'zh-CN' else ''} ](README.zh-CN.md) • "
        f"[ 🇷🇺 Русский{' (Текущий)' if target_lang == 'ru' else ''} ](README.ru.md)\n\n"
    )

    if "> 🌐 **Language" in result_md:
        result_md = re.sub(r"> 🌐 \*\*Language[^\n]+\n+", lang_banner, result_md, count=1)
    else:
        title_marker = "# "
        if title_marker in result_md:
            pos = result_md.index(title_marker)
            eol = result_md.find("\n", pos)
            result_md = result_md[:eol + 1] + "\n" + lang_banner + result_md[eol + 1:]

    return result_md


def translate_content(
    content: str,
    target_lang: str,
    cache: Optional[dict[str, dict[str, str]]] = None,
) -> str:
    """Convenience helper to translate markdown content using cached or loaded cache."""
    if cache is None:
        cache = load_cache()
    return translate_full_markdown(content, target_lang, cache)


def sync_readme(target_lang: str, cache: dict[str, dict[str, str]]) -> Path:
    """Read English README, translate completely, and write localized file."""
    if not README_EN.exists():
        raise FileNotFoundError(f"English README not found at {README_EN}")

    content = README_EN.read_text(encoding="utf-8")
    target_file = README_ZH if target_lang == "zh-CN" else README_RU

    logger.info("Translating README.md to %s...", target_lang)
    start_time = time.time()
    translated = translate_full_markdown(content, target_lang, cache)
    elapsed = time.time() - start_time

    target_file.write_text(translated, encoding="utf-8")
    logger.info("Saved %s in %.2fs (%d characters).", target_file.name, elapsed, len(translated))
    return target_file


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Full-content multilingual README synchronizer.")
    parser.add_argument("--lang", choices=["zh-CN", "ru", "all"], default="all")
    parser.add_argument("--clear-cache", action="store_true", help="Clear translation cache before run")
    args = parser.parse_args()

    if args.clear_cache and CACHE_FILE.exists():
        CACHE_FILE.unlink()
        logger.info("Cleared cache file.")

    cache = load_cache()

    try:
        if args.lang in {"zh-CN", "all"}:
            sync_readme("zh-CN", cache)
        if args.lang in {"ru", "all"}:
            sync_readme("ru", cache)
        save_cache(cache)
        print("✅ Full multilingual translation complete!")
        return 0
    except Exception as e:
        logger.error("Multilingual sync failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
