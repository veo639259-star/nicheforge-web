"""NicheForge Phase 3 — Rate-Limit Sentinel.

Safety-critical: NEVER hammer a rate limit. After every browser action the
runner scans page text / HTTP status codes with this module. On a hit, the
account is PARKED (never retried blindly) and the rotation pool moves on to
the next unparked account.

A parked account cools down for ``cooldown_secs`` (default 1 hour). Expired
parks are auto-removed on read so they never block rotation forever.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

DEFAULT_COOLDOWN_SECS = 3600  # 1 hour

# Case-insensitive substring signals in page text.
LIMIT_SIGNALS = [
    "try again later",
    "limit reached",
    "rate limit",
    "too many requests",
    "you've reached",
    "come back later",
    "usage limit",
    "quota exceeded",
]

# Matches an HTTP 429 surfaced as text (e.g. an error page body).
HTTP_429_SIGNAL = "HTTP 429"


def check_text(text):
    """Scan page text for rate-limit signals (case-insensitive).

    Returns {"signal": <matched>, "cooldown_secs": 3600} on the FIRST match
    in LIMIT_SIGNALS order, or None when clean. "429" in text counts as
    HTTP 429.
    """
    sample = (text or "").lower()
    for signal in LIMIT_SIGNALS:
        if signal in sample:
            return {"signal": signal, "cooldown_secs": DEFAULT_COOLDOWN_SECS}
    if "429" in sample:
        return {"signal": HTTP_429_SIGNAL, "cooldown_secs": DEFAULT_COOLDOWN_SECS}
    return None


def check_status_code(code):
    """Dict on HTTP 429, None otherwise. Accepts int or str."""
    if str(code).strip() == "429":
        return {"signal": HTTP_429_SIGNAL, "cooldown_secs": DEFAULT_COOLDOWN_SECS}
    return None


# ---------------------------------------------------------------- tracker

def _utc_now():
    return datetime.now(timezone.utc)


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


class RateLimitTracker:
    """DB-backed account parking. All timestamps are UTC ISO."""

    def __init__(self, db_path):
        self.db_path = db_path
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_parks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service TEXT NOT NULL,
                    email TEXT NOT NULL,
                    parked_until_utc TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def park(self, service, email, reason, cooldown_secs=DEFAULT_COOLDOWN_SECS):
        """Park (service, email) for cooldown_secs. Returns parked_until_utc."""
        until = _utc_now() + timedelta(seconds=cooldown_secs)
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO browser_parks"
                " (service, email, parked_until_utc, reason, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    service,
                    email,
                    until.isoformat(timespec="seconds"),
                    reason or "",
                    _utc_now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return until.isoformat(timespec="seconds")

    def _expire(self, conn, service=None, email=None):
        """Delete past parks (optionally scoped). Returns rows removed."""
        now = _utc_now().isoformat(timespec="seconds")
        sql = "DELETE FROM browser_parks WHERE parked_until_utc <= ?"
        params = [now]
        if service is not None:
            sql += " AND service = ?"
            params.append(service)
        if email is not None:
            sql += " AND email = ?"
            params.append(email)
        cur = conn.execute(sql, params)
        return cur.rowcount

    def is_parked(self, service, email):
        """True when (service, email) has an unexpired park. Past parks are
        auto-expired (deleted) first."""
        conn = _connect(self.db_path)
        try:
            self._expire(conn, service, email)
            conn.commit()
            row = conn.execute(
                "SELECT MAX(parked_until_utc) AS u FROM browser_parks"
                " WHERE service = ? AND email = ?",
                (service, email),
            ).fetchone()
            return row["u"] is not None
        finally:
            conn.close()

    def next_available(self, service, emails):
        """First email in order that is NOT parked; None when all are parked."""
        for email in emails or []:
            if not self.is_parked(service, email):
                return email
        return None

    def list_parks(self):
        """All currently active parks (expired ones removed first), as dicts
        ordered by parked_until_utc."""
        conn = _connect(self.db_path)
        try:
            self._expire(conn)
            conn.commit()
            rows = conn.execute(
                "SELECT id, service, email, parked_until_utc, reason, created_at"
                " FROM browser_parks ORDER BY parked_until_utc"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
