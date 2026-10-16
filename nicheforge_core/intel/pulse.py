"""Performance Pulse — collect and summarise per-niche post metrics.

Reads/writes the ``post_metrics`` table (created by ``intel.init_intel_tables``).
All UI-facing strings are en-GB English, never Devanagari.
"""
import csv
import io
import json
import urllib.request
from datetime import datetime

from intel.util import utc_now, connect, NICHE_IDS
from research import reject_devanagari

INSUFFICIENT_DATA = "Not enough data yet — add metrics to unlock insights."

GRAPH_API_VERSION = "v21.0"
GRAPH_TIMEOUT_S = 15


def _validate_niche(niche):
    if niche not in NICHE_IDS:
        raise ValueError("unknown niche {!r}".format(niche))


def _to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_iso(value):
    """Parse an ISO-8601 timestamp; return a datetime or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _engagement(row):
    return (row["likes"] or 0) + (row["shares"] or 0) + (row["comments"] or 0)


# ----------------------------------------------------------------- write

def record_metric(db_path, niche, post_id, posted_at, likes, shares,
                  comments, reach, source="manual"):
    """Insert one post-metrics row. Returns the new row id."""
    _validate_niche(niche)
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO post_metrics (niche, post_id, posted_at, likes, shares,"
            " comments, reach, source, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (niche, post_id or "", posted_at or "",
             _to_int(likes), _to_int(shares), _to_int(comments),
             _to_int(reach), source or "manual", utc_now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def import_csv(db_path, csv_text):
    """Import metrics from CSV text.

    Columns: niche,post_id,posted_at,likes,shares,comments,reach.
    Rows with an unknown niche, a missing post_id or unparseable numbers are
    skipped. Returns the number of rows imported.
    """
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    required = {"niche", "post_id", "posted_at", "likes", "shares",
                "comments", "reach"}
    header = set(reader.fieldnames or [])
    if not required.issubset(header):
        raise ValueError(
            "CSV must contain columns: {}".format(",".join(sorted(required))))
    count = 0
    for row in reader:
        niche = (row.get("niche") or "").strip()
        post_id = (row.get("post_id") or "").strip()
        try:
            likes = int(float(row["likes"]))
            shares = int(float(row["shares"]))
            comments = int(float(row["comments"]))
            reach = int(float(row["reach"]))
        except (TypeError, ValueError):
            continue  # bad numbers — skip the row
        if niche not in NICHE_IDS or not post_id:
            continue
        record_metric(db_path, niche, post_id, row.get("posted_at") or "",
                      likes, shares, comments, reach, source="csv")
        count += 1
    return count


def fetch_insights(db_path, niche, page_id, token):
    """Best-effort Facebook Graph fetch of recent post insights.

    Stores whatever comes back in ``post_metrics`` (source='graph') and
    returns the number of posts stored. On any failure raises RuntimeError
    with a plain human message (the route catches it).
    """
    _validate_niche(niche)
    fields = ("id,created_time,likes.summary(true),shares,"
              "comments.summary(true),insights.metric(post_impressions)")
    url = ("https://graph.facebook.com/{}/posts"
           "?fields={}&limit=25&access_token={}").format(
               GRAPH_API_VERSION, page_id, fields, token)
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "NicheForge/1.0"})
        with urllib.request.urlopen(req, timeout=GRAPH_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            "Facebook insights fetch failed ({}). Check the page ID and "
            "access token, then try again.".format(exc))
    posts = payload.get("data") or []
    stored = 0
    for post in posts:
        likes = ((post.get("likes") or {}).get("summary") or {}).get(
            "total_count", 0)
        shares = (post.get("shares") or {}).get("count", 0)
        comments = ((post.get("comments") or {}).get("summary") or {}).get(
            "total_count", 0)
        reach = 0
        for metric in (post.get("insights") or {}).get("data") or []:
            if metric.get("name") == "post_impressions":
                values = metric.get("values") or []
                if values:
                    reach = values[0].get("value", 0)
                break
        record_metric(db_path, niche, post.get("id", ""),
                      post.get("created_time", ""), likes, shares, comments,
                      reach, source="graph")
        stored += 1
    return stored


# --------------------------------------------------------------- summary

def _niche_display(niche):
    return niche[:1].upper() + niche[1:]


def _format_ratio(ratio):
    text = "{:.1f}".format(ratio).rstrip("0").rstrip(".")
    return "{}x".format(text or "0")


def _build_insight(niche, rows):
    """Plain-language insight computed from the rows, en-GB, no Devanagari."""
    n = len(rows)
    if n >= 5:
        by_hour = {}
        for row in rows:
            dt = _parse_iso(row["posted_at"])
            if dt is None:
                continue
            by_hour.setdefault(dt.hour, []).append(row["reach"] or 0)
        if len(by_hour) >= 2:
            hour_avg = {h: sum(v) / len(v) for h, v in by_hour.items()}
            best_hour = max(hour_avg, key=hour_avg.get)
            morning = [r for h, vals in by_hour.items()
                       for r in vals if 5 <= h <= 11]
            baseline = (sum(morning) / len(morning)) if morning \
                else sum(hour_avg.values()) / len(hour_avg)
            if baseline > 0:
                ratio = hour_avg[best_hour] / baseline
                if ratio >= 1.3:
                    return ("{} posts at {:02d}:00 get about {} the reach of"
                            " morning posts.").format(
                                _niche_display(niche), best_hour,
                                _format_ratio(ratio))
    if n >= 3:
        total_eng = sum(_engagement(r) for r in rows)
        total_shares = sum(r["shares"] or 0 for r in rows)
        if total_eng > 0:
            share_pct = round(100.0 * total_shares / total_eng)
            return ("Shares make up about {}% of engagement across {} {}"
                    " posts — shareable posts travel further.").format(
                        share_pct, n, _niche_display(niche))
    return INSUFFICIENT_DATA


def _summarise_niche(niche, rows):
    total_likes = sum(r["likes"] or 0 for r in rows)
    total_shares = sum(r["shares"] or 0 for r in rows)
    total_comments = sum(r["comments"] or 0 for r in rows)
    total_reach = sum(r["reach"] or 0 for r in rows)
    n = len(rows)
    avg_reach = (total_reach / n) if n else 0.0

    best_post = worst_post = None
    if rows:
        scored = [(_engagement(r), r) for r in rows]
        best = max(scored, key=lambda t: t[0])[1]
        worst = min(scored, key=lambda t: t[0])[1]
        best_post = {"post_id": best["post_id"],
                     "engagement": _engagement(best)}
        worst_post = {"post_id": worst["post_id"],
                      "engagement": _engagement(worst)}

    best_hour = None
    if n >= 2:
        hour_reach = {}
        for r in rows:
            dt = _parse_iso(r["posted_at"])
            if dt is not None:
                hour_reach.setdefault(dt.hour, []).append(r["reach"] or 0)
        if hour_reach:
            best_hour = max(hour_reach,
                            key=lambda h: sum(hour_reach[h]) /
                            len(hour_reach[h]))

    insight = _build_insight(niche, rows)
    reject_devanagari(insight, "pulse insight")

    return {
        "posts": n,
        "total_likes": total_likes,
        "total_shares": total_shares,
        "total_comments": total_comments,
        "avg_reach": round(avg_reach, 2),
        "best_post": best_post,
        "worst_post": worst_post,
        "best_hour": best_hour,
        "insight": insight,
    }


def summary(db_path, niche=None):
    """Per-niche performance summary.

    Returns {niche: {posts, total_likes, total_shares, total_comments,
    avg_reach, best_post, worst_post, best_hour, insight}} — for one niche
    when ``niche`` is given, otherwise for every niche that has metrics.
    """
    if niche is not None:
        _validate_niche(niche)
    conn = connect(db_path)
    try:
        if niche is not None:
            rows = conn.execute(
                "SELECT niche, post_id, posted_at, likes, shares, comments,"
                " reach FROM post_metrics WHERE niche = ?"
                " ORDER BY posted_at", (niche,)).fetchall()
            grouped = {niche: rows}
        else:
            all_rows = conn.execute(
                "SELECT niche, post_id, posted_at, likes, shares, comments,"
                " reach FROM post_metrics ORDER BY niche, posted_at").fetchall()
            grouped = {}
            for r in all_rows:
                grouped.setdefault(r["niche"], []).append(r)
    finally:
        conn.close()
    return {n: _summarise_niche(n, rs) for n, rs in grouped.items()}
