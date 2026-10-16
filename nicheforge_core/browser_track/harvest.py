"""NicheForge Phase 3 — Competitor Harvest (observation only).

Visits competitor/public pages per niche and records lightweight post
signals (snippet, likes, comment count) for idea research. This is
OBSERVATION ONLY — snippets inform what topics are landing; the content
itself is never copied (the ideas-first workflow forbids it).

Runs sequentially with respectful gaps between visits. If a guard hook
fires (rate-limit banner, login wall, captcha), the run STOPS immediately
and logs the stop — never hammer a site that pushes back.

DRY-RUN is the default: with a mock driver nothing touches the network.
"""

import sqlite3
import time
from datetime import datetime, timezone


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _sleep(seconds):
    """Sleep hook kept at module level so tests can monkeypatch it."""
    time.sleep(seconds)


def init_harvest_tables(db_path):
    """Create harvest_targets and harvest_posts tables if missing."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS harvest_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                niche TEXT NOT NULL,
                url TEXT NOT NULL,
                label TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS harvest_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER NOT NULL,
                snippet TEXT DEFAULT '',
                likes INTEGER DEFAULT 0,
                comments_count INTEGER DEFAULT 0,
                posted_at_text TEXT DEFAULT '',
                harvested_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def add_target(db_path, niche, url, label=""):
    """Register a competitor page to observe. Returns the target id."""
    init_harvest_tables(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO harvest_targets (niche, url, label, created_at)"
            " VALUES (?, ?, ?, ?)",
            (niche, url, label, _utc_now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_targets(db_path, niche=None):
    """List registered targets, optionally filtered by niche."""
    init_harvest_tables(db_path)
    conn = _connect(db_path)
    try:
        if niche is None:
            rows = conn.execute(
                "SELECT * FROM harvest_targets ORDER BY id ASC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM harvest_targets WHERE niche = ? ORDER BY id ASC",
                (niche,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def run_harvest(db_path, driver, niche=None, dry_run=True,
                min_gap_secs=30, guards=None):
    """Walk the targets sequentially and store post signals.

    Duck-typed driver must provide:
        goto(url) -> None
        extract_posts() -> list of dicts with keys: snippet, likes,
            comments_count, posted_at_text

    guards: optional callables f(post_dict) -> signal | None. First
    non-None signal STOPS the run immediately (returns stopped info).

    Returns dict: {"visited": n, "posts": m, "stopped": bool, "reason": str}.
    """
    init_harvest_tables(db_path)
    guards = list(guards or [])
    targets = list_targets(db_path, niche)
    visited = 0
    stored = 0
    stopped = False
    reason = ""

    for idx, target in enumerate(targets):
        if idx > 0 and min_gap_secs:
            _sleep(min_gap_secs)
        driver.goto(target["url"])
        posts = driver.extract_posts() or []
        visited += 1
        conn = _connect(db_path)
        try:
            for post in posts:
                post = dict(post or {})
                hit = None
                for guard in guards:
                    hit = guard(post)
                    if hit:
                        break
                if hit:
                    stopped = True
                    reason = "guard signal: %s" % hit
                    conn.commit()
                    return {"visited": visited, "posts": stored,
                            "stopped": True, "reason": reason}
                conn.execute(
                    "INSERT INTO harvest_posts (target_id, snippet, likes,"
                    " comments_count, posted_at_text, harvested_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (target["id"], post.get("snippet", ""),
                     int(post.get("likes", 0) or 0),
                     int(post.get("comments_count", 0) or 0),
                     post.get("posted_at_text", ""), _utc_now()),
                )
                stored += 1
            conn.commit()
        finally:
            conn.close()

    return {"visited": visited, "posts": stored,
            "stopped": stopped, "reason": reason}
