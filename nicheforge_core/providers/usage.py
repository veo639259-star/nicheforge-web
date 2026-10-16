"""SQLite usage logging for the Key Ladder.

Schema (created by the db module owned by another agent -- NEVER create
the table here, only INSERT/SELECT):

    usage(id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          tokens_in INTEGER DEFAULT 0,
          tokens_out INTEGER DEFAULT 0,
          ok INTEGER DEFAULT 1)
"""

import sqlite3
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_usage(db_path: str, provider: str, model: str,
              tokens_in: int = 0, tokens_out: int = 0, ok: int = 1) -> None:
    """Record one attempt row. ``ok`` is 1 on success, 0 on failure."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO usage (ts, provider, model, tokens_in, tokens_out, ok)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_utc_now_iso(), provider, model, int(tokens_in), int(tokens_out), int(bool(ok))),
        )
        conn.commit()
    finally:
        conn.close()


def get_usage(db_path: str, days: int = 30) -> list:
    """Return usage rows from the last ``days`` days as a list of dicts,
    newest first."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT id, ts, provider, model, tokens_in, tokens_out, ok"
            " FROM usage"
            " WHERE ts >= datetime('now', ?)"
            " ORDER BY ts DESC",
            (f"-{int(days)} days",),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
