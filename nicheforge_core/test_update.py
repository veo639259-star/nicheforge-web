"""Tests for update.py (self-updater). All runs use a fake root under /tmp —
never touches the real config.json or the real repo."""

import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update

checks = 0


def ok(name):
    global checks
    checks += 1
    print(f"ok - {name}")


def make_root(version="5.0.0"):
    root = tempfile.mkdtemp(prefix="nf-update-")
    with open(os.path.join(root, "VERSION"), "w") as fh:
        fh.write(version)
    os.makedirs(os.path.join(root, "workspace"), exist_ok=True)
    return root


def make_dist(dist_dir, version, extra_files=None):
    """Build a fake nicheforge-<ver>.zip with manifest.json inside."""
    path = os.path.join(dist_dir, f"nicheforge-{version}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({"version": version}))
        zf.writestr("VERSION", version + "\n")
        for name, content in (extra_files or {}).items():
            zf.writestr(name, content)
    return path


# 1. read_version
root = make_root("5.0.0")
assert update.read_version(root) == "5.0.0"
ok("read_version returns stripped VERSION content")

# 2. parse_version ordering
assert update.parse_version("5.1.0") > update.parse_version("5.0.9")
assert update.parse_version("5.0.0") == (5, 0, 0)
try:
    update.parse_version("5.0")
    raise AssertionError("should have raised")
except ValueError:
    pass
ok("parse_version compares dotted triples and rejects bad input")

# 3. check_update finds newest dist and reports availability
dist = tempfile.mkdtemp(prefix="nf-dist-")
make_dist(dist, "5.0.1")
make_dist(dist, "5.1.0")
make_dist(dist, "4.9.9")
res = update.check_update(root, dist)
assert res == {"available": True, "current": "5.0.0", "dist": "5.1.0"}, res
ok("check_update picks newest dist version, available=True")

# 4. check_update: no newer version
root_new = make_root("5.1.0")
res2 = update.check_update(root_new, dist)
assert res2["available"] is False and res2["dist"] == "5.1.0", res2
ok("check_update available=False when already current")

# 5. check_update: empty dist dir
res3 = update.check_update(root, tempfile.mkdtemp(prefix="nf-empty-"))
assert res3 == {"available": False, "current": "5.0.0", "dist": None}, res3
ok("check_update returns dist=None when no zips found")

# 6. apply_update: backup-first, extracts, writes new VERSION
root6 = make_root("5.0.0")
with open(os.path.join(root6, "keep.txt"), "w") as fh:
    fh.write("mine")
dist6 = tempfile.mkdtemp(prefix="nf-dist6-")
z6 = make_dist(dist6, "5.1.0", {"newfile.txt": "hello"})
out = update.apply_update(root6, z6)
assert out["updated_to"] == "5.1.0"
assert os.path.isfile(out["backup"]), "backup missing"
assert "-pre-update" in os.path.basename(out["backup"])
assert update.read_version(root6) == "5.1.0", "VERSION not updated"
assert os.path.isfile(os.path.join(root6, "newfile.txt")), "new file missing"
assert os.path.isfile(os.path.join(root6, "keep.txt")), "existing file clobbered"
ok("apply_update backs up first, extracts, writes new VERSION")

# 7. apply_update refuses zip without manifest.json; error names the backup
root7 = make_root("5.0.0")
bad = os.path.join(tempfile.mkdtemp(), "bad.zip")
with zipfile.ZipFile(bad, "w") as zf:
    zf.writestr("VERSION", "9.9.9\n")
try:
    update.apply_update(root7, bad)
    raise AssertionError("should have raised")
except RuntimeError as exc:
    assert "-pre-update" in str(exc), "backup path missing from error"
    assert update.read_version(root7) == "5.0.0", "VERSION changed on failure"
ok("apply_update refuses zip without manifest.json, error carries backup path")

# 8. apply_update refuses corrupt zip; error names the backup
root8 = make_root("5.0.0")
corrupt = os.path.join(tempfile.mkdtemp(), "corrupt.zip")
with open(corrupt, "wb") as fh:
    fh.write(b"PK\x03\x04" + b"\x00" * 50)
try:
    update.apply_update(root8, corrupt)
    raise AssertionError("should have raised")
except RuntimeError as exc:
    assert "-pre-update" in str(exc), "backup path missing from error"
ok("apply_update refuses corrupt zip, error carries backup path")

print(f"ALL {checks} CHECKS PASSED")
