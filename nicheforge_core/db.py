"""NicheForge Idea Bank — SQLite persistence layer.

Two tables:
  ideas — the approval inbox (title/detail ideas, deduped by TF-IDF cosine).
  usage — token usage log; schema MUST NOT change (providers/ writes to it).
"""
import math
import re
import sqlite3
from datetime import datetime, timezone

NICHE_IDS = [
    "wicketverse", "pakwire", "maloomat", "sukhan", "paheli",
    "memeistan", "lafz", "deen", "parhai", "aangan",
    "angrezi", "techsathi", "imtihan", "marvelverse",
]

VALID_STATUSES = {"pending", "approved", "rejected"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path):
    """Create the ideas and usage tables if they don't exist."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                niche TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                decided_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                ok INTEGER DEFAULT 1
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def init_publish_tables(db_path):
    """Create the fb_posts log table (Phase-2 publisher) if it doesn't exist.
    Does not alter the ideas/usage tables."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fb_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                niche TEXT NOT NULL DEFAULT '',
                page_id TEXT NOT NULL DEFAULT '',
                post_id TEXT,
                image_path TEXT DEFAULT '',
                caption_head TEXT DEFAULT '',
                scheduled_utc TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT DEFAULT ''
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- dedup

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return _WORD_RE.findall((text or "").lower())


def _tf(tokens):
    vec = {}
    for t in tokens:
        vec[t] = vec.get(t, 0) + 1
    return vec


def _cosine(tf_a, idf, tf_b):
    dot = 0.0
    for term, count_a in tf_a.items():
        if term in idf and term in tf_b:
            w = idf[term]
            dot += (count_a * w) * (tf_b[term] * w)
    norm_a = math.sqrt(sum((c * idf[t]) ** 2 for t, c in tf_a.items() if t in idf))
    norm_b = math.sqrt(sum((c * idf[t]) ** 2 for t, c in tf_b.items() if t in idf))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_similar(db_path, niche, title, detail="", threshold=0.82):
    """TF-IDF cosine similarity of (title + detail) against existing ideas of
    the same niche with status != 'rejected'. Returns (idea_id, score) of the
    best match >= threshold, else (None, 0.0). Pure Python, no sklearn."""
    init_db(db_path)
    corpus = []
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, title, detail FROM ideas WHERE niche = ? AND status != 'rejected'",
            (niche,),
        ).fetchall()
        for r in rows:
            toks = _tokens((r["title"] or "") + " " + (r["detail"] or ""))
            if toks:
                corpus.append((r["id"], _tf(toks)))
    finally:
        conn.close()

    if not corpus:
        return (None, 0.0)

    n = len(corpus) + 1
    df = {}
    all_vecs = [_tf(_tokens((title or "") + " " + (detail or "")))]
    all_vecs.extend(vec for _, vec in corpus)
    for vec in all_vecs:
        for term in vec:
            df[term] = df.get(term, 0) + 1
    # Smoothed IDF: plain log(n/df) zeroes out terms shared by every doc,
    # collapsing similarity on tiny corpora. The +1.0 keeps shared terms at
    # weight 1 and boosts rare (discriminating) terms above 1.
    idf = {term: math.log(n / c) + 1.0 for term, c in df.items()}

    query = all_vecs[0]
    best_id, best_score = None, 0.0
    for idea_id, vec in corpus:
        score = _cosine(query, idf, vec)
        if score > best_score:
            best_id, best_score = idea_id, score

    if best_id is not None and best_score >= threshold:
        return (best_id, round(best_score, 3))
    return (None, 0.0)


def add_idea(db_path, niche, title, detail=""):
    """Insert an idea after dedup. Returns (ok, info): on success (True,
    "idea #<id> added"); on duplicate (False, "duplicate of #<id> (<score>)")."""
    init_db(db_path)
    title = (title or "").strip()
    if not title:
        return (False, "title is required")
    dup_id, score = find_similar(db_path, niche, title, detail or "")
    if dup_id is not None:
        return (False, "duplicate of #{} ({})".format(dup_id, score))

    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO ideas (niche, title, detail, status, created_at, decided_at)"
            " VALUES (?, ?, ?, 'pending', ?, NULL)",
            (niche, title, detail or "", utc_now()),
        )
        conn.commit()
        return (True, "idea #{} added".format(cur.lastrowid))
    except sqlite3.Error as e:
        return (False, "db error: {}".format(e))
    finally:
        conn.close()


def set_status(db_path, idea_id, status):
    """Set status (approved/rejected/pending); stamps decided_at UTC ISO."""
    init_db(db_path)
    if status not in VALID_STATUSES:
        raise ValueError("status must be one of {}".format(sorted(VALID_STATUSES)))
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE ideas SET status = ?, decided_at = ? WHERE id = ?",
            (status, utc_now(), idea_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_ideas(db_path, status=None, niche=None):
    """Newest-first list of ideas as dicts, optionally filtered."""
    init_db(db_path)
    sql = "SELECT id, niche, title, detail, status, created_at, decided_at FROM ideas"
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if niche:
        clauses.append("niche = ?")
        params.append(niche)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC"
    conn = _connect(db_path)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
