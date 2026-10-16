"""NicheForge Phase 5 — Launch checklist.

Pure read-only checks, NO side effects. run_checks() returns a list of
{"id", "label", "status", "detail"} dicts where status is one of
"pass", "fail" or "warn".
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3

try:
    from . import backup as _backup  # pragma: no cover - package use
except ImportError:  # pragma: no cover - standalone script use
    import backup as _backup  # noqa: F401

GB = 1024 ** 3


def _check(id, label, status, detail):
    return {"id": id, "label": label, "status": status, "detail": detail}


def _check_config_present(root):
    path = os.path.join(root, "config.json")
    if os.path.isfile(path):
        return _check("config_present", "config.json present", "pass",
                      f"found at {path} (contents never read)")
    return _check("config_present", "config.json present", "fail",
                  f"missing: {path}")


def _check_password_env():
    if os.environ.get("NICHEFORGE_PASSWORD"):
        return _check("password_env", "NICHEFORGE_PASSWORD set", "pass",
                      "env var is set")
    return _check("password_env", "NICHEFORGE_PASSWORD set", "warn",
                  "not set — needed for AI provider and Facebook features")


def _check_facebook_pages(config):
    if config is None:
        return _check("facebook_pages", "facebook_pages configured", "warn",
                      "not checked (config not loaded)")
    pages = None
    for key in ("facebook_pages", "pages", "fb_pages"):
        if isinstance(config, dict) and key in config:
            pages = config[key]
            break
    if pages is None:
        return _check("facebook_pages", "facebook_pages configured", "warn",
                      "no facebook_pages key found in config")
    count = len(pages) if hasattr(pages, "__len__") else 0
    if count == 14:
        return _check("facebook_pages", "facebook_pages configured", "pass",
                      "14/14 pages configured")
    return _check("facebook_pages", "facebook_pages configured", "warn",
                  f"{count} pages configured, expected 14")


def _check_db(root, db_path):
    path = db_path or os.path.join(root, "nicheforge.db")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - report any db error
        return _check("db_readable", "nicheforge.db readable", "fail",
                      f"cannot open/query {path}: {exc}")
    return _check("db_readable", "nicheforge.db readable", "pass",
                  f"SELECT 1 ok on {path}")


def _check_disk(root):
    try:
        free = shutil.disk_usage(root).free
    except OSError as exc:
        return _check("disk_space", "disk space", "fail", f"cannot stat disk: {exc}")
    gb = free / GB
    if free < GB:
        return _check("disk_space", "disk space", "fail",
                      f"only {gb:.2f} GB free (< 1 GB)")
    if free < 2 * GB:
        return _check("disk_space", "disk space", "warn",
                      f"{gb:.2f} GB free (< 2 GB)")
    return _check("disk_space", "disk space", "pass",
                  f"{gb:.2f} GB free")


def _check_ffmpeg():
    if shutil.which("ffmpeg"):
        return _check("ffmpeg", "ffmpeg present", "pass", "ffmpeg found on PATH")
    return _check("ffmpeg", "ffmpeg present", "warn",
                  "not found — reels/video assembly needs it")


def _check_playwright():
    if importlib.util.find_spec("playwright") is not None:
        return _check("playwright", "playwright installed", "pass",
                      "playwright importable")
    return _check("playwright", "playwright installed", "warn",
                  "not installed — browser track needs it")


def _check_fonts(root):
    fonts_dir = os.path.join(root, "fonts")
    if os.path.isdir(fonts_dir):
        for name in os.listdir(fonts_dir):
            lowered = name.lower()
            if "nastaleeq" in lowered or "noori" in lowered:
                return _check("fonts", "Urdu font present", "pass",
                              f"found {name} under fonts/")
    return _check("fonts", "Urdu font present", "warn",
                  "Jameel Noori Nastaleeq not found under fonts/ — "
                  "overlay studio needs it")


def _check_workspace_dirs(root):
    dna_dir = os.path.join(root, "dna")
    niches = []
    if os.path.isdir(dna_dir):
        niches = sorted(
            f[:-5] for f in os.listdir(dna_dir) if f.endswith(".json")
        )
    if not niches:
        return _check("workspace_dirs", "niche asset dirs", "fail",
                      "no niche definitions found under dna/")
    missing = [
        n for n in niches
        if not os.path.isdir(os.path.join(root, "workspace", "niches", n, "assets"))
    ]
    if missing:
        return _check("workspace_dirs", "niche asset dirs", "fail",
                      f"missing assets dirs: {', '.join(missing)}")
    return _check("workspace_dirs", "niche asset dirs", "pass",
                  f"{len(niches)}/{len(niches)} niche asset dirs present")


def _check_version(root):
    path = os.path.join(root, "VERSION")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                ver = fh.read().strip()
        except OSError:
            ver = "?"
        return _check("version_file", "VERSION file present", "pass",
                      f"version {ver}")
    return _check("version_file", "VERSION file present", "fail",
                  f"missing: {path}")


def run_checks(root, db_path=None, config=None):
    """Run all launch checks. No side effects — pure reads only."""
    return [
        _check_config_present(root),
        _check_password_env(),
        _check_facebook_pages(config),
        _check_db(root, db_path),
        _check_disk(root),
        _check_ffmpeg(),
        _check_playwright(),
        _check_fonts(root),
        _check_workspace_dirs(root),
        _check_version(root),
    ]


def all_pass(checks) -> bool:
    """True if every check has status 'pass'."""
    return all(c["status"] == "pass" for c in checks)


def summary(checks):
    """Return {"pass": n, "warn": n, "fail": n} counts."""
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for c in checks:
        status = c.get("status")
        if status in counts:
            counts[status] += 1
    return counts
