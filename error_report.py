"""NicheForge Web — central error reporting.

Every pipeline exception (idea gen, captions, image gen, posting, browser
automation) flows through log_error(), which records it in three places:

1. SQLite table ``nf_errors`` (same DB as the core app) — for the admin panel.
2. ``error_logs/<error_id>.log`` — full traceback on disk.
3. ``hidden_files/alerts.jsonl`` — one JSON line per error; Jarvis's monitor
   reads this file to see failures without touching the DB.

On cloud hosts (Railway/Render) the local filesystem is ephemeral, so
log_error() ALSO tries ``ALERT_WEBHOOK_URL`` (POST JSON) when set, and every
alert is exposed at ``/admin/api/alerts`` for HTTP polling.
"""

import datetime
import functools
import json
import os
import sqlite3
import traceback
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
ERROR_LOG_DIR = os.path.join(ROOT, "error_logs")
HIDDEN_DIR = os.path.join(ROOT, "hidden_files")
ALERTS_PATH = os.path.join(HIDDEN_DIR, "alerts.jsonl")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def init_error_tables(db_path):
    """Create nf_errors table (idempotent)."""
    os.makedirs(ERROR_LOG_DIR, exist_ok=True)
    os.makedirs(HIDDEN_DIR, exist_ok=True)
    if not os.path.isfile(ALERTS_PATH):
        open(ALERTS_PATH, "a").close()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nf_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                niche TEXT NOT NULL DEFAULT 'global',
                stage TEXT NOT NULL DEFAULT 'unknown',
                error_type TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                retries INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _post_webhook(payload):
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8).read()
    except Exception:
        pass  # webhook is best-effort; local records are the source of truth


def log_error(db_path, niche="global", stage="unknown", exc=None, message="",
              extra=None):
    """Record one pipeline error everywhere. Returns the error id.

    exc: an exception instance (traceback captured automatically).
    message: fallback / additional message when exc is None.
    extra: optional dict merged into the JSONL alert.
    """
    if exc is not None:
        error_type = type(exc).__name__
        msg = str(exc) or error_type
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        error_type = (extra or {}).get("error_type", "Error")
        msg = message or error_type
        tb = (extra or {}).get("traceback", "")

    ts = utc_now()
    init_error_tables(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO nf_errors (ts, niche, stage, error_type, message, status)"
            " VALUES (?, ?, ?, ?, ?, 'open')",
            (ts, niche or "global", stage or "unknown", error_type, msg[:2000]),
        )
        error_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # Full traceback on disk.
    try:
        with open(os.path.join(ERROR_LOG_DIR, "%d.log" % error_id), "w",
                  encoding="utf-8") as fh:
            fh.write("ts: %s\nniche: %s\nstage: %s\nerror_type: %s\nmessage: %s\n\n%s"
                     % (ts, niche, stage, error_type, msg, tb))
    except Exception:
        pass

    # One-line alert for Jarvis's monitor.
    alert = {
        "ts": ts,
        "error_id": error_id,
        "niche": niche or "global",
        "stage": stage or "unknown",
        "error_type": error_type,
        "message": msg[:500],
    }
    if extra:
        alert.update({k: v for k, v in extra.items()
                      if k not in alert and k != "traceback"})
    try:
        with open(ALERTS_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(alert, ensure_ascii=False) + "\n")
    except Exception:
        pass

    _post_webhook(alert)
    return error_id


def reported(db_path, niche="global", stage="unknown"):
    """Decorator: run fn, and log any exception via log_error() then re-raise."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                log_error(db_path, niche=niche, stage=stage, exc=exc)
                raise
        return wrapper
    return deco


def list_errors(db_path, niche=None, status=None, limit=100):
    init_error_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM nf_errors"
        clauses, params = [], []
        if niche:
            clauses.append("niche = ?")
            params.append(niche)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def mark_resolved(db_path, error_id):
    init_error_tables(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE nf_errors SET status = 'resolved' WHERE id = ?",
                     (error_id,))
        conn.commit()
    finally:
        conn.close()


def bump_retry(db_path, error_id):
    init_error_tables(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE nf_errors SET retries = retries + 1, status = 'retried'"
            " WHERE id = ?",
            (error_id,),
        )
        conn.commit()
    finally:
        conn.close()


def read_traceback(error_id):
    path = os.path.join(ERROR_LOG_DIR, "%d.log" % int(error_id))
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return ""


def recent_alerts(limit=50):
    """Read the tail of alerts.jsonl for Jarvis / the admin API."""
    if not os.path.isfile(ALERTS_PATH):
        return []
    out = []
    try:
        with open(ALERTS_PATH, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out
