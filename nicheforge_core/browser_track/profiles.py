"""NicheForge Phase 3 — Profile Vault.

One persistent Chrome user-data-dir per (niche x service x account), so
cookies/logins stay isolated and the human-mimic engine can resume each
niche's browser session exactly where it left off.

Directory layout (PROFILES_ROOT)::

    <repo>/workspace/browser_profiles/<niche>/<service>-<sanitised-email>/

Secrets: this module never stores passwords. The account list comes from
the decrypted config dict under the ``browser_accounts`` key::

    {
      "browser_accounts": {
        "chatgpt": ["a@x.com", "b@y.com"],
        "claude": ["c@z.com"],
        "gemini": ["d@w.com"]
      }
    }

config.example.json shape (documented here, owned by another builder)::

    {
      "...existing provider keys...": "...",
      "browser_accounts": {
        "chatgpt": ["you1@example.com", "you2@example.com"],
        "claude": ["you@example.com"],
        "gemini": ["you@example.com"]
      }
    }
"""

import os
import re
import sqlite3
from datetime import datetime, timezone

# <repo>/workspace/browser_profiles/ — computed from this module's location,
# never hardcoded, so the repo can move.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_ROOT = os.path.join(_REPO_ROOT, "workspace", "browser_profiles")

PROFILE_STATUSES = {"active", "paused", "expired"}

# Services the vault knows how to isolate profiles for.
SERVICES = {"chatgpt", "claude", "gemini"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_profile_tables(db_path):
    """Create the browser_profiles and browser_events tables if missing."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS browser_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                niche TEXT NOT NULL,
                service TEXT NOT NULL,
                email TEXT NOT NULL,
                profile_dir TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_used TEXT,
                UNIQUE (niche, service, email)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS browser_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                niche TEXT NOT NULL,
                service TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT DEFAULT ''
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _sanitise_email(email):
    return re.sub(r"[^a-zA-Z0-9._-]", "_", email)


def profile_dir_for(niche, service, email):
    """Filesystem dir for one (niche, service, email) profile."""
    return os.path.join(PROFILES_ROOT, niche, "%s-%s" % (service, _sanitise_email(email)))


def _log_event(conn, niche, service, kind, detail=""):
    conn.execute(
        "INSERT INTO browser_events (ts, niche, service, kind, detail)"
        " VALUES (?, ?, ?, ?, ?)",
        (utc_now(), niche, service, kind, detail),
    )


def register_profile(db_path, niche, service, email):
    """mkdir -p the profile dir; INSERT idempotently (unique niche+service+email).

    Returns the row as a dict.
    """
    profile_dir = profile_dir_for(niche, service, email)
    os.makedirs(profile_dir, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO browser_profiles"
            " (niche, service, email, profile_dir, status, created_at)"
            " VALUES (?, ?, ?, ?, 'active', ?)",
            (niche, service, email, profile_dir, utc_now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM browser_profiles WHERE niche = ? AND service = ? AND email = ?",
            (niche, service, email),
        ).fetchone()
        if row is None:
            raise RuntimeError("register_profile: row missing after insert")
        result = dict(row)
        _log_event(conn, niche, service, "profile_registered", email)
        conn.commit()
        return result
    finally:
        conn.close()


def get_profile(db_path, niche, service, email=None):
    """First ACTIVE profile for (niche, service); email filter optional.

    Returns dict or None.
    """
    conn = _connect(db_path)
    try:
        if email is not None:
            row = conn.execute(
                "SELECT * FROM browser_profiles WHERE niche = ? AND service = ?"
                " AND email = ? AND status = 'active' ORDER BY id LIMIT 1",
                (niche, service, email),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM browser_profiles WHERE niche = ? AND service = ?"
                " AND status = 'active' ORDER BY id LIMIT 1",
                (niche, service),
            ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_status(db_path, niche, service, email, status):
    """Set a profile's status; must be one of active/paused/expired."""
    if status not in PROFILE_STATUSES:
        raise ValueError("status must be one of %s" % sorted(PROFILE_STATUSES))
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE browser_profiles SET status = ?"
            " WHERE niche = ? AND service = ? AND email = ?",
            (status, niche, service, email),
        )
        if cur.rowcount == 0:
            raise KeyError("no profile for %r/%r/%r" % (niche, service, email))
        _log_event(conn, niche, service, "status_%s" % status, email)
        conn.commit()
    finally:
        conn.close()


def list_profiles(db_path, niche=None, service=None):
    """All profiles, optionally filtered by niche and/or service."""
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM browser_profiles"
        params = []
        clauses = []
        if niche is not None:
            clauses.append("niche = ?")
            params.append(niche)
        if service is not None:
            clauses.append("service = ?")
            params.append(service)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY niche, service, id"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _touch_last_used(db_path, profile_id):
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE browser_profiles SET last_used = ? WHERE id = ?",
            (utc_now(), profile_id),
        )
        conn.commit()
    finally:
        conn.close()


def next_available_profile(db_path, niche, service, parked_checker):
    """Account Rotation Pool: first usable profile for (niche, service).

    ``parked_checker`` is a callable (service, email) -> bool, True when the
    account is parked by the sentinel layer. Iterates in registry order and
    skips paused, expired, or parked accounts. Updates last_used on the
    returned profile. Returns a dict or None when nothing is available.
    """
    candidates = [
        p for p in list_profiles(db_path, niche=niche, service=service)
        if p["status"] == "active"
    ]
    for profile in candidates:
        if parked_checker(profile["service"], profile["email"]):
            continue
        _touch_last_used(db_path, profile["id"])
        profile = get_profile(db_path, niche, service, email=profile["email"])
        if profile is not None:
            return profile
    return None


def sync_accounts_from_config(db_path, config, niche):
    """Register one profile per (niche x service x email) from a config dict.

    ``config`` is the DECRYPTED config (from providers.load_config); reads
    ``config["browser_accounts"]`` of the form
    {"chatgpt": ["a@x.com"], "claude": [...], "gemini": [...]}.
    Idempotent: already-registered accounts are skipped. Returns the list of
    row dicts for every account in the config (new or pre-existing).
    """
    accounts = (config or {}).get("browser_accounts") or {}
    registered = []
    for service, emails in accounts.items():
        for email in emails or []:
            registered.append(register_profile(db_path, niche, service, email))
    return registered


def launch_kwargs(niche, headless=False):
    """Keyword args for launching a Playwright persistent context.

    Playwright is imported lazily inside ``launch_browser`` so the vault (and
    its tests) work without playwright installed.
    """
    return {
        "user_data_dir": os.path.join(PROFILES_ROOT, niche),
        "headless": bool(headless),
        "viewport": {"width": 1366, "height": 900},
        "locale": "en-GB",
    }


def launch_browser(niche, service, email, headless=False):
    """Lazy-import playwright and launch the niche's persistent context.

    Helper only; not exercised by the vault tests. Raises ImportError with a
    clear message when playwright is not installed.
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: E402
    except ImportError as exc:
        raise ImportError(
            "playwright is not installed; install it to launch the browser"
        ) from exc
    kwargs = launch_kwargs(niche, headless=headless)
    profile_dir = profile_dir_for(niche, service, email)
    os.makedirs(profile_dir, exist_ok=True)
    pw = sync_playwright().start()
    return pw.chromium.launch_persistent_context(
        profile_dir,
        headless=kwargs["headless"],
        viewport=kwargs["viewport"],
        locale=kwargs["locale"],
    )
