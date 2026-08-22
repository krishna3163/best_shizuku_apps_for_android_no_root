"""Metadata database for tracking synchronized releases."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("apk-sync")

ROOT = Path(__file__).resolve().parents[1]
RELEASES_DB = ROOT / "data" / "releases.json"
STATUS_DB = ROOT / "data" / "apps-status.json"


def _ensure_data_dir() -> None:
    """Create the data/ directory if it doesn't exist."""
    RELEASES_DB.parent.mkdir(parents=True, exist_ok=True)


def load_releases_db() -> dict[str, Any]:
    """Load the releases metadata database."""
    _ensure_data_dir()
    if RELEASES_DB.exists():
        try:
            return json.loads(RELEASES_DB.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read releases database: %s", exc)
    return {}


def save_releases_db(db: dict[str, Any]) -> None:
    """Save the releases metadata database."""
    _ensure_data_dir()
    RELEASES_DB.write_text(
        json.dumps(db, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_status_db() -> dict[str, Any]:
    """Load the application status database."""
    _ensure_data_dir()
    if STATUS_DB.exists():
        try:
            return json.loads(STATUS_DB.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read status database: %s", exc)
    return {}


def save_status_db(db: dict[str, Any]) -> None:
    """Save the application status database."""
    _ensure_data_dir()
    STATUS_DB.write_text(
        json.dumps(db, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def is_already_synced(
    releases_db: dict[str, Any],
    slug: str,
    source_release_id: int,
) -> bool:
    """Check whether a specific release has already been synchronized."""
    entry = releases_db.get(slug)
    if not entry:
        return False
    return entry.get("source_release_id") == source_release_id


def get_synced_asset_names(
    releases_db: dict[str, Any],
    slug: str,
) -> set[str]:
    """Return set of asset filenames already uploaded for *slug*."""
    entry = releases_db.get(slug)
    if not entry:
        return set()
    return {a.get("filename", "") for a in entry.get("assets", [])}


def update_release_entry(
    releases_db: dict[str, Any],
    slug: str,
    source_repository: str,
    source_release_id: int,
    source_tag: str,
    source_published_at: str,
    assets: list[dict[str, Any]],
    mirror_release_tag: str,
    mirror_release_url: str = "",
) -> None:
    """Create or update a release entry in the database."""
    now = datetime.now(timezone.utc).isoformat()

    existing = releases_db.get(slug, {})
    existing_assets = existing.get("assets", [])

    # Merge assets (don't duplicate)
    existing_filenames = {a["filename"] for a in existing_assets}
    for asset in assets:
        if asset["filename"] not in existing_filenames:
            existing_assets.append(asset)

    releases_db[slug] = {
        "source_repository": source_repository,
        "source_release_id": source_release_id,
        "source_tag": source_tag,
        "source_published_at": source_published_at,
        "synced_at": now,
        "assets": existing_assets if source_release_id == existing.get("source_release_id") else assets,
        "mirror_release_tag": mirror_release_tag,
        "mirror_release_url": mirror_release_url,
    }


def update_status(
    status_db: dict[str, Any],
    slug: str,
    status: str,
    latest_version: str = "",
    error: str = "",
) -> None:
    """Update the status entry for an application.

    Valid statuses: synced, no-update, no-apk, failed, disabled
    """
    now = datetime.now(timezone.utc).isoformat()
    entry = status_db.get(slug, {})
    entry["status"] = status
    entry["last_checked"] = now
    if latest_version:
        entry["latest_version"] = latest_version
    if status == "synced":
        entry["last_synced"] = now
    if error:
        entry["error"] = error
    elif "error" in entry:
        del entry["error"]
    status_db[slug] = entry
