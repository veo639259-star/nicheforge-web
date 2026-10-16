"""Viral Feedback Loop — score ideas against historical niche performance.

Cold start (no metrics at all): heuristic rules only. Otherwise a niche's
historical engagement, scaled against the global average, contributes up to
25 points. UI strings are en-GB English, never Devanagari.
"""
import re

from intel.util import utc_now, connect, NICHE_IDS
import db
from research import load_dna, reject_devanagari

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MIN_KEYWORD_LEN = 4
_TOP_POSTS = 3
_BASE_SCORE = 50.0
_ENGAGEMENT_BONUS = 25.0


def _validate_niche(niche):
    if niche not in NICHE_IDS:
        raise ValueError("unknown niche {!r}".format(niche))


def _tokens(text):
    return [t for t in _TOKEN_RE.findall((text or "").lower())
            if len(t) >= _MIN_KEYWORD_LEN]


def _engagement(row):
    return (row["likes"] or 0) + (row["shares"] or 0) + (row["comments"] or 0)


def _niche_name(niche):
    try:
        return load_dna(niche).get("display_name", niche)
    except Exception:
        return niche


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,)).fetchone()
    return row is not None


def _top_post_titles(conn, db_path, niche, top_post_ids, exclude_idea_id=None):
    """Titles for the niche's top-performing posts.

    Lookup chain: post_metrics.post_id -> fb_posts.post_id -> caption_head
    (the post's title head). Falls back to the niche's recent idea titles
    when no published-post mapping exists, so keyword overlap always has a
    real title pool to compare against. The idea being scored is excluded
    from the pool so it cannot match itself.
    """
    titles = []
    if top_post_ids and _table_exists(conn, "fb_posts"):
        placeholders = ",".join("?" for _ in top_post_ids)
        rows = conn.execute(
            "SELECT caption_head FROM fb_posts WHERE post_id IN ({})"
            .format(placeholders), tuple(top_post_ids)).fetchall()
        titles = [r["caption_head"] for r in rows if r["caption_head"]]
    if not titles:
        ideas = db.list_ideas(db_path, niche=niche)
        titles = [i["title"] for i in ideas
                  if i["title"] and i["id"] != exclude_idea_id]
    return titles


def score_idea(db_path, idea_id, title, detail, niche):
    """Score an idea 0-100. Returns (score float, reason str)."""
    _validate_niche(niche)
    title = title or ""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT post_id, niche, likes, shares, comments"
            " FROM post_metrics").fetchall()
        top_ids = [r["post_id"] for r in
                   sorted([r for r in rows if r["niche"] == niche],
                          key=_engagement, reverse=True)[:_TOP_POSTS]
                   if r["post_id"]]
        top_titles = _top_post_titles(conn, db_path, niche, top_ids, idea_id)
    finally:
        conn.close()

    parts = ["base {}".format(int(_BASE_SCORE))]
    score = _BASE_SCORE
    has_data = bool(rows)

    if has_data:
        global_avg = sum(_engagement(r) for r in rows) / len(rows)
        niche_rows = [r for r in rows if r["niche"] == niche]
        if global_avg > 0:
            niche_avg = (sum(_engagement(r) for r in niche_rows) /
                         len(niche_rows)) if niche_rows else 0.0
            ratio = niche_avg / global_avg
            bonus = _ENGAGEMENT_BONUS * min(1.0, max(0.0, ratio))
            score += bonus
            parts.append("+engagement {:.1f} (niche avg {:.0f} vs global"
                         " avg {:.0f})".format(bonus, niche_avg, global_avg))
        else:
            parts.append("cold start — heuristics only")
    else:
        parts.append("cold start — heuristics only")

    if 40 <= len(title) <= 120:
        score += 10
        parts.append("+length 10 (ideal 40-120 chars)")
    if "?" in title:
        score += 5
        parts.append("+question 5")
    if any(ch.isdigit() for ch in title):
        score += 5
        parts.append("+digit 5")

    if has_data and top_titles:
        top_words = set()
        for t in top_titles:
            top_words.update(_tokens(t))
        if top_words & set(_tokens(title)):
            score += 5
            parts.append("+keywords 5 (matches top-performing titles)")

    score = max(0.0, min(100.0, round(float(score), 1)))
    reason = "{}: {}".format(_niche_name(niche), "; ".join(parts))
    reject_devanagari(reason, "score reason")
    return (score, reason)


def refresh_scores(db_path):
    """Score every pending idea and upsert into ``idea_scores``.

    Returns the number of ideas scored.
    """
    ideas = db.list_ideas(db_path, status="pending")
    conn = connect(db_path)
    try:
        for idea in ideas:
            score, reason = score_idea(db_path, idea["id"], idea["title"],
                                       idea.get("detail", ""), idea["niche"])
            conn.execute(
                "INSERT OR REPLACE INTO idea_scores"
                " (idea_id, score, reason, scored_at)"
                " VALUES (?, ?, ?, ?)",
                (idea["id"], score, reason, utc_now()))
        conn.commit()
    finally:
        conn.close()
    return len(ideas)


def score_map(db_path):
    """{idea_id: score} for the inbox badges. Refreshes first."""
    refresh_scores(db_path)
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT idea_id, score FROM idea_scores").fetchall()
    finally:
        conn.close()
    return {str(r["idea_id"]): r["score"] for r in rows}
