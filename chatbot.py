"""NicheForge Web — built-in AI assistant.

Sidebar chat panel powered by the Gemini key ladder (with full provider
failover). It can:
  - answer questions about batches / niches / schedules (live DB context)
  - help write captions
  - suggest fresh ideas on demand
  - explain errors in simple words (reads nf_errors + tracebacks)

Conversation history is kept per Flask session (capped).
"""

import datetime
import os
import sqlite3

NICHES = ["wicketverse", "pakwire", "maloomat", "sukhan", "paheli",
          "memeistan", "lafz", "deen", "parhai", "aangan", "angrezi",
          "techsathi", "imtihan", "marvelverse"]

MAX_HISTORY = 20  # messages (10 turns)


def _db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def build_context(db_path):
    """Compact live snapshot of the workspace for the system prompt."""
    lines = []
    try:
        conn = _db(db_path)
        try:
            for niche in NICHES:
                row = conn.execute(
                    "SELECT"
                    " SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,"
                    " SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved,"
                    " MAX(created_at) AS last_batch"
                    " FROM ideas WHERE niche = ?",
                    (niche,),
                ).fetchone()
                if row and (row["pending"] or row["approved"]):
                    lines.append(
                        "%s: %d pending, %d approved (last batch %s)"
                        % (niche, row["pending"] or 0, row["approved"] or 0,
                           (row["last_batch"] or "?")[:16]))
            today = datetime.datetime.now(
                datetime.timezone.utc).strftime("%Y-%m-%d")
            sched = conn.execute(
                "SELECT COUNT(*) AS c FROM scheduled_posts"
                " WHERE substr(slot_utc,1,10) = ?",
                (today,)).fetchone()
            lines.append("scheduled today (UTC date): %d" % (sched["c"] if sched else 0))
            try:
                errs = conn.execute(
                    "SELECT niche, stage, error_type, message FROM nf_errors"
                    " WHERE status = 'open' ORDER BY id DESC LIMIT 5").fetchall()
                for e in errs:
                    lines.append("OPEN ERROR [%s/%s] %s: %s"
                                 % (e["niche"], e["stage"], e["error_type"],
                                    (e["message"] or "")[:120]))
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()
    except Exception:
        lines.append("(workspace stats unavailable)")
    return "\n".join(lines) if lines else "(no batches yet)"


SYSTEM_TMPL = """You are Forge, the built-in assistant of NicheForge, Hmb's
content-automation app for 14 Facebook niches. Be concise, practical, and
friendly. Reply in the user's language: Roman Urdu if they write Roman Urdu,
English if they write English. Never use Devanagari script.

You can: explain batches and niche status, draft captions (Roman Urdu + English
mix, hook first, CTA last), suggest fresh post ideas, and explain errors in
simple words with a fix suggestion.

Live workspace snapshot (use it when asked about status):
%s

Rules: no fake claims, no invented numbers on images, Deen niche = zero Arabic,
Urdu text on images is overlaid by the app (never AI-generated)."""


def ask(db_path, ladder, history, user_text):
    """One chat turn. Returns (reply_text, provider, model)."""
    if ladder is None:
        return ("Abhi API keys set nahi hain — /admin/keys par Gemini key "
                "add karein, phir main jawab de sakun ga.", "none", "none")
    context = build_context(db_path)
    system = SYSTEM_TMPL % context
    messages = []
    for m in (history or [])[-MAX_HISTORY:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"],
                             "content": m["content"][:2000]})
    messages.append({"role": "user", "content": user_text[:2000]})
    try:
        res = ladder.chat(messages, system=system, max_tokens=800)
        return res["text"], res.get("provider", "?"), res.get("model", "?")
    except Exception as exc:  # noqa: BLE001
        return ("Maazrat — AI providers se jawab nahi aa saka: %s. Keys /admin/keys"
                " par check karein." % str(exc)[:200], "error", "error")


def explain_error(db_path, error_id):
    """Simple-words explanation of one logged error (for the error panel)."""
    from error_report import read_traceback  # local import, no cycle
    tb = read_traceback(error_id)[:3000]
    if not tb:
        return "Is error ka traceback nahi mila."
    return ("Is error ko simple lafzon mein samjhna ho to chat mein likhein:\n"
            "'error #%s samjhao' — main poora traceback parh kar asaan "
            "hal bata dun ga." % error_id)
