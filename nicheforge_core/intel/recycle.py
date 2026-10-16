"""Evergreen Recycler — resurface top-performing old posts with fresh angles.

find_candidates: picks evergreen winners from post_metrics.
make_briefs: turns each candidate into a pending [RECYCLE] idea plus a
recycle_briefs row. Heuristic (no AI) in v1; ladder accepted for future use.
"""
import math
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from intel.util import connect, utc_now  # noqa: E402
from research import reject_devanagari  # noqa: E402

RENEWAL_ANGLES = [
    "fresh caption hook, same image re-cropped",
    "new opening line + reordered facts",
    "Roman Urdu version of the original caption",
    "zoomed detail crop + question-style caption",
]


def _parse_ts(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_candidates(db_path, min_age_days=90, _now=None):
    """Old posts (posted_at older than min_age_days) ranked by engagement
    (likes+shares+comments). Returns the top decile by engagement — at least
    the top 3 when there are fewer than 30 posts — as
    [{niche, post_id, posted_at, engagement}]."""
    now = _now if isinstance(_now, datetime) else _parse_ts(_now) \
        if _now else datetime.now(timezone.utc)

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT niche, post_id, posted_at, likes, shares, comments "
            "FROM post_metrics"
        ).fetchall()
    finally:
        conn.close()

    aged = []
    for r in rows:
        posted = _parse_ts(r["posted_at"])
        if posted is None:
            continue
        age_days = (now - posted).total_seconds() / 86400.0
        if age_days >= min_age_days:
            engagement = int(r["likes"] or 0) + int(r["shares"] or 0) \
                + int(r["comments"] or 0)
            aged.append({
                "niche": r["niche"],
                "post_id": r["post_id"],
                "posted_at": r["posted_at"],
                "engagement": engagement,
            })

    aged.sort(key=lambda c: (-c["engagement"], c["posted_at"]))
    if not aged:
        return []
    keep = max(3, math.ceil(len(aged) / 10))
    return aged[:keep]


def make_briefs(db_path, ladder=None, _now=None):
    """For every recycle candidate, insert a pending [RECYCLE] idea and a
    recycle_briefs row. Returns {"briefs_created": n}."""
    candidates = find_candidates(db_path, _now=_now)
    created = 0
    rows = []

    for i, c in enumerate(candidates):
        new_angle = RENEWAL_ANGLES[i % len(RENEWAL_ANGLES)]
        stats = (
            "Original engagement: {} (post_id {}, posted {})"
        ).format(c["engagement"], c["post_id"], c["posted_at"])
        detail = "New angle: {}.\n{}".format(new_angle, stats)
        reject_devanagari(detail, "recycle brief")
        title = "[RECYCLE] {} / {}".format(c["niche"], c["post_id"])
        db.add_idea(db_path, c["niche"], title, detail=detail)
        rows.append((c["niche"], c["post_id"], c["posted_at"],
                     c["engagement"], new_angle))
        created += 1

    # Insert recycle_briefs rows in one transaction AFTER the idea inserts,
    # so we never hold a write lock across db.add_idea's own connection.
    conn = connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO recycle_briefs "
            "(niche, post_id, posted_at, engagement, new_angle, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'new', ?)",
            [r + (utc_now(),) for r in rows],
        )
        conn.commit()
    finally:
        conn.close()

    return {"briefs_created": created}
