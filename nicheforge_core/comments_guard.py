"""NicheForge comment guard (Phase 5).

Approval-gated comment moderation for Facebook Page posts:

  fetch_comments()  — best-effort Graph API read of a post's comments.
                      Never raises on network issues: returns [] and logs a
                      warning instead.
  classify_comment() — spam | abuse | genuine via a neutral blocklist.
  suggest_reply()   — drafts a reply (via the AI key ladder with the niche
                      DNA system prompt, or a neutral template when no
                      ladder is available).
  queue_reply()     — puts a drafted reply in the approval queue.
  approve_reply() / reject_reply() — human decision.
  mark_posted()     — marks a reply as posted AFTER it was posted manually.

NOTHING in this module posts to Facebook. Replies only ever enter the
approval queue; posting stays a manual, human-approved step.
"""
import json
import os
import sys

from db import _connect, utc_now

GRAPH_API_VERSION = "v21.0"

VALID_VERDICTS = {"spam", "abuse", "genuine"}
VALID_REPLY_STATUSES = {"pending", "approved", "rejected", "posted"}

# Neutral pattern blocklist — category names only, no profanity anywhere.
SPAM_PATTERNS = [
    "crypto", "bitcoin", "forex", "binary option", "investment",
    "double your money", "earn from home", "work from home",
    "dm for promo", "dm me", "telegram", "whatsapp me",
    "click the link", "free followers", "buy followers",
    "make money fast", "get rich", "limited offer", "act now",
]

ABUSE_PATTERNS = [
    # Mild insult categories; kept clean — no slurs, no profanity.
    "idiot", "stupid", "dumb", "loser", "shut up",
    "hate you", "kill yourself", "worthless", "moron",
]

NEUTRAL_REPLY = "Thanks for your comment! We appreciate your feedback."


def init_comment_tables(db_path):
    """Create the comment_replies table if it doesn't exist (idempotent)."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comment_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                niche TEXT NOT NULL,
                post_id TEXT NOT NULL DEFAULT '',
                comment_id TEXT NOT NULL DEFAULT '',
                author TEXT DEFAULT '',
                text TEXT DEFAULT '',
                verdict TEXT NOT NULL DEFAULT 'genuine',
                suggested_reply TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def fetch_comments(page_id, page_token, post_id, limit=50):
    """Read a post's comments via the Graph API (best effort).

    Returns a list of comment dicts. On ANY failure (missing requests,
    network error, bad response) logs a warning to stderr and returns [] —
    it never raises.
    """
    try:
        import requests
    except ImportError:
        print("warning: requests is not installed; cannot fetch comments",
              file=sys.stderr)
        return []
    url = "https://graph.facebook.com/{}/{}/comments".format(
        GRAPH_API_VERSION, post_id)
    params = {
        "fields": "id,message,from",
        "limit": limit,
        "access_token": page_token,
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        data = resp.json()
        return data.get("data") or []
    except Exception as exc:
        print("warning: fetch_comments failed: {}".format(exc),
              file=sys.stderr)
        return []


def classify_comment(text):
    """Classify comment text as 'spam', 'abuse' or 'genuine'."""
    t = (text or "").lower()
    if any(p in t for p in SPAM_PATTERNS):
        return "spam"
    if any(p in t for p in ABUSE_PATTERNS):
        return "abuse"
    return "genuine"


def _load_dna(niche):
    """Load the niche DNA JSON shipped with NicheForge (best effort)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "dna", "{}.json".format(niche))
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def suggest_reply(niche, comment_text, ladder=None):
    """Draft a reply to a comment.

    With a ladder (providers.ladder.KeyLadder): asks the AI with the niche
    DNA system prompt, requesting at most 2 sentences in Roman Urdu/English
    per the niche lane. Without a ladder: returns a neutral template reply.
    """
    if ladder is None:
        return NEUTRAL_REPLY
    dna = _load_dna(niche) or {}
    system = dna.get("system_prompt") or (
        "You are the content assistant for the '{}' niche.".format(niche)
    )
    system += (
        "\nWrite a brief, friendly reply to the page comment below in at "
        "most 2 short sentences. Language: Roman Urdu or English only, "
        "matching the niche lane. Never use Devanagari script."
    )
    prompt = ("Page comment: {}\n"
              "Write the reply only, no preamble.").format(comment_text or "")
    result = ladder.chat([{"role": "user", "content": prompt}],
                         system=system, timeout=30)
    if isinstance(result, dict):
        return str(result.get("text") or result.get("content") or result)
    return str(result)


def queue_reply(db_path, niche, post_id, comment_id, author, text, verdict,
                suggested_reply):
    """Put a drafted reply in the approval queue; returns the row id."""
    if verdict not in VALID_VERDICTS:
        raise ValueError("Invalid verdict {!r}".format(verdict))
    init_comment_tables(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO comment_replies (niche, post_id, comment_id, author,"
            " text, verdict, suggested_reply, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (niche, post_id or "", comment_id or "", author or "",
             text or "", verdict, suggested_reply or "", utc_now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_replies(db_path, niche=None, status=None):
    """List queued replies, optionally filtered by niche and/or status."""
    init_comment_tables(db_path)
    query = "SELECT * FROM comment_replies WHERE 1=1"
    params = []
    if niche:
        query += " AND niche = ?"
        params.append(niche)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id ASC"
    conn = _connect(db_path)
    try:
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def approve_reply(db_path, reply_id):
    """Approve a queued reply (human decision)."""
    _set_reply_status(db_path, reply_id, "approved")


def reject_reply(db_path, reply_id):
    """Reject a queued reply (human decision)."""
    _set_reply_status(db_path, reply_id, "rejected")


def mark_posted(db_path, reply_id):
    """Mark a reply as posted — call AFTER it was posted manually."""
    _set_reply_status(db_path, reply_id, "posted")


def _set_reply_status(db_path, reply_id, status):
    if status not in VALID_REPLY_STATUSES:
        raise ValueError("Invalid reply status {!r}".format(status))
    init_comment_tables(db_path)
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE comment_replies SET status = ? WHERE id = ?",
                     (status, reply_id))
        conn.commit()
    finally:
        conn.close()
