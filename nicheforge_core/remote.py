"""NicheForge WhatsApp Remote — command protocol layer (Phase 5, v1).

v1 scope: COMMANDS ONLY. There is no real WhatsApp connection in this
version. Messages move through two local SQLite tables:

  wa_inbox      — inbound messages staged for processing.
  wa_outbox     — replies staged for sending.
  remote_pauses — per-niche pause flags toggled by PAUSE/RESUME.

FUTURE WIRING (webhook slot — for the Flask integrator):
  1. Add a Flask route ``POST /api/remote/webhook`` accepting JSON
     ``{"from": "<sender>", "body": "<text>"}``. That route does ONE
     thing: ``remote.webhook_ingest(db_path, sender, body)`` — insert the
     message into wa_inbox and return 200. Keep command logic OUT of the
     route; the helper below exists so the integrator wires it in one line.
  2. A worker (cron or a long-running loop) calls
     ``remote.process_inbox(db_path, remote.default_handlers())`` which
     parses each unprocessed message, runs the matching handler, writes
     the reply into wa_outbox, and marks the message processed.
  3. A separate sender drains ``remote.get_outbox_pending(db_path)``
     through the real WhatsApp channel (future work) and calls
     ``remote.mark_outbox_sent(db_path, outbox_id)`` for every reply the
     channel actually delivers.

Protocol: commands are case-insensitive. The first word of the message is
the command; everything after it is the argument list.

Commands: STATUS | PAUSE <niche> | RESUME <niche> | APPROVE <idea_id> |
          REJECT <idea_id> | QUEUE | HELP
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import db  # noqa: E402 — Phase-1 idea bank (add_idea / list_ideas / set_status)


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_remote_tables(db_path):
    """Create wa_inbox, wa_outbox and remote_pauses if they don't exist."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                received_at TEXT NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS remote_pauses (
                niche TEXT PRIMARY KEY,
                paused INTEGER NOT NULL DEFAULT 0,
                at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- parsing

def parse_command(body):
    """Parse a message into (COMMAND, args). Command is upper-cased.

    Empty/blank input parses to ("HELP", []) so the sender gets the help
    text. Unknown commands keep their token — process_inbox falls back to
    the HELP handler when no handler is registered for them.
    """
    if not body or not str(body).strip():
        return ("HELP", [])
    parts = str(body).strip().split()
    return (parts[0].upper(), parts[1:])


# ---------------------------------------------------------------- ingest

