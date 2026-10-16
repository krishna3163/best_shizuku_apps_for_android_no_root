"""Android APK Inspector: SDK Compatibility, Native Architecture Matrix & Privacy Scorecard.

Extracts metadata, Android target/min SDK, architectures, and permissions directly
from APK files using pure-Python binary parsing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import struct
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional

try:
    from .apk import calculate_sha256
except ImportError:
    from apk import calculate_sha256

logger = logging.getLogger("apk-inspector")

# Android API level to OS version mapping
ANDROID_API_MAP = {
    14: "Android 4.0 (Ice Cream Sandwich)",
    15: "Android 4.0.3",
    16: "Android 4.1 (Jelly Bean)",
    17: "Android 4.2",
    18: "Android 4.3",
    19: "Android 4.4 (KitKat)",
    21: "Android 5.0 (Lollipop)",
    22: "Android 5.1",
    23: "Android 6.0 (Marshmallow)",
    24: "Android 7.0 (Nougat)",
    25: "Android 7.1",
    26: "Android 8.0 (Oreo)",
    27: "Android 8.1",
    28: "Android 9.0 (Pie)",
    29: "Android 10 (Q)",
    30: "Android 11 (R)",
    31: "Android 12 (S)",
    32: "Android 12L",
    33: "Android 13 (Tiramisu)",
    34: "Android 14 (Upside Down Cake)",
    35: "Android 15 (Vanilla Ice Cream)",
    36: "Android 16 (Baklava)",
}

DANGEROUS_PERMISSIONS = {
    "android.permission.READ_CONTACTS": "Read Contacts",
    "android.permission.WRITE_CONTACTS": "Write Contacts",
    "android.permission.READ_CALENDAR": "Read Calendar",
    "android.permission.WRITE_CALENDAR": "Write Calendar",
    "android.permission.ACCESS_FINE_LOCATION": "Precise GPS Location",
    "android.permission.ACCESS_COARSE_LOCATION": "Approximate Location",
    "android.permission.RECORD_AUDIO": "Record Audio / Microphone",
    "android.permission.CAMERA": "Camera Access",
    "android.permission.READ_CALL_LOG": "Read Call Logs",
    "android.permission.WRITE_CALL_LOG": "Write Call Logs",
    "android.permission.READ_SMS": "Read SMS",
    "android.permission.SEND_SMS": "Send SMS",
    "android.permission.RECEIVE_SMS": "Receive SMS",
    "android.permission.MANAGE_EXTERNAL_STORAGE": "All Files Access",
    "android.permission.SYSTEM_ALERT_WINDOW": "Display Over Other Apps",
}


def parse_string_pool_from_axml(axml_data: bytes) -> list[str]:
    """Extract string pool entries from Android Binary XML (AXML)."""
    if len(axml_data) < 8:
        return []

    # Verify AXML magic (0x00080003)
    magic, _ = struct.unpack("<II", axml_data[:8])
    if magic != 0x00080003:
        # Fallback raw ASCII / UTF-8 string extraction
        return [s.decode("utf-8", "ignore") for s in re.findall(b"[\x20-\x7e]{3,}", axml_data)]

    offset = 8
    strings = []

    while offset + 8 <= len(axml_data):
        chunk_type, chunk_size = struct.unpack("<II", axml_data[offset : offset + 8])
        if chunk_size == 0 or offset + chunk_size > len(axml_data):
            break

        # String Pool Chunk Type = 0x00010001
        if chunk_type == 0x00010001 and chunk_size >= 28:
            (
                _,
                _,
                string_count,
                style_count,
                flags,
                strings_start,
                styles_start,
            ) = struct.unpack("<IIIIIII", axml_data[offset : offset + 28])

            is_utf8 = bool(flags & (1 << 8))
            indices_offset = offset + 28
            strings_base = offset + strings_start

            for i in range(string_count):
                idx_ptr = indices_offset + (i * 4)
                if idx_ptr + 4 > len(axml_data):
                    break
                (str_offset,) = struct.unpack("<I", axml_data[idx_ptr : idx_ptr + 4])
                pos = strings_base + str_offset
                if pos >= len(axml_data):
                    continue

                try:
                    if is_utf8:
                        # UTF-8 encoded string: length prefixes then null-terminated
                        u8_len = axml_data[pos]
                        pos += 1
                        if u8_len & 0x80:
                            pos += 1
                        str_bytes_len = axml_data[pos]
                        pos += 1
                        if str_bytes_len & 0x80:
                            pos += 1
                        val = axml_data[pos : pos + str_bytes_len].decode("utf-8", errors="replace")
                    else:
                        # UTF-16LE encoded string
                        (u16_len,) = struct.unpack("<H", axml_data[pos : pos + 2])
                        pos += 2
                        if u16_len & 0x8000:
                            pos += 2
                        str_bytes = axml_data[pos : pos + (u16_len * 2)]
                        val = str_bytes.decode("utf-16le", errors="replace")
                    strings.append(val)
                except Exception:
                    continue
            break

        offset += chunk_size

    if not strings:
        # Fallback to regex on readable patterns
        return [s.decode("utf-8", "ignore") for s in re.findall(b"[\x20-\x7e]{3,}", axml_data)]
    return strings


def extract_manifest_metadata(axml_data: bytes) -> dict[str, Any]:
    """Parse package name, permissions, and SDK info from manifest binary XML."""
    strings = parse_string_pool_from_axml(axml_data)

    permissions = set()
    shizuku_permissions = set()
    dangerous_permissions = set()

    package_name = ""
    version_name = ""

    for s in strings:
        if s.startswith("android.permission.") or ".permission." in s:
            permissions.add(s)
            if "shizuku" in s.lower():
                shizuku_permissions.add(s)
            if s in DANGEROUS_PERMISSIONS:
                dangerous_permissions.add(s)
        elif not package_name and re.match(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$", s):
            if not s.startswith("android.") and not s.startswith("androidx.") and not s.startswith("kotlin."):
                package_name = s

    # Search for SDK levels in manifest integers/attributes
    min_sdk = None
    target_sdk = None

    # Search for minSdkVersion / targetSdkVersion patterns in binary chunks
    for i, s in enumerate(strings):
        if s == "minSdkVersion" and i + 1 < len(strings):
            cand = strings[i + 1]
            if cand.isdigit():
                min_sdk = int(cand)
        elif s == "targetSdkVersion" and i + 1 < len(strings):
            cand = strings[i + 1]
            if cand.isdigit():
                target_sdk = int(cand)
        elif s == "versionName" and i + 1 < len(strings):
            version_name = strings[i + 1]

    # Fallback heuristic if not named directly: inspect integers in attributes
    if min_sdk is None or target_sdk is None:
        int_matches = [int(m) for m in re.findall(rb"[\x15-\x25]", axml_data)]
        valid_sdks = [x for x in int_matches if 21 <= x <= 36]
        if valid_sdks:
            if min_sdk is None:
                min_sdk = min(valid_sdks)
            if target_sdk is None:
                target_sdk = max(valid_sdks)

    min_sdk = min_sdk or 26  # Default fallback Android 8.0+
    target_sdk = target_sdk or 34  # Default fallback Android 14

    return {
        "package_name": package_name or "unknown.package",
        "version_name": version_name or "unknown",
        "min_sdk": min_sdk,
        "min_android_version": ANDROID_API_MAP.get(min_sdk, f"Android API {min_sdk}"),
        "target_sdk": target_sdk,
        "target_android_version": ANDROID_API_MAP.get(target_sdk, f"Android API {target_sdk}"),
        "permissions": sorted(permissions),
        "shizuku_permissions": sorted(shizuku_permissions),
        "dangerous_permissions": sorted(dangerous_permissions),
    }


def compute_privacy_grade(dangerous_count: int, has_shizuku: bool) -> tuple[str, str]:
    """Calculate Privacy Grade and description."""
    if dangerous_count == 0:
        return "A+", "Zero dangerous Android permissions requested (Highest Privacy)"
    if dangerous_count <= 2:
        return "A", "Minimal permissions required for core functions"
    if dangerous_count <= 4:
        return "B", "Moderate permissions requested"
    return "C", "Broad device permissions requested"


def inspect_apk(apk_path: str) -> dict[str, Any]:
    """Full inspection of an APK file."""
    path = Path(apk_path)
    if not path.is_file():
        raise FileNotFoundError(f"APK file not found: {apk_path}")

    file_size = path.stat().st_size
    sha256 = calculate_sha256(str(path))

    architectures = set()
    manifest_info = {}

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()

        # Architecture detection from lib/
        for n in names:
            if n.startswith("lib/") and "/" in n[4:]:
                arch = n.split("/")[1]
                if arch:
                    architectures.add(arch)

        # Parse AndroidManifest.xml
        if "AndroidManifest.xml" in names:
            axml_data = zf.read("AndroidManifest.xml")
            manifest_info = extract_manifest_metadata(axml_data)

    arch_list = sorted(architectures) if architectures else ["universal"]
    dangerous_perms = manifest_info.get("dangerous_permissions", [])
    has_shizuku = bool(manifest_info.get("shizuku_permissions"))

    grade, grade_desc = compute_privacy_grade(len(dangerous_perms), has_shizuku)

    return {
        "file_name": path.name,
        "file_size": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 2),
        "sha256": sha256,
        "architectures": arch_list,
        "architecture_summary": ", ".join(arch_list),
        "package_name": manifest_info.get("package_name", "unknown"),
        "min_sdk": manifest_info.get("min_sdk", 26),
        "min_android": manifest_info.get("min_android_version", "Android 8.0+"),
        "target_sdk": manifest_info.get("target_sdk", 34),
        "target_android": manifest_info.get("target_android_version", "Android 14"),
        "privacy_scorecard": {
            "grade": grade,
            "description": grade_desc,
            "dangerous_count": len(dangerous_perms),
            "dangerous_permissions": dangerous_perms,
            "shizuku_integration": has_shizuku,
            "total_permissions_count": len(manifest_info.get("permissions", [])),
        },
    }


def generate_inspector_markdown(info: dict[str, Any]) -> str:
    """Format APK inspection into markdown cards for release bodies or catalogs."""
    sc = info["privacy_scorecard"]
    lines = [
        "### 📱 Android Compatibility & Architecture Matrix",
        "",
        f"- **Target OS:** {info['target_android']} (API {info['target_sdk']})",
        f"- **Minimum OS:** {info['min_android']} (API {info['min_sdk']}+)",
        f"- **Architectures:** `{info['architecture_summary']}`",
        f"- **Package:** `{info['package_name']}`",
        "",
        "### 🔒 Privacy Scorecard",
        "",
        f"- **Privacy Grade:** **`Grade {sc['grade']}`** ({sc['description']})",
        f"- **Dangerous Permissions:** `{sc['dangerous_count']}` requested",
        f"- **Shizuku Elevated API:** `{'✅ Verified' if sc['shizuku_integration'] else 'ℹ️ Standard'}`",
        "",
    ]
    if sc["dangerous_permissions"]:
        lines.append("<details><summary>View Requested Dangerous Permissions</summary>\n")
        for perm in sc["dangerous_permissions"]:
            label = DANGEROUS_PERMISSIONS.get(perm, perm)
            lines.append(f"- `{perm}` ({label})")
        lines.append("\n</details>\n")

    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Inspect Android APK for SDK compatibility, native architectures, and privacy.")
    parser.add_argument("apk", help="Path to APK file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = inspect_apk(args.apk)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(generate_inspector_markdown(data))
        return 0
    except Exception as exc:
        print(f"Error inspecting APK: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
