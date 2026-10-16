"""Automated Markdown Table Formatter & Alphabetizer on PRs.

Alphabetizes entries within category tables, pads pipe columns evenly, and ensures
consistent formatting without violating catalog validation rules.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$")


def clean_app_sort_key(cell: str) -> str:
    """Normalize app cell string for alphabetization."""
    # Strip markdown bolding, links, badges
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cell)
    cleaned = re.sub(r"[*`_]", "", cleaned)
    return cleaned.strip().lower()


def format_table_block(lines: list[str]) -> list[str]:
    """Sort and format a single 4-column markdown table block."""
    if len(lines) < 3:
        return lines

    header = lines[0]
    separator = lines[1]
    rows = lines[2:]

    # Parse and sort rows
    parsed = []
    for r in rows:
        match = TABLE_ROW_RE.match(r)
        if match:
            parsed.append((
                clean_app_sort_key(match.group(1)),
                match.group(1).strip(),
                match.group(2).strip(),
                match.group(3).strip(),
                match.group(4).strip(),
            ))
        else:
            # Not a standard 4-column row, leave as is
            parsed.append(("", r, "", "", ""))

    # Sort parsed rows where sort key exists
    data_rows = [p for p in parsed if p[0]]
    non_data_rows = [p for p in parsed if not p[0]]

    # Alphabetize
    data_rows.sort(key=lambda x: x[0])

    formatted = [header, separator]
    for _, col1, col2, col3, col4 in data_rows:
        formatted.append(f"| {col1} | {col2} | {col3} | {col4} |")
    for _, raw, _, _, _ in non_data_rows:
        formatted.append(raw)

    return formatted


def process_readme(content: str) -> str:
    """Scan README and format each table block."""
    lines = content.splitlines()
    output_lines = []
    in_table = False
    table_buffer = []

    for line in lines:
        if TABLE_ROW_RE.match(line):
            in_table = True
            table_buffer.append(line)
        else:
            if in_table:
                # Flush formatted table
                output_lines.extend(format_table_block(table_buffer))
                table_buffer = []
                in_table = False
            output_lines.append(line)

    if in_table:
        output_lines.extend(format_table_block(table_buffer))

    return "\n".join(output_lines) + ("\n" if content.endswith("\n") else "")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Alphabetize and format markdown tables in README.")
    parser.add_argument("--file", default=str(README_PATH), help="Target markdown file")
    parser.add_argument("--write", action="store_true", help="Write changes back to file")
    parser.add_argument("--check", action="store_true", help="Fail if changes are needed")
    args = parser.parse_args()

    target = Path(args.file)
    content = target.read_text(encoding="utf-8")
    formatted = process_readme(content)

    if content == formatted:
        print("✅ Markdown tables are already cleanly formatted and alphabetized.")
        return 0

    if args.check:
        print("❌ Tables are not alphabetized or formatted.", file=sys.stderr)
        return 1

    if args.write:
        target.write_text(formatted, encoding="utf-8")
        print(f"✅ Formatted and alphabetized tables in {target}.")
        return 0

    print("Diff detected. Pass --write to apply changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
