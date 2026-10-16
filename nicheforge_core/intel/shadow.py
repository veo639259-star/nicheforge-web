"""Shadow Ban Detector — early warning for sudden reach drops.

Compares the most recent post's reach against the median reach of the last
7 days. This is an early warning, never a diagnosis: alert wording always
says "possible restriction — check manually".
"""
import statistics
from datetime import datetime, timedelta, timezone

from intel.util import utc_now, connect, NICHE_IDS
from research import reject_devanagari

_WINDOW_DAYS = 7
_MIN_WINDOW_POSTS = 3
_ALERT_RATIO = 0.5


def _validate_niche(niche):
    if niche not in NICHE_IDS:
        raise ValueError("unknown niche {!r}".format(niche))


def check(db_path, niche):
    """Return {niche, median_reach, current_reach, drop_pct, alert, message}.

    ``current_reach`` is the reach of the most recent metric; ``median_reach``
    is the median reach over the last 7 days. When fewer than 3 posts exist
    in the window, returns {"status": "ok-no-data"} instead. On alert, a row
    is inserted into ``shadow_alerts``.
    """
    _validate_niche(niche)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=_WINDOW_DAYS)).isoformat(timespec="seconds")

    conn = connect(db_path)
    try:
        latest = conn.execute(
            "SELECT reach, posted_at FROM post_metrics WHERE niche = ?"
            " ORDER BY posted_at DESC, id DESC LIMIT 1",
            (niche,)).fetchone()
        window = conn.execute(
            "SELECT reach FROM post_metrics WHERE niche = ?"
            " AND posted_at >= ?",
            (niche, cutoff)).fetchall()
    finally:
        conn.close()

    reaches = [r["reach"] or 0 for r in window]
    if latest is None or len(reaches) < _MIN_WINDOW_POSTS:
        return {"status": "ok-no-data", "niche": niche}

    current = latest["reach"] or 0
    median = int(round(statistics.median(reaches)))
    if median > 0:
        drop_pct = round(100.0 * (median - current) / median, 1)
    else:
        drop_pct = 0.0
    alert = median > 0 and current < _ALERT_RATIO * median

    if alert:
        message = ("Latest post reach ({}) is down {:.0f}% vs the 7-day"
                   " median ({}). Early warning only, never a diagnosis:"
                   " possible restriction — check manually.").format(
                       current, drop_pct, median)
        conn = connect(db_path)
        try:
            conn.execute(
                "INSERT INTO shadow_alerts (niche, detected_at, median_reach,"
                " current_reach, status)"
                " VALUES (?, ?, ?, ?, 'new')",
                (niche, utc_now(), median, current))
            conn.commit()
        finally:
            conn.close()
    else:
        message = "Reach is within the normal range — no action needed."

    reject_devanagari(message, "shadow message")
    return {
        "niche": niche,
        "median_reach": median,
        "current_reach": current,
        "drop_pct": drop_pct,
        "alert": alert,
        "message": message,
    }
