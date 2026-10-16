"""Crisis Shield — pause cheerful scheduled posts when bad news breaks.

CHEERFUL_NICHES lists the niches whose tone would feel inappropriate during
a crisis. It is a module constant: edit it here to change which niches get
paused. Pauses are reversible via resume(); nothing is ever deleted.
"""
import os
from datetime import datetime, timezone

from intel.util import utc_now, connect
from intel import trends as _trends

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRISIS_LOG = os.path.join(ROOT, "workspace", "intel", "crisis.log")

CRISIS_KEYWORDS = [
    "earthquake", "earthquakes",
    "blast", "blasts",
    "crash", "crashed", "crashes",
    "killed", "killing", "kills", "dead", "deadly",
    "flood", "floods", "flooding",
    "fire", "fires",
    "attack", "attacks", "attacked",
    "bomb", "bombs", "bombing",
    "collapse", "collapsed",
    "drown", "drowned", "drowning",
    "martyr", "martyred",
    "terror", "terrorist", "terrorism",
]

# Configurable: niches with a cheerful tone that get paused during a crisis.
CHEERFUL_NICHES = ["memeistan", "paheli", "lafz", "sukhan", "marvelverse", "aangan"]


def _is_crisis(headline):
    h = (headline or "").lower()
    return any(k in h for k in CRISIS_KEYWORDS)


def _log(line):
    os.makedirs(os.path.dirname(CRISIS_LOG), exist_ok=True)
    with open(CRISIS_LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _today_str(_today):
    if _today:
        return str(_today)
    return datetime.now(timezone.utc).date().isoformat()


def scan(db_path, feed_items=None, _today=None):
    """Scan headlines for crisis keywords.

    feed_items: list of (headline, source); when None the trends RSS feeds
    are fetched best-effort. On a hit, today's scheduled cheerful posts are
    paused (never deleted), a crisis_events row is inserted and the event is
    appended to workspace/intel/crisis.log.
    """
    if feed_items is None:
        feed_items = []
        for _name, url in _trends.RSS_FEEDS:
            try:
                for title in _trends._fetch(url):
                    feed_items.append((title, _name))
            except Exception:
                continue

    today = _today_str(_today)
    hit = None
    for headline, source in feed_items:
        if _is_crisis(headline):
            hit = (headline, source)
            break

    if not hit:
        _log("{} SCAN clean ({} items)".format(utc_now(), len(feed_items)))
        return {"triggered": False, "scanned": len(feed_items)}

    headline, source = hit
    placeholders = ",".join("?" for _ in CHEERFUL_NICHES)
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE scheduled_posts SET status='paused_by_crisis' "
            "WHERE status='scheduled' AND date(slot_utc)=? AND niche IN ({})".format(
                placeholders),
            [today] + list(CHEERFUL_NICHES))
        paused = cur.rowcount
        cur = conn.execute(
            "INSERT INTO crisis_events "
            "(headline, source, detected_at, paused_count, status) "
            "VALUES (?, ?, ?, ?, 'active')",
            (headline, source, utc_now(), paused))
        conn.commit()
        event_id = cur.lastrowid
    finally:
        conn.close()

    _log("{} TRIGGERED | {} | source={} | paused={} | event_id={}".format(
        utc_now(), headline, source, paused, event_id))
    return {
        "triggered": True,
        "headline": headline,
        "source": source,
        "paused_count": paused,
        "event_id": event_id,
    }


def resume(db_path, event_id):
    """Restore posts paused by a crisis event and mark the event resolved."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM crisis_events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            return {"resumed": False,
                    "reason": "unknown event id {}".format(event_id)}
        event_date = (row["detected_at"] or "")[:10]
        placeholders = ",".join("?" for _ in CHEERFUL_NICHES)
        cur = conn.execute(
            "UPDATE scheduled_posts SET status='scheduled' "
            "WHERE status='paused_by_crisis' AND date(slot_utc)=? "
            "AND niche IN ({})".format(placeholders),
            [event_date] + list(CHEERFUL_NICHES))
        restored = cur.rowcount
        conn.execute(
            "UPDATE crisis_events SET status='resolved', resumed_at=? "
            "WHERE id=?",
            (utc_now(), event_id))
        conn.commit()
    finally:
        conn.close()
    return {"resumed": True, "event_id": event_id,
            "restored_count": restored}


def list_events(db_path, limit=20):
    """Crisis events, newest first."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, headline, source, detected_at, paused_count, status, resumed_at"
            " FROM crisis_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
