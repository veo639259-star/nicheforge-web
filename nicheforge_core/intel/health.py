"""Niche Health Score — one number per niche from three components.

  consistency (40 pts): scheduled posts in the last 7 days / 35 target
  engagement trend (35 pts): avg engagement last 14d vs prior 14d
  freshness (25 pts): 1.0 if any idea or post in the last 3 days,
                     decaying linearly to 0 at 14 days

Flags: "needs attention" if score < 40; "quiet" if no posts in 7 days;
"no data" if the niche has no metrics at all. UI strings are en-GB.
"""
import json
from datetime import datetime, timedelta, timezone

from intel.util import utc_now, connect, NICHE_IDS
from research import reject_devanagari

_CONSISTENCY_PTS = 40.0
_TREND_PTS = 35.0
_FRESHNESS_PTS = 25.0
_WEEKLY_TARGET = 35
_CONSISTENCY_DAYS = 7
_TREND_WINDOW_D = 14
_FRESH_DAYS = 3
_STALE_DAYS = 14
_TREND_RATIO_CAP = 1.5
_ATTENTION_THRESHOLD = 40


def _validate_niche(niche):
    if niche not in NICHE_IDS:
        raise ValueError("unknown niche {!r}".format(niche))


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,)).fetchone()
    return row is not None


def _engagement(row):
    return (row["likes"] or 0) + (row["shares"] or 0) + (row["comments"] or 0)


def _consistency(conn, niche, now):
    """Fraction of the weekly scheduling target hit in the last 7 days."""
    if not _table_exists(conn, "scheduled_posts"):
        return 0.0, 0
    cutoff = _iso(now - timedelta(days=_CONSISTENCY_DAYS))
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM scheduled_posts"
        " WHERE niche = ? AND slot_utc >= ? AND slot_utc <= ?",
        (niche, cutoff, _iso(now))).fetchone()
    n = row["n"] if row else 0
    return min(1.0, n / _WEEKLY_TARGET), n


def _trend(conn, niche, now):
    """Engagement trend: avg engagement last 14d vs the 14d before it.

    Returns (0-1 score, recent_avg, prior_avg).
    """
    recent_cut = _iso(now - timedelta(days=_TREND_WINDOW_D))
    prior_cut = _iso(now - timedelta(days=2 * _TREND_WINDOW_D))
    rows = conn.execute(
        "SELECT posted_at, likes, shares, comments FROM post_metrics"
        " WHERE niche = ? AND posted_at >= ?",
        (niche, prior_cut)).fetchall()
    recent = [_engagement(r) for r in rows
              if (r["posted_at"] or "") >= recent_cut]
    prior = [_engagement(r) for r in rows
             if (r["posted_at"] or "") < recent_cut]
    recent_avg = sum(recent) / len(recent) if recent else 0.0
    prior_avg = sum(prior) / len(prior) if prior else 0.0

    if not recent and not prior:
        return 0.5, recent_avg, prior_avg  # no data at all
    if not prior or prior_avg <= 0:
        # Nothing to compare against: growing beats flat.
        return (1.0 if recent_avg > 0 else 0.5), recent_avg, prior_avg
    ratio = recent_avg / prior_avg
    ratio = max(0.0, min(_TREND_RATIO_CAP, ratio))
    return ratio / _TREND_RATIO_CAP, recent_avg, prior_avg


def _freshness(conn, niche, now):
    """1.0 if any idea/post activity in the last 3d, decaying to 0 at 14d."""
    latest = None
    if _table_exists(conn, "ideas"):
        row = conn.execute(
            "SELECT MAX(created_at) AS ts FROM ideas WHERE niche = ?",
            (niche,)).fetchone()
        latest = row["ts"] if row else None
    for column in ("posted_at", "created_at"):
        row = conn.execute(
            "SELECT MAX({}) AS ts FROM post_metrics"
            " WHERE niche = ?".format(column), (niche,)).fetchone()
        ts = row["ts"] if row else None
        if ts and (latest is None or ts > latest):
            latest = ts
    if not latest:
        return 0.0, None
    dt = _parse_iso(latest)
    if dt is None:
        return 0.0, None
    days = (now - dt).total_seconds() / 86400.0
    if days <= _FRESH_DAYS:
        return 1.0, days
    decayed = max(0.0, 1.0 - (days - _FRESH_DAYS) /
                  (_STALE_DAYS - _FRESH_DAYS))
    return decayed, days


def compute_health(db_path, niche):
    """Return (score 0-100 int, detail dict) for one niche."""
    _validate_niche(niche)
    now = _now()
    conn = connect(db_path)
    try:
        consistency, scheduled_7d = _consistency(conn, niche, now)
        trend, recent_avg, prior_avg = _trend(conn, niche, now)
        freshness, last_activity_days = _freshness(conn, niche, now)
        metric_row = conn.execute(
            "SELECT COUNT(*) AS n FROM post_metrics WHERE niche = ?",
            (niche,)).fetchone()
        metric_count = metric_row["n"] if metric_row else 0
    finally:
        conn.close()

    consistency_pts = round(_CONSISTENCY_PTS * consistency, 2)
    trend_pts = round(_TREND_PTS * trend, 2)
    freshness_pts = round(_FRESHNESS_PTS * freshness, 2)
    score = int(round(consistency_pts + trend_pts + freshness_pts))
    score = max(0, min(100, score))

    flags = []
    if score < _ATTENTION_THRESHOLD:
        flags.append("needs attention")
    if scheduled_7d == 0:
        flags.append("quiet")
    if metric_count == 0:
        flags.append("no data")
    for flag in flags:
        reject_devanagari(flag, "health flag")

    detail = {
        "consistency_pts": consistency_pts,
        "trend_pts": trend_pts,
        "freshness_pts": freshness_pts,
        "scheduled_7d": scheduled_7d,
        "recent_avg_engagement": round(recent_avg, 2),
        "prior_avg_engagement": round(prior_avg, 2),
        "last_activity_days_ago": (round(last_activity_days, 2)
                                   if last_activity_days is not None else None),
        "flags": flags,
    }
    return (score, detail)


def refresh_all(db_path):
    """Recompute health for every niche and upsert into ``niche_health``.

    Returns {niche: score}.
    """
    result = {}
    conn = connect(db_path)
    try:
        for niche in NICHE_IDS:
            score, detail = compute_health(db_path, niche)
            conn.execute(
                "INSERT OR REPLACE INTO niche_health"
                " (niche, score, detail_json, computed_at)"
                " VALUES (?, ?, ?, ?)",
                (niche, score, json.dumps(detail), utc_now()))
            result[niche] = score
        conn.commit()
    finally:
        conn.close()
    return result


def health_map(db_path):
    """{niche: {score, flags}} for the dashboard. Computes on the fly."""
    import json
    out = {}
    for niche in NICHE_IDS:
        score, detail = compute_health(db_path, niche)
        out[niche] = {"score": score, "flags": detail.get("flags", [])}
    return out
