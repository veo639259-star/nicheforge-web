"""NicheForge Phase 5 — Auto Backup Vault.

Safe, automatic backups of the whole NicheForge state. No secrets are
ever written anywhere except inside the backup zip itself, alongside the
original config.json it was copied from.
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime, timezone


# Relative to the repo root. Optional entries that are missing are skipped
# with a note in the manifest — a missing optional target never fails the
# backup.
BACKUP_TARGETS = ["nicheforge.db", "config.json", "workspace", "dna", "VERSION"]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_targets(root):
    """Return the full BACKUP_TARGETS list, adding workspace/intel if present."""
    targets = list(BACKUP_TARGETS)
    intel_dir = os.path.join(root, "workspace", "intel")
    if os.path.isdir(intel_dir) and "workspace/intel" not in targets:
        targets.append("workspace/intel")
    return targets


def _read_version(root) -> str:
    try:
        with open(os.path.join(root, "VERSION"), "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return "unknown"


def _backup_name(suffix: str = "") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"nicheforge-backup-{stamp}{suffix}.zip"


def _default_dest_dir(root) -> str:
    return os.path.join(root, "workspace", "backups")


def create_backup(root, dest_dir=None, name_suffix="") -> str:
    """Zip the backup targets into <dest_dir>/nicheforge-backup-<stamp>.zip.

    Writes manifest.json inside the zip: {created_at, version, targets,
    skipped}. Missing optional targets are skipped with a note in the
    manifest; the backup itself never fails because of a missing target.
    Returns the zip path.
    """
    dest_dir = dest_dir or _default_dest_dir(root)
    os.makedirs(dest_dir, exist_ok=True)

    targets = _resolve_targets(root)
    included = []
    skipped = []
    for target in targets:
        full = os.path.join(root, target)
        if os.path.exists(full):
            included.append(target)
        else:
            skipped.append(target)

    zip_path = os.path.join(dest_dir, _backup_name(name_suffix))

    manifest = {
        "created_at": _utcnow_iso(),
        "version": _read_version(root),
        "targets": included,
        "skipped": skipped,
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        written = set()
        # Never back up the backup destination (or the zip being written) —
        # walking into it causes a read/write feedback loop on the same file.
        dest_abs = os.path.abspath(dest_dir)
        zip_abs = os.path.abspath(zip_path)

        def add_file(fpath):
            arcname = os.path.relpath(fpath, root)
            if arcname in written:
                return
            if os.path.abspath(fpath).startswith(dest_abs + os.sep):
                return
            if os.path.abspath(fpath) == zip_abs:
                return
            zf.write(fpath, arcname)
            written.add(arcname)

        for target in included:
            full = os.path.join(root, target)
            if os.path.isdir(full):
                for dirpath, _dirnames, filenames in os.walk(full):
                    for filename in filenames:
                        add_file(os.path.join(dirpath, filename))
            else:
                add_file(full)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return zip_path


def list_backups(root):
    """Newest-first list of backups: [{path, size, created_at}, ...]."""
    dest_dir = _default_dest_dir(root)
    if not os.path.isdir(dest_dir):
        return []
    backups = []
    for name in os.listdir(dest_dir):
        if not (name.startswith("nicheforge-backup-") and name.endswith(".zip")):
            continue
        path = os.path.join(dest_dir, name)
        stat = os.stat(path)
        backups.append(
            {
                "path": path,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    backups.sort(key=lambda b: b["created_at"], reverse=True)
    return backups


def prune_backups(root, keep=7) -> int:
    """Delete oldest backups beyond `keep`. NEVER deletes the newest.

    Returns the number of backups deleted.
    """
    backups = list_backups(root)
    if len(backups) <= max(keep, 1):
        return 0
    to_delete = backups[max(keep, 1):]
    deleted = 0
    for entry in to_delete:
        try:
            os.remove(entry["path"])
            deleted += 1
        except OSError:
            continue
    return deleted


def restore_backup(zip_path, root):
    """Restore a backup zip over root — SAFETY FIRST.

    1. Creates a fresh backup of the current state (suffixed -pre-restore).
    2. Verifies the zip: zipfile.testzip() must pass and manifest.json must exist.
    3. Extracts the zip over root.

    Returns {"restored": zip_path, "pre_restore_backup": path}.
    Raises ValueError if the zip has no manifest.json or fails the zip check.
    """
    if not os.path.isfile(zip_path):
        raise ValueError(f"backup not found: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"not a valid zip file: {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        if zf.testzip() is not None:
            raise ValueError(f"zip integrity check failed: {zip_path}")
        if "manifest.json" not in zf.namelist():
            raise ValueError(f"refusing restore: no manifest.json in {zip_path}")

    # Safety backup of current state BEFORE touching anything.
    pre_restore = create_backup(root, name_suffix="-pre-restore")

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            # Guard against zip-slip style paths.
            target = os.path.normpath(os.path.join(root, name))
            if not target.startswith(os.path.normpath(root) + os.sep) and target != os.path.normpath(root):
                raise ValueError(f"refusing restore: unsafe path in zip: {name}")
        zf.extractall(root)

    return {"restored": zip_path, "pre_restore_backup": pre_restore}
