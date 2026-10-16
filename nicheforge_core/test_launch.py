"""Tests for launch.py (launch checklist). All checks run against a fake root
under /tmp — never touches the real config.json."""

import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import launch

checks = 0


def ok(name):
    global checks
    checks += 1
    print(f"ok - {name}")


def by_id(checks_list):
    return {c["id"]: c for c in checks_list}


def make_root(niches=("aangan", "deen")):
    root = tempfile.mkdtemp(prefix="nf-launch-")
    with open(os.path.join(root, "config.json"), "w") as fh:  # fake
        fh.write('{"fake": true}')
    conn = sqlite3.connect(os.path.join(root, "nicheforge.db"))
    conn.execute("SELECT 1")
    conn.close()
    os.makedirs(os.path.join(root, "fonts"), exist_ok=True)
    with open(os.path.join(root, "fonts", "JameelNooriNastaleeq.ttf"), "w") as fh:
        fh.write("fake")
    with open(os.path.join(root, "VERSION"), "w") as fh:
        fh.write("5.0.0")
    os.makedirs(os.path.join(root, "dna"), exist_ok=True)
    for n in niches:
        with open(os.path.join(root, "dna", f"{n}.json"), "w") as fh:
            fh.write("{}")
        os.makedirs(os.path.join(root, "workspace", "niches", n, "assets"), exist_ok=True)
    return root


os.environ["NICHEFORGE_PASSWORD"] = "test-secret"
root = make_root()
results = launch.run_checks(root)
d = by_id(results)

# 1. ten checks, each with id/label/status/detail
assert len(results) == 10, f"expected 10 checks, got {len(results)}"
for c in results:
    assert set(c) == {"id", "label", "status", "detail"}, f"bad shape: {c}"
    assert c["status"] in ("pass", "fail", "warn")
ok("run_checks returns 10 well-formed check dicts")

# 2. config present passes without reading contents
assert d["config_present"]["status"] == "pass"
ok("config.json present -> pass")

# 3. config missing -> fail
os.remove(os.path.join(root, "config.json"))
d2 = by_id(launch.run_checks(root))
assert d2["config_present"]["status"] == "fail"
ok("config.json missing -> fail")
with open(os.path.join(root, "config.json"), "w") as fh:
    fh.write('{"fake": true}')

# 4. password env: warn when missing, pass when set
del os.environ["NICHEFORGE_PASSWORD"]
assert by_id(launch.run_checks(root))["password_env"]["status"] == "warn"
os.environ["NICHEFORGE_PASSWORD"] = "test-secret"
assert by_id(launch.run_checks(root))["password_env"]["status"] == "pass"
ok("NICHEFORGE_PASSWORD warn when missing, pass when set")

# 5. facebook_pages only when config dict passed
assert d["facebook_pages"]["status"] == "warn"
assert "not checked" in d["facebook_pages"]["detail"]
pages14 = {"facebook_pages": {f"p{i}": {} for i in range(14)}}
d5 = by_id(launch.run_checks(root, config=pages14))
assert d5["facebook_pages"]["status"] == "pass"
pages3 = {"facebook_pages": {"a": {}, "b": {}, "c": {}}}
d6 = by_id(launch.run_checks(root, config=pages3))
assert d6["facebook_pages"]["status"] == "warn"
ok("facebook_pages: warn when not loaded, pass at 14, warn otherwise")

# 6. db readable: pass on real sqlite, fail on bad path
assert d["db_readable"]["status"] == "pass"
d7 = by_id(launch.run_checks(root, db_path="/nonexistent/dir/x.db"))
assert d7["db_readable"]["status"] == "fail"
ok("nicheforge.db readable -> pass; bad path -> fail")

# 7. disk space: valid status; /tmp may be a tiny tmpfs, so accept any verdict
assert d["disk_space"]["status"] in ("pass", "warn", "fail")
assert "GB" in d["disk_space"]["detail"]
ok("disk space check returns a verdict with GB detail")

# 8. ffmpeg / playwright report warn (not fail) when missing
assert d["ffmpeg"]["status"] in ("pass", "warn")
assert d["playwright"]["status"] in ("pass", "warn")
ok("ffmpeg and playwright report pass or warn (never fail)")

# 9. fonts: pass with nastaleeq, warn without
assert d["fonts"]["status"] == "pass"
shutil.rmtree(os.path.join(root, "fonts"))
assert by_id(launch.run_checks(root))["fonts"]["status"] == "warn"
ok("fonts: pass when Nastaleeq present, warn when missing")

# 10. workspace dirs driven by dna filenames
assert d["workspace_dirs"]["status"] == "pass"
shutil.rmtree(os.path.join(root, "workspace", "niches", "deen", "assets"))
d10 = by_id(launch.run_checks(root))["workspace_dirs"]
assert d10["status"] == "fail" and "deen" in d10["detail"]
ok("workspace dirs read from dna filenames; missing assets -> fail")

# 11. VERSION present -> pass; missing -> fail
assert d["version_file"]["status"] == "pass"
os.remove(os.path.join(root, "VERSION"))
assert by_id(launch.run_checks(root))["version_file"]["status"] == "fail"
ok("VERSION file present -> pass; missing -> fail")

# 12. all_pass and summary
clean = make_root(niches=("aangan",))
res = launch.run_checks(clean)
s = launch.summary(res)
assert s["pass"] + s["warn"] + s["fail"] == 10
assert launch.all_pass(res) == (s["fail"] == 0 and s["warn"] == 0)
ok("all_pass and summary counts consistent")

print(f"ALL {checks} CHECKS PASSED")
