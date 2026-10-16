"""NicheForge Web — AI browser apps workspace.

Three tabs: Google Flow, ChatGPT, Gemini. Each tab manages a persistent
Chrome profile tied to Hmb's signed-in accounts (same per-account profile
pattern as the local NicheForge browser track).

What this module does on a cloud host (Railway/Render):
  * keeps a service registry (status per service: signed_in / needs_login /
    rate_limited + reset time) in the DB
  * surfaces rate-limit parks from the core sentinel (browser_parks)
  * lists image-generation jobs routed to each browser session, with a
    copy-prompt helper and an upload slot for the finished image
  * documents the Flow paste limitation honestly: Flow's prompt box cannot be
    pasted into by automation, so the helper copies the prompt and Hmb pastes
    it manually (one paste), then generation continues.

What it does NOT do: it never claims a login it cannot verify, and never
fakes a generated image. On Hmb's own PC the same page can drive the real
Chrome profiles via the core browser_track modules.
"""

import datetime
import os
import sqlite3

SERVICES = [
    {"id": "flow", "name": "Google Flow", "url": "https://flow.google.com/",
     "desc": "Text-to-image / AI filmmaking. 4 versions per prompt."},
    {"id": "chatgpt", "name": "ChatGPT", "url": "https://chatgpt.com/",
     "desc": "Images, captions, scripts. fakharcgg@gmail.com"},
    {"id": "gemini", "name": "Gemini", "url": "https://gemini.google.com/",
     "desc": "Images + video prompts. hmuhammadbilal2016@gmail.com"},
]

SERVICE_IDS = [s["id"] for s in SERVICES]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def init_browser_tables(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nf_browser_services (
                service TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'needs_login',
                reset_at TEXT DEFAULT '',
                profile_name TEXT DEFAULT '',
                note TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        for sid in SERVICE_IDS:
            conn.execute(
                "INSERT OR IGNORE INTO nf_browser_services"
                " (service, status, updated_at) VALUES (?, 'needs_login', ?)",
                (sid, utc_now()))
        conn.commit()
    finally:
        conn.close()


def get_services(db_path):
    """Service registry merged with live rate-limit parks from sentinel."""
    init_browser_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = {r["service"]: dict(r) for r in
                conn.execute("SELECT * FROM nf_browser_services").fetchall()}
        # Overlay sentinel parks (rate limits) when present.
        parks = {}
        try:
            for p in conn.execute(
                    "SELECT service, reason FROM browser_parks").fetchall():
                parks[p["service"]] = p["reason"]
        except sqlite3.OperationalError:
            pass
        out = []
        for s in SERVICES:
            reg = rows.get(s["id"], {})
            status = reg.get("status", "needs_login")
            if s["id"] in parks and status != "rate_limited":
                status = "rate_limited"
            out.append({
                "id": s["id"],
                "name": s["name"],
                "url": s["url"],
                "desc": s["desc"],
                "status": status,
                "reset_at": reg.get("reset_at", ""),
                "profile_name": reg.get("profile_name", "") or
                ("nf-%s" % s["id"]),
                "note": parks.get(s["id"], reg.get("note", "")),
                "updated_at": reg.get("updated_at", ""),
            })
        return out
    finally:
        conn.close()


def set_service_status(db_path, service, status, reset_at="", note="",
                       profile_name=""):
    if service not in SERVICE_IDS:
        raise ValueError("unknown service")
    if status not in ("signed_in", "needs_login", "rate_limited"):
        raise ValueError("bad status")
    init_browser_tables(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE nf_browser_services SET status=?, reset_at=?, note=?,"
            " profile_name=?, updated_at=? WHERE service = ?",
            (status, reset_at, note,
             profile_name or ("nf-%s" % service), utc_now(), service))
        conn.commit()
    finally:
        conn.close()


def pending_jobs_for(db_path, service):
    """Image jobs routed to this browser session, still queued."""
    import imagegen as imagegen_mod
    jobs = imagegen_mod.list_jobs(db_path, limit=100)
    return [j for j in jobs
            if j["provider"] == service and j["status"] in ("queued",)]


STATUS_LABEL = {
    "signed_in": "Signed in",
    "needs_login": "Needs login",
    "rate_limited": "Rate-limited",
}
