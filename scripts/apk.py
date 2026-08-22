"""APK detection, selection, validation, and checksum utilities."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import struct
import zipfile
from typing import Any, Optional

logger = logging.getLogger("apk-sync")

# Architecture preference order (lower index = higher priority)
ARCH_PRIORITY = ["universal", "arm64-v8a", "arm64", "armeabi-v7a", "armeabi", "x86_64", "x86"]

# Default patterns for rejection
DEFAULT_EXCLUDE_PATTERNS = [r"(?i).*debug.*", r"(?i).*unsigned.*", r"(?i).*test.*"]

# Known non-APK extensions to reject
REJECT_EXTENSIONS = {".aab", ".zip", ".tar.gz", ".gz", ".jar", ".txt", ".json", ".sha256", ".asc", ".sig", ".md5", ".pem", ".aar"}


def is_apk_candidate(filename: str) -> bool:
    """Return True if *filename* looks like an APK (by extension)."""
    return filename.lower().endswith(".apk")


def matches_patterns(filename: str, patterns: list[str]) -> bool:
    """Return True if *filename* matches any of the regex *patterns*."""
    for pattern in patterns:
        if re.search(pattern, filename, re.IGNORECASE):
            return True
    return False


def detect_architecture(filename: str) -> str:
    """Attempt to detect architecture from the APK filename."""
    lower = filename.lower()
    for arch in ARCH_PRIORITY:
        if arch in lower:
            return arch
    return "unknown"


def filter_assets(
    assets: list[dict[str, Any]],
    asset_patterns: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Filter release assets to only valid APK candidates.

    1. Keep only files matching *asset_patterns* (default: ``.*\\.apk$``).
    2. Remove files matching any *exclude_patterns*.
    3. Reject known non-APK extensions.
    """
    if asset_patterns is None:
        asset_patterns = [r"(?i).*\.apk$"]
    if exclude_patterns is None:
        exclude_patterns = list(DEFAULT_EXCLUDE_PATTERNS)

    result: list[dict[str, Any]] = []
    for asset in assets:
        name: str = asset.get("name", "")

        # Must match at least one asset pattern
        if not matches_patterns(name, asset_patterns):
            continue

        # Must not match any exclude pattern
        if matches_patterns(name, exclude_patterns):
            logger.debug("Excluded by pattern: %s", name)
            continue

        # Reject known non-APK extensions (safety net)
        ext = os.path.splitext(name)[1].lower()
        if ext in REJECT_EXTENSIONS:
            continue

        # Must actually end in .apk
        if not is_apk_candidate(name):
            continue

        result.append(asset)

    return result


def select_best_assets(
    assets: list[dict[str, Any]],
    preferred_architectures: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Select APK assets using architecture preference.

    If a 'universal' variant exists, return it plus any architecture-specific
    variants.  If multiple remain and no preference resolves them, return all.
    """
    if not assets:
        return []

    if len(assets) == 1:
        return assets

    if preferred_architectures is None:
        preferred_architectures = list(ARCH_PRIORITY)

    # Tag each asset with its detected architecture
    tagged: list[tuple[dict[str, Any], str]] = []
    for asset in assets:
        arch = detect_architecture(asset["name"])
        tagged.append((asset, arch))

    # If there is a universal build, include it
    # Also include all arch-specific variants (users may want a specific arch)
    # This follows the spec: "Prefer uploading all valid APK variants"
    return assets


def normalize_filename(filename: str, slug: str, version: str) -> str:
    """Produce a safe, normalized filename.

    Only normalize when the original name contains unsafe characters.
    Prefer preserving the upstream filename when already safe.
    """
    # Check if the filename is already safe
    safe_chars = set("abcdefghijklmnopqrstuvwxyz0123456789-_.")
    if all(c in safe_chars for c in filename.lower()):
        return filename

    # Normalize
    base, ext = os.path.splitext(filename)
    normalized = base.lower()
    normalized = re.sub(r"[^\w\-.]", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    normalized = normalized.strip("-")

    return f"{normalized}{ext.lower()}"


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------

def validate_apk(filepath: str) -> tuple[bool, str]:
    """Validate a downloaded APK file.

    Returns (is_valid, message).
    """
    # File exists
    if not os.path.exists(filepath):
        return False, "File does not exist"

    # File size > 0
    size = os.path.getsize(filepath)
    if size == 0:
        return False, "File is empty"

    # Extension check
    if not filepath.lower().endswith(".apk"):
        return False, "File does not have .apk extension"

    # Valid ZIP archive (APKs are ZIP files)
    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            # Check for AndroidManifest.xml (required in every APK)
            names = zf.namelist()
            if "AndroidManifest.xml" not in names:
                return False, "No AndroidManifest.xml found (not a valid APK)"
            # Check for classes.dex (most APKs have this)
            has_dex = any(n.endswith(".dex") for n in names)
            if not has_dex:
                logger.warning("No .dex file found in %s — may be a special APK", filepath)
    except zipfile.BadZipFile:
        return False, "Not a valid ZIP/APK archive"
    except Exception as exc:
        return False, f"Error reading APK: {exc}"

    return True, f"Valid APK ({size:,} bytes)"


def calculate_sha256(filepath: str) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def create_checksum_file(apk_path: str, sha256_hash: str) -> str:
    """Create a .sha256 checksum sidecar file.

    Returns the path to the checksum file.
    """
    checksum_path = apk_path + ".sha256"
    filename = os.path.basename(apk_path)
    with open(checksum_path, "w", encoding="utf-8") as fh:
        fh.write(f"{sha256_hash}  {filename}\n")
    return checksum_path


def extract_apk_metadata(filepath: str) -> dict[str, Any]:
    """Extract basic metadata from an APK without modifying it.

    This is best-effort and does not require Android build tools.
    """
    metadata: dict[str, Any] = {
        "file_size": os.path.getsize(filepath),
        "sha256": calculate_sha256(filepath),
    }

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            names = zf.namelist()
            # Detect architectures from lib/ directory
            lib_archs = set()
            for name in names:
                if name.startswith("lib/") and "/" in name[4:]:
                    arch = name.split("/")[1]
                    if arch:
                        lib_archs.add(arch)
            if lib_archs:
                metadata["native_architectures"] = sorted(lib_archs)

            # Count DEX files
            dex_files = [n for n in names if n.endswith(".dex")]
            metadata["dex_count"] = len(dex_files)

            # Check for signing info
            has_v1_sig = any(n.startswith("META-INF/") and n.endswith((".RSA", ".DSA", ".EC")) for n in names)
            metadata["has_v1_signature"] = has_v1_sig

    except Exception as exc:
        logger.debug("Could not extract APK metadata: %s", exc)

    return metadata