def webhook_ingest(db_path, sender, body):
    """Insert one inbound message into wa_inbox; returns the row id.

    This is the single call the future ``POST /api/remote/webhook`` route
    makes: ``webhook_ingest(db_path, payload["from"], payload["body"])``.
    """
    init_remote_tables(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO wa_inbox (sender, body, received_at, processed)"
            " VALUES (?, ?, ?, 0)",
            (sender or "", body or "", _utc_now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _mark_processed(db_path, inbox_id):
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE wa_inbox SET processed = 1 WHERE id = ?", (inbox_id,))
        conn.commit()
    finally:
        conn.close()


def _enqueue_outbox(db_path, recipient, body):
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO wa_outbox (recipient, body, created_at, sent)"
            " VALUES (?, ?, ?, 0)",
            (recipient or "", body or "", _utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_outbox_pending(db_path):
    """Replies staged but not yet sent, oldest first (future sender drains)."""
    init_remote_tables(db_path)
    conn = _connect(db_path)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, recipient, body, created_at, sent"
                " FROM wa_outbox WHERE sent = 0 ORDER BY id ASC"
            ).fetchall()
        ]
    finally:
        conn.close()


def mark_outbox_sent(db_path, outbox_id):
    """Mark one staged reply as delivered. Returns True if a row changed."""
    init_remote_tables(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE wa_outbox SET sent = 1 WHERE id = ?", (int(outbox_id),)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------- pauses

def is_niche_paused(db_path, niche):
    """True when the niche currently has a PAUSE flag set."""
    init_remote_tables(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT paused FROM remote_pauses WHERE niche = ?", (niche,)
        ).fetchone()
        return row is not None and int(row["paused"]) == 1
    finally:
        conn.close()


def _set_pause(db_path, niche, paused):
    init_remote_tables(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO remote_pauses (niche, paused, at) VALUES (?, ?, ?)"
            " ON CONFLICT(niche) DO UPDATE SET paused = excluded.paused,"
            " at = excluded.at",
            (niche, 1 if paused else 0, _utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- handlers

def _h_status(db_path, args):
    pending = db.list_ideas(db_path, status="pending")
    conn = _connect(db_path)
    try:
        paused_rows = conn.execute(
            "SELECT niche FROM remote_pauses WHERE paused = 1 ORDER BY niche"
        ).fetchall()
        unsent = conn.execute(
            "SELECT COUNT(*) AS n FROM wa_outbox WHERE sent = 0"
        ).fetchone()["n"]
    finally:
        conn.close()
    try:
        import credits  # optional: Phase-5 Credit Guard lives beside this module

        ai_ok = credits.is_ai_allowed(db_path)
        ai_line = "yes" if ai_ok else "NO — Credit Guard paused AI"
    except Exception:
        ai_line = "unknown (credits module not loaded)"
    lines = [
        "NicheForge status",
        "Pending approvals: %d" % len(pending),
        "Paused niches: %s" % (
            ", ".join(r["niche"] for r in paused_rows) or "none"
        ),
        "Unsent replies: %d" % unsent,
        "AI allowed: %s" % ai_line,
    ]
    return "\n".join(lines)


def _h_queue(db_path, args):
    pending = db.list_ideas(db_path, status="pending")[:10]
    total = len(db.list_ideas(db_path, status="pending"))
    if not pending:
        return "Approval queue is empty. Nothing waiting."
    lines = ["Pending approvals (%d):" % total]
    for idea in pending:
        title = (idea.get("title") or "").strip()
        if len(title) > 60:
            title = title[:57] + "..."
        lines.append("#%d [%s] %s" % (idea["id"], idea.get("niche", ""), title))
    lines.append("Reply APPROVE <id> or REJECT <id>.")
    return "\n".join(lines)


def _h_help(db_path, args):
    return (
        "NicheForge remote commands:\n"
        "STATUS — queue and health summary\n"
        "QUEUE — list ideas waiting for approval\n"
        "APPROVE <idea_id> — approve an idea\n"
        "REJECT <idea_id> — reject an idea\n"
        "PAUSE <niche> — pause posting for a niche\n"
        "RESUME <niche> — resume posting for a niche\n"
        "HELP — this text"
    )


def _h_pause(db_path, args):
    if not args:
        return "Usage: PAUSE <niche>. Valid niches: " + ", ".join(db.NICHE_IDS)
    niche = args[0].lower()
    if niche not in db.NICHE_IDS:
        return (
            "Unknown niche '%s'. Valid niches: %s"
            % (args[0], ", ".join(db.NICHE_IDS))
        )
    _set_pause(db_path, niche, True)
    return "Paused posting for niche '%s'. Send RESUME %s to unpause." % (
        niche, args[0].upper())


def _h_resume(db_path, args):
    if not args:
        return "Usage: RESUME <niche>. Valid niches: " + ", ".join(db.NICHE_IDS)
    niche = args[0].lower()
    if niche not in db.NICHE_IDS:
        return (
            "Unknown niche '%s'. Valid niches: %s"
            % (args[0], ", ".join(db.NICHE_IDS))
        )
    _set_pause(db_path, niche, False)
    return "Resumed posting for niche '%s'." % niche


def _get_idea(db_path, idea_id):
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, niche, title, status FROM ideas WHERE id = ?",
            (idea_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _h_approve(db_path, args):
    if not args or not args[0].isdigit():
        return "Usage: APPROVE <idea_id> — e.g. APPROVE 12. Send QUEUE to see ids."
    idea_id = int(args[0])
    idea = _get_idea(db_path, idea_id)
    if idea is None:
        return "No idea with id %d. Send QUEUE to see pending ids." % idea_id
    db.set_status(db_path, idea_id, "approved")
    title = (idea.get("title") or "").strip()
    if len(title) > 60:
        title = title[:57] + "..."
    return "Approved idea #%d [%s]: %s" % (idea_id, idea.get("niche", ""), title)


def _h_reject(db_path, args):
    if not args or not args[0].isdigit():
        return "Usage: REJECT <idea_id> — e.g. REJECT 12. Send QUEUE to see ids."
    idea_id = int(args[0])
    idea = _get_idea(db_path, idea_id)
    if idea is None:
        return "No idea with id %d. Send QUEUE to see pending ids." % idea_id
    db.set_status(db_path, idea_id, "rejected")
    return "Rejected idea #%d. It stays in the log but will not post." % idea_id


def default_handlers():
    """Safe built-in command map: command name -> callable(db_path, args).

    Every callable returns the reply string written to wa_outbox. Add custom
    commands by copying this dict and registering more entries before
    passing it to process_inbox.
    """
    return {
        "STATUS": _h_status,
        "QUEUE": _h_queue,
        "HELP": _h_help,
        "PAUSE": _h_pause,
        "RESUME": _h_resume,
        "APPROVE": _h_approve,
        "REJECT": _h_reject,
    }


# ---------------------------------------------------------------- process

def process_inbox(db_path, handlers):
    """Process every unprocessed wa_inbox row, oldest first.

    Parses the message, calls the matching handler (falling back to HELP
    for unknown commands), writes the handler's reply into wa_outbox for
    the original sender, and marks the row processed. A handler exception
    never stalls the loop — the error becomes the reply.

    Returns the number of messages processed.
    """
    init_remote_tables(db_path)
    conn = _connect(db_path)
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id, sender, body FROM wa_inbox"
                " WHERE processed = 0 ORDER BY id ASC"
            ).fetchall()
        ]
    finally:
        conn.close()
    processed = 0
    for row in rows:
        cmd, args = parse_command(row["body"])
        handler = handlers.get(cmd) or handlers.get("HELP")
        try:
            reply = handler(db_path, args) if handler else ""
        except Exception as exc:  # noqa: BLE001 — poison message safety
            reply = "Error processing '%s': %s" % (cmd, exc)
        _enqueue_outbox(db_path, row["sender"], reply or "")
        _mark_processed(db_path, row["id"])
        processed += 1
    return processed
