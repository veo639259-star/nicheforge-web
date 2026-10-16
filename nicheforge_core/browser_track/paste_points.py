"""NicheForge Phase 3 — Paste-Safe Handoff points.

KNOWN LIMITATION: browser automation cannot paste text into some editors
(for example Google Flow's prompt box — a ProseMirror contenteditable div
with no accessibility ref, frozen clipboard, no JS-execution escape hatch).
For those steps the automation stops and asks a human to paste instead.

CONTRACT between automation and the Flask UI:
  1. The automation calls next_pending(). If it returns None, no paste is
     needed and the run continues unattended.
  2. If a paste point is returned, the automation PAUSES at that point and
     the UI banner polls pending_count() / list_pending() and shows:
         "Paste karo: <label>"  + the URL + the context hint.
  3. The human opens the URL in their real browser, pastes the prompt
     (copied from the context/prompt text), then clicks Done or Skip in
     the UI.
  4. Done -> complete(id) -> automation resumes the paused step.
     Skip  -> skip(id)     -> automation treats the step as not done and
     moves on (records the skip so nothing is silently retried forever).
"""

import sqlite3
from datetime import datetime, timezone

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
VALID_STATUSES = {STATUS_PENDING, STATUS_DONE, STATUS_SKIPPED}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_paste_tables(db_path):
    """Create the paste_points table if it doesn't exist."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paste_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                url TEXT NOT NULL,
                context TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def request(db_path, label, url, context=""):
    """Register a new paste point. Returns its id."""
    init_paste_tables(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO paste_points (label, url, context, status,"
            " created_at) VALUES (?, ?, ?, 'pending', ?)",
            (label, url, context, _utc_now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _row_to_dict(row):
    return dict(row) if row is not None else None


def next_pending(db_path):
    """Oldest still-pending paste point, or None."""
    init_paste_tables(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM paste_points WHERE status = 'pending'"
            " ORDER BY id ASC LIMIT 1"
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def complete(db_path, paste_id):
    """Mark a paste point done — the human pasted and clicked Done."""
    _resolve(db_path, paste_id, STATUS_DONE)


def skip(db_path, paste_id):
    """Mark a paste point skipped — automation moves on without it."""
    _resolve(db_path, paste_id, STATUS_SKIPPED)


def _resolve(db_path, paste_id, status):
    init_paste_tables(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE paste_points SET status = ?, resolved_at = ?"
            " WHERE id = ?",
            (status, _utc_now(), paste_id),
        )
        conn.commit()
    finally:
        conn.close()


def pending_count(db_path):
    """How many paste points are still waiting on the human."""
    init_paste_tables(db_path)
    conn = _connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM paste_points WHERE status = 'pending'"
        ).fetchone()["c"]
    finally:
        conn.close()


def list_pending(db_path):
    """All pending paste points, oldest first."""
    init_paste_tables(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM paste_points WHERE status = 'pending'"
            " ORDER BY id ASC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
