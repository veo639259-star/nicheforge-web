"""NicheForge Offline Queue (Phase 5).

A durable FIFO work queue for anything that must survive a crash, a lost
network link, or a paused pipeline: publishing jobs, retried API calls,
user-approved items waiting on a flaky downstream.

Storage contract — an approved user item is NEVER lost:
  * Items only transition queued -> retrying -> done. They are never
    deleted by the replay loop.
  * Failed items (attempts exhausted) stay in the table permanently for
    the user to inspect; only ``purge_done()`` removes rows, and only
    those already marked done (default: older than 30 days).

Schema:
  offline_queue(id INTEGER PK, kind TEXT, payload_json TEXT,
                status TEXT, attempts INT DEFAULT 0, last_error TEXT,
                created_at TEXT, updated_at TEXT)
  status is one of: queued | retrying | done | failed
"""

import json
import sqlite3
from datetime import datetime, timezone

VALID_STATUSES = {"queued", "retrying", "done", "failed"}
_PENDING = ("queued", "retrying")
_MAX_ERROR_CHARS = 500


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_offline_tables(db_path):
    """Create offline_queue if it doesn't exist."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS offline_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- enqueue

def queue_work(db_path, kind, payload):
    """Append a job; returns its id. ``payload`` must be a JSON-able dict."""
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    init_offline_tables(db_path)
    now = _utc_now_iso()
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO offline_queue"
            " (kind, payload_json, status, attempts, last_error,"
            "  created_at, updated_at)"
            " VALUES (?, ?, 'queued', 0, '', ?, ?)",
            (kind, json.dumps(payload), now, now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_queue(db_path, status=None):
    """FIFO (oldest first) list of queued jobs as dicts; optional status filter."""
    init_offline_tables(db_path)
    sql = ("SELECT id, kind, payload_json, status, attempts, last_error,"
           " created_at, updated_at FROM offline_queue")
    params = []
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError("status must be one of %s" % sorted(VALID_STATUSES))
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY id ASC"
    conn = _connect(db_path)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------- replay

def _mark_done(db_path, item_id):
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE offline_queue SET status = 'done', updated_at = ?"
            " WHERE id = ?",
            (_utc_now_iso(), item_id),
        )
        conn.commit()
    finally:
        conn.close()


def _record_attempt(db_path, item, error, max_attempts):
    """Bump attempts, store a truncated error, transition status.

    Returns the new status: 'retrying' while attempts remain, 'failed'
    once max_attempts is reached. Never deletes the row.
    """
    attempts = int(item["attempts"]) + 1
    new_status = "failed" if attempts >= max_attempts else "retrying"
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE offline_queue"
            " SET attempts = ?, last_error = ?, status = ?, updated_at = ?"
            " WHERE id = ?",
            (attempts, str(error)[:_MAX_ERROR_CHARS], new_status,
             _utc_now_iso(), item["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return new_status


def replay_queue(db_path, handlers, max_attempts=5):
    """Run every queued/retrying job once, in FIFO order.

    ``handlers`` maps kind -> callable(payload). On success the job is
    marked done. On exception the attempt is counted, the (truncated)
    error stored, and the job becomes 'failed' once attempts reach
    max_attempts — failed rows stay visible; nothing is deleted.

    Returns {"done": n_newly_done, "failed": n_newly_failed,
             "remaining": n_still_pending}.
    """
    init_offline_tables(db_path)
    summary = {"done": 0, "failed": 0, "remaining": 0}
    pending = [i for i in list_queue(db_path) if i["status"] in _PENDING]
    for item in pending:
        try:
            payload = json.loads(item["payload_json"])
        except Exception as exc:  # noqa: BLE001 — corrupt payload is fatal-ish
            new_status = _record_attempt(
                db_path, item, "corrupt payload_json: %s" % exc, max_attempts)
        else:
            handler = handlers.get(item["kind"])
            if handler is None:
                new_status = _record_attempt(
                    db_path, item,
                    "no handler registered for kind %r" % item["kind"],
                    max_attempts)
            else:
                try:
                    handler(payload)
                except Exception as exc:  # noqa: BLE001 — job failure, not a bug
                    new_status = _record_attempt(db_path, item, exc, max_attempts)
                else:
                    _mark_done(db_path, item["id"])
                    new_status = "done"
        if new_status == "done":
            summary["done"] += 1
        elif new_status == "failed":
            summary["failed"] += 1
    summary["remaining"] = len(list_queue_items_pending(db_path))
    return summary


def list_queue_items_pending(db_path):
    """Pending jobs (queued + retrying), FIFO."""
    init_offline_tables(db_path)
    conn = _connect(db_path)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, kind, payload_json, status, attempts, last_error,"
                " created_at, updated_at FROM offline_queue"
                " WHERE status IN ('queued', 'retrying') ORDER BY id ASC"
            ).fetchall()
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------- purge

def purge_done(db_path, older_than_days=30):
    """Delete done jobs whose updated_at is older than the cutoff.

    Failed jobs are NEVER deleted automatically — they stay visible for the
    user to inspect or requeue. Returns the number of rows deleted.
    """
    init_offline_tables(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM offline_queue"
            " WHERE status = 'done'"
            " AND updated_at < datetime('now', ?)",
            ("-%d days" % int(older_than_days),),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
