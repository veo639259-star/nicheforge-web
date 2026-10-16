"""NicheForge Phase 3 — Session Health Monitor.

Cheap heuristics for "am I still logged in?" plus expiry bookkeeping.
Called by the sentinel layer after each browser run; it never guesses —
``check_login`` works on a short sample of page text and looks for the
service's logged-out markers.

Heuristic rules (kept deliberately simple so false negatives are rare):
  - Normalise: lowercase, collapse whitespace.
  - If ANY of the service's logged-out indicators appears in the sample,
    the session is treated as LOGGED OUT -> returns False.
  - Otherwise the session is treated as LOGGED IN -> returns True.

Indicators are case-insensitive substring matches against the rendered page
text (headings, buttons, links). A genuinely logged-in page rarely shows the
bare words "log in" / "sign in" / "sign up" in its visible text sample.
"""

import re
import sqlite3

try:  # package context: from browser_track import sessions
    from browser_track.profiles import _connect, set_status, utc_now
except ImportError:  # direct module context
    from profiles import _connect, set_status, utc_now


# Logged-out indicators per service: if any of these appear in a short page
# sample, the session is considered LOGGED OUT.
LOGIN_SIGNALS = {
    "chatgpt": ["log in", "sign up"],
    "claude": ["log in"],
    "gemini": ["sign in"],
}


def check_login(page_text, service):
    """True when the session looks LOGGED IN, False when logged out.

    ``page_text`` is a short sample of the rendered page text (e.g. the
    landing page after navigation). Returns True when none of the service's
    logged-out indicators are present.
    """
    indicators = LOGIN_SIGNALS.get(service, ["log in"])
    sample = re.sub(r"\s+", " ", (page_text or "")).strip().lower()
    for indicator in indicators:
        if indicator.lower() in sample:
            return False
    return True


def mark_expired(db_path, niche, service, email):
    """Flip a profile to expired and log a browser_events entry."""
    conn = _connect(db_path)
    try:
        set_status(db_path, niche, service, email, "expired")
        conn.execute(
            "INSERT INTO browser_events (ts, niche, service, kind, detail)"
            " VALUES (?, ?, ?, ?, ?)",
            (utc_now(), niche, service, "session_expired", email),
        )
        conn.commit()
    finally:
        conn.close()


def relogin_url(service):
    """Manual relogin URL for a service (shown to the user on expiry)."""
    return {
        "chatgpt": "https://chatgpt.com/auth/login",
        "claude": "https://claude.ai/login",
        "gemini": "https://gemini.google.com",
    }[service]


def login_status_report(db_path):
    """[{niche, service, email, status}] for the UI dashboard."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT niche, service, email, status FROM browser_profiles"
            " ORDER BY niche, service, email"
        ).fetchall()
        return [
            {
                "niche": r["niche"],
                "service": r["service"],
                "email": r["email"],
                "status": r["status"],
            }
            for r in rows
        ]
    finally:
        conn.close()
