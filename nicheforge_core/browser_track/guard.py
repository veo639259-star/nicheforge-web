"""NicheForge Phase 3 — Captcha & Block Guard.

Safety-critical: NEVER auto-retry a captcha or block. On a hit this module
PAUSES the profile (so the runner never touches it again on its own),
writes a browser_events entry, and returns a critical alert for the human
to see. The ONLY way back is an explicit human_resume() call — there is no
automatic resume, no backoff retry, nothing that re-touches a flagged
account without a person saying so.

Profile storage/schema is owned by profiles.py; we call its
init_profile_tables() defensively before every write.
"""

import sqlite3

try:  # package context: from browser_track import guard
    from browser_track.profiles import (
        _connect,
        init_profile_tables,
        profile_dir_for,
        utc_now,
    )
except ImportError:  # direct module context
    from profiles import (
        _connect,
        init_profile_tables,
        profile_dir_for,
        utc_now,
    )


# Case-insensitive substring signals in page text.
BLOCK_SIGNALS = [
    "captcha",
    "verify you are human",
    "unusual activity",
    "suspicious activity",
    "account suspended",
    "access denied",
    "robot check",
]


def scan(text):
    """Return the list of BLOCK_SIGNALS found in text (case-insensitive).
    Empty list when the page looks clean."""
    sample = (text or "").lower()
    return [signal for signal in BLOCK_SIGNALS if signal in sample]


class BlockGuard:
    def __init__(self, db_path):
        self.db_path = db_path
        init_profile_tables(db_path)

    def trip(self, niche, service, email, signal):
        """A block/captcha was detected: pause the profile, log the event,
        and return a critical alert dict. NEVER retries — that is the whole
        point.

        The profile row may not exist yet (defensive): it is created already
        paused so no runner can pick it up.
        """
        init_profile_tables(self.db_path)
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO browser_profiles"
                " (niche, service, email, profile_dir, status, created_at)"
                " VALUES (?, ?, ?, ?, 'paused', ?)",
                (niche, service, email, profile_dir_for(niche, service, email),
                 utc_now()),
            )
            conn.execute(
                "UPDATE browser_profiles SET status = 'paused'"
                " WHERE niche = ? AND service = ? AND email = ?",
                (niche, service, email),
            )
            conn.execute(
                "INSERT INTO browser_events (ts, niche, service, kind, detail)"
                " VALUES (?, ?, ?, 'block', ?)",
                (utc_now(), niche, service, "%s: %s" % (email, signal)),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "level": "critical",
            "message": (
                "BLOCK on %s/%s (%s): '%s'. Profile paused — "
                "human must review and call human_resume(); no auto-retry."
            ) % (niche, service, email, signal),
        }

    def human_resume(self, niche, service, email):
        """The ONLY way back: an explicit human action reactivates the
        profile and logs kind='resume'. Returns True on success."""
        init_profile_tables(self.db_path)
        conn = _connect(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE browser_profiles SET status = 'active'"
                " WHERE niche = ? AND service = ? AND email = ?",
                (niche, service, email),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "INSERT INTO browser_events (ts, niche, service, kind, detail)"
                " VALUES (?, ?, ?, 'resume', ?)",
                (utc_now(), niche, service, email),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def recent_events(self, niche=None, limit=50):
        """Newest-first browser_events, optionally filtered by niche."""
        init_profile_tables(self.db_path)
        conn = _connect(self.db_path)
        try:
            sql = "SELECT ts, niche, service, kind, detail FROM browser_events"
            params = []
            if niche is not None:
                sql += " WHERE niche = ?"
                params.append(niche)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
