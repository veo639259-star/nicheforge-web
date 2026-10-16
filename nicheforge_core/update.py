"""NicheForge Phase 5 — Self-updater (simple and safe).

No network — updates come from a local dist folder containing files named
nicheforge-<ver>.zip. Every update is backup-first: on any exception the
raised error carries the backup path so the user can restore.
"""

from __future__ import annotations

import os
import re
import sys
import zipfile

# Make sure sibling module backup.py is importable in both standalone and
# package use.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup as _backup  # noqa: E402

DIST_PATTERN = re.compile(r"^nicheforge-(\d+\.\d+\.\d+)\.zip$")


def read_version(root) -> str:
    """Return the version string from <root>/VERSION (stripped)."""
    with open(os.path.join(root, "VERSION"), "r", encoding="utf-8") as fh:
        return fh.read().strip()


def parse_version(version) -> tuple:
    """Parse a dotted version triple into (major, minor, patch) ints."""
    parts = str(version).strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"bad version (expected x.y.z): {version!r}")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise ValueError(f"bad version (non-numeric part): {version!r}")


def check_update(root, dist_dir):
    """Look for nicheforge-<ver>.zip files in dist_dir.

    Returns {"available": bool, "current": str, "dist": str|None}.
    available=True only when the newest dist version is newer than current.
    """
    current = read_version(root)
    best = None
    best_parsed = None
    if os.path.isdir(dist_dir):
        for name in os.listdir(dist_dir):
            match = DIST_PATTERN.match(name)
            if not match:
                continue
            try:
                parsed = parse_version(match.group(1))
            except ValueError:
                continue
            if best_parsed is None or parsed > best_parsed:
                best_parsed = parsed
                best = match.group(1)
    if best is None:
        return {"available": False, "current": current, "dist": None}
    available = best_parsed > parse_version(current)
    return {"available": available, "current": current, "dist": best}


def apply_update(root, zip_path):
    """Apply an update zip over root — backup FIRST, then verify, then extract.

    The zip must pass zipfile.testzip() and contain manifest.json.
    The new version is written into VERSION from the manifest.

    Returns {"updated_to": ver, "backup": path}.
    On any exception, the raised message includes the backup path so the
    user can restore.
    """
    backup_path = _backup.create_backup(root, name_suffix="-pre-update")
    try:
        if not os.path.isfile(zip_path) or not zipfile.is_zipfile(zip_path):
            raise ValueError(f"not a valid update zip: {zip_path}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            if zf.testzip() is not None:
                raise ValueError(f"update zip failed integrity check: {zip_path}")
            names = zf.namelist()
            if "manifest.json" not in names:
                raise ValueError(f"refusing update: no manifest.json in {zip_path}")
            import json

            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            version = manifest.get("version")
            if not version:
                raise ValueError(f"refusing update: manifest has no version in {zip_path}")
            for name in names:
                target = os.path.normpath(os.path.join(root, name))
                if not target.startswith(os.path.normpath(root) + os.sep) \
                        and target != os.path.normpath(root):
                    raise ValueError(f"refusing update: unsafe path in zip: {name}")
            zf.extractall(root)
        # New version written only after a clean extract.
        with open(os.path.join(root, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write(str(version).strip() + "\n")
        return {"updated_to": str(version).strip(), "backup": backup_path}
    except Exception as exc:
        raise RuntimeError(
            f"update failed ({exc}); restore from backup: {backup_path}"
        ) from exc
