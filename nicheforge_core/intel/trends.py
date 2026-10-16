"""Trend Radar — poll public RSS feeds, extract trending topics, match them to niches.

No API keys needed. Polls at most once per ``min_interval_min`` minutes
(tracked in the intel_state table) and degrades gracefully when feeds
are unreachable.
"""
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from intel.util import utc_now, connect, NICHE_IDS
import db  # noqa: F401  (kept for convention parity with other intel modules)
from research import load_dna

RSS_FEEDS = [
    ("Google Trends PK", "https://trends.google.com/trending/rss?geo=PK"),
    ("Dawn", "https://www.dawn.com/feeds/home"),
]

LAST_POLL_KEY = "trends_last_poll"

STOPWORDS = frozenset(
    "a an the and or but of to in on for with at by from as is are was were be been "
    "being it its this that these those they them he she we you i my our their his "
    "her not no yes do does did have has had will would can could should may might "
    "must shall than then so such into out up down over under about between through "
    "during before after again once here there when where why how all any both each "
    "few more most other some only own same too very just don re ve ll".split()
)

# Used when a niche DNA file has no "keywords" field (none do today).
FALLBACK_KEYWORDS = {
    "wicketverse": ["cricket", "match", "t20", "odi", "test", "pakistan team",
                    "babar", "afridi", "psl", "wicket", "batting", "bowling"],
    "pakwire": ["pakistan", "government", "pti", "assembly", "court", "lahore",
                "karachi", "islamabad", "minister", "election", "budget"],
    "maloomat": ["facts", "science", "history", "space", "discovery", "world",
                 "pakistan"],
    "sukhan": ["poetry", "urdu", "shayari", "ghazal", "nazm"],
    "paheli": ["riddle", "puzzle", "quiz", "brain"],
    "memeistan": ["funny", "viral", "meme", "comedy", "joke"],
    "lafz": ["quote", "quotes", "motivation", "poetry", "lafz"],
    "deen": ["islam", "quran", "hadith", "ramadan", "eid", "muslim", "namaz",
             "deen"],
    "parhai": ["exam", "study", "education", "student", "school", "board",
               "result"],
    "aangan": ["drama", "film", "movie", "music", "song", "singer", "actor"],
    "angrezi": ["english", "learn", "vocabulary", "grammar"],
    "techsathi": ["tech", "mobile", "app", "google", "iphone", "android",
                  "software", "ai"],
    "imtihan": ["exam", "test", "mcq", "paper", "result", "admission"],
    "marvelverse": ["marvel", "avengers", "movie", "film", "hero"],
}


def _fetch(url, timeout=12):
    """Fetch an RSS feed and return its item titles. [] on any failure."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "NicheForge/1.0 (trend radar)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        titles = []
        for item in root.iter("item"):
            title = item.findtext("title")
            if title:
                titles.append(title.strip())
        return titles
    except Exception:
        return []


def _keywords(titles):
    """Count lowercase title words (len>=4, stopword-filtered)."""
    counts = {}
    for title in titles:
        for word in re.findall(r"[a-z]{4,}", (title or "").lower()):
            if word in STOPWORDS:
                continue
            counts[word] = counts.get(word, 0) + 1
    return counts


def _niche_hints(niche):
    """Keyword hints for a niche: DNA "keywords" field if present, else fallback."""
    try:
        dna = load_dna(niche)
        kws = dna.get("keywords")
        if kws:
            return [str(k).lower() for k in kws]
    except Exception:
        pass
    return FALLBACK_KEYWORDS.get(niche, [])


def _match_niches(topic):
    matched = []
    for niche in NICHE_IDS:
        for hint in _niche_hints(niche):
            if topic in hint or hint in topic:
                matched.append(niche)
                break
    return matched


def poll(db_path, min_interval_min=15, _now=None):
    """Poll RSS feeds and store the top-10 topics as trend_alerts rows."""
    now = _now or datetime.now(timezone.utc)
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT v FROM intel_state WHERE k=?", (LAST_POLL_KEY,)).fetchone()
        if row and row["v"]:
            last = datetime.fromisoformat(row["v"])
            elapsed_min = (now - last).total_seconds() / 60
            if elapsed_min < min_interval_min:
                return {
                    "status": "skipped",
                    "reason": "last poll {:.0f} min ago (< {} min interval)".format(
                        elapsed_min, min_interval_min),
                }

        titles = []
        for _name, url in RSS_FEEDS:
            got = _fetch(url)
            if got:
                titles.extend(got)

        # Record the attempt (success or not) so a failing feed does not get
        # hammered on every call.
        stamp = now.isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO intel_state (k, v) VALUES (?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (LAST_POLL_KEY, stamp))
        conn.commit()

        if not titles:
            return {
                "status": "degraded",
                "reason": "all {} feeds failed".format(len(RSS_FEEDS)),
            }

        counts = _keywords(titles)
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        topics = []
        for word, count in top:
            niches = _match_niches(word)
            topics.append({"topic": word, "score": count, "niches": niches})
            conn.execute(
                "INSERT INTO trend_alerts "
                "(topic, niches_csv, score, detected_at, status) "
                "VALUES (?, ?, ?, ?, 'new')",
                (word, ",".join(niches), count, utc_now()))
        conn.commit()
        return {"status": "ok", "topics": topics}
    finally:
        conn.close()


def x_trends_status():
    """X/Twitter trends are not available without API auth."""
    return {
        "status": "degraded",
        "reason": "X trends need API auth — not configured",
    }


def list_alerts(db_path, limit=20):
    """Most recent trend alerts, newest first."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT topic, niches_csv, score, detected_at, status FROM trend_alerts"
            " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
