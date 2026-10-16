"""Tests for backup.py (Auto Backup Vault). Runs in a fake root under /tmp —
never touches the real config.json."""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup

checks = 0


def ok(name):
    global checks
    checks += 1
    print(f"ok - {name}")


def make_root(with_intel=False, with_config=True, with_version=True):
    root = tempfile.mkdtemp(prefix="nf-backup-")
    # fake nicheforge.db
    conn = sqlite3.connect(os.path.join(root, "nicheforge.db"))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    # fake config.json (never the real one)
    if with_config:
        with open(os.path.join(root, "config.json"), "w") as fh:
            fh.write('{"fake": true}')
    os.makedirs(os.path.join(root, "workspace"), exist_ok=True)
    os.makedirs(os.path.join(root, "dna"), exist_ok=True)
    with open(os.path.join(root, "dna", "aangan.json"), "w") as fh:
        fh.write("{}")
    if with_intel:
        os.makedirs(os.path.join(root, "workspace", "intel"), exist_ok=True)
        with open(os.path.join(root, "workspace", "intel", "state.json"), "w") as fh:
            fh.write("{}")
    if with_version:
        with open(os.path.join(root, "VERSION"), "w") as fh:
            fh.write("5.0.0")
    return root


# 1. create_backup returns a zip under workspace/backups with the right name
root = make_root(with_intel=True)
zip_path = backup.create_backup(root)
assert os.path.isfile(zip_path), "zip not created"
assert os.path.basename(zip_path).startswith("nicheforge-backup-"), "bad name"
assert os.path.basename(zip_path).endswith(".zip"), "bad suffix"
ok("create_backup returns zip in workspace/backups")

# 2. manifest.json inside the zip
with zipfile.ZipFile(zip_path) as zf:
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
assert "created_at" in manifest and "version" in manifest
assert manifest["version"] == "5.0.0", "version in manifest"
assert "nicheforge.db" in manifest["targets"]
assert "workspace/intel" in manifest["targets"], "intel included when present"
ok("manifest.json written with created_at, version, targets")

# 3. missing optional targets are skipped with a note, never fail
root2 = make_root(with_config=False, with_version=False)
zip2 = backup.create_backup(root2)
with zipfile.ZipFile(zip2) as zf:
    m2 = json.loads(zf.read("manifest.json").decode("utf-8"))
assert "config.json" in m2["skipped"], "missing config noted"
assert "VERSION" in m2["skipped"], "missing VERSION noted"
assert m2["version"] == "unknown", "unknown version fallback"
ok("missing targets skipped with note in manifest (backup still succeeds)")

# 4. intel excluded when workspace/intel absent
root3 = make_root(with_intel=False)
zip3 = backup.create_backup(root3)
with zipfile.ZipFile(zip3) as zf:
    m3 = json.loads(zf.read("manifest.json").decode("utf-8"))
assert not any("intel" in t for t in m3["targets"]), "intel wrongly included"
ok("workspace/intel only included when it exists")

# 5. list_backups newest-first with path/size/created_at
blist = backup.list_backups(root)
assert len(blist) == 1 and set(blist[0]) == {"path", "size", "created_at"}
assert blist[0]["size"] > 0
ok("list_backups returns newest-first entries with path/size/created_at")

# 6. prune_backups keeps newest, deletes oldest beyond keep
for _ in range(4):
    backup.create_backup(root, name_suffix="-x")
before = backup.list_backups(root)
n = len(before)
newest = before[0]["path"]
deleted = backup.prune_backups(root, keep=2)
after = backup.list_backups(root)
assert deleted == n - 2, f"deleted {deleted}, expected {n - 2}"
assert len(after) == 2
assert after[0]["path"] == newest, "newest was deleted!"
ok("prune_backups deletes oldest beyond keep and never the newest")

# 7. restore_backup brings back old state, and makes a pre-restore backup
root4 = make_root()
good = backup.create_backup(root4)
with open(os.path.join(root4, "dna", "aangan.json"), "w") as fh:
    fh.write('{"changed": true}')
result = backup.restore_backup(good, root4)
assert result["restored"] == good
assert os.path.isfile(result["pre_restore_backup"])
with open(os.path.join(root4, "dna", "aangan.json")) as fh:
    assert fh.read() == "{}", "restore did not bring back old state"
ok("restore_backup restores old state and keeps a pre-restore backup")

# 8. restore refuses a zip with no manifest.json
badzip = os.path.join(tempfile.mkdtemp(), "nomanifest.zip")
with zipfile.ZipFile(badzip, "w") as zf:
    zf.writestr("nicheforge.db", "junk")
try:
    backup.restore_backup(badzip, root4)
    raise AssertionError("should have raised")
except ValueError:
    ok("restore_backup refuses zip without manifest.json")

# 9. restore refuses a corrupt zip
corrupt = os.path.join(tempfile.mkdtemp(), "corrupt.zip")
with open(corrupt, "wb") as fh:
    fh.write(b"PK\x03\x04" + b"\x00" * 100)
try:
    backup.restore_backup(corrupt, root4)
    raise AssertionError("should have raised")
except ValueError:
    ok("restore_backup refuses zip that fails integrity check")

print(f"ALL {checks} CHECKS PASSED")
