"""Phase-4 intel signal tests — plain asserts, temp DB, no live network."""
import os
import sys
import tempfile
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intel import init_intel_tables
from intel import trends, newsjack, crisis, festivals
from intel.util import connect
import db
from research import load_dna


def check(name, cond):
    assert cond, "FAILED: " + name
    print("ok - " + name)


def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    init_intel_tables(path)
    return path


# ------------------------------------------------------------------ trends
def test_trends():
    db_path = fresh_db()
    real_fetch = trends._fetch

    # Failing fetch -> degraded
    trends._fetch = lambda url, timeout=12: []
    try:
        r = trends.poll(db_path)
        check("trends degraded on failing fetch", r["status"] == "degraded")
        check("trends degraded reason mentions feeds",
              "feeds" in r.get("reason", ""))

        # Second poll too soon -> skipped
        r2 = trends.poll(db_path)
        check("trends second poll skipped",
              r2["status"] == "skipped" and "reason" in r2)

        # Fixture fetch -> ok
        def fixture(url, timeout=12):
            if "dawn" in url:
                return ["Pakistan cricket team wins T20 match in Lahore",
                        "Government assembly passes court bill on budget"]
            return ["Babar Azam century seals cricket match victory",
                    "Funny viral meme spreads across Pakistan",
                    "Viral meme video breaks the internet in Pakistan"]
        trends._fetch = fixture
        r3 = trends.poll(db_path, min_interval_min=0)
        check("trends fixture poll ok", r3["status"] == "ok")
        topics = r3["topics"]
        check("trends returns topics", len(topics) > 0)
        by_word = {t["topic"]: t for t in topics}
        check("trends counts cricket twice",
              by_word.get("cricket", {}).get("score", 0) == 2)
        check("trends matches cricket to wicketverse",
              "wicketverse" in by_word["cricket"]["niches"])
        check("trends matches meme to memeistan",
              "memeistan" in by_word.get("meme", {}).get("niches", []) or
              "memeistan" in by_word.get("viral", {}).get("niches", []))

        conn = connect(db_path)
        rows = conn.execute(
            "SELECT topic, niches_csv, status FROM trend_alerts").fetchall()
        conn.close()
        check("trend_alerts rows stored",
              len(rows) == len(topics))
        check("trend_alerts status new",
              all(rw["status"] == "new" for rw in rows))
    finally:
        trends._fetch = real_fetch

    check("x_trends_status degraded",
          trends.x_trends_status() == {
              "status": "degraded",
              "reason": "X trends need API auth — not configured"})


# ---------------------------------------------------------------- newsjack
def test_newsjack():
    db_path = fresh_db()
    niches = ["memeistan", "pakwire"]
    r = newsjack.on_spike(
        db_path, "Big storm hits Lahore",
        "Met office confirms; schools closed tomorrow", niches)
    check("newsjack briefs_created", r == {"briefs_created": 2})

    conn = connect(db_path)
    rows = conn.execute(
        "SELECT niche, title, detail, status FROM ideas "
        "WHERE title LIKE '[NEWSJACK]%'").fetchall()
    conn.close()
    check("newsjack created 2 inbox ideas", len(rows) == 2)
    check("newsjack ideas pending",
          all(rw["status"] == "pending" for rw in rows))
    check("newsjack titles carry headline",
          all(rw["title"].startswith("[NEWSJACK] Big storm hits Lahore")
              for rw in rows))

    dna_rules = load_dna("memeistan")["rules"][:3]
    meme_row = [rw for rw in rows if rw["niche"] == "memeistan"][0]
    check("newsjack brief has 3-line structure",
          "1) What happened" in meme_row["detail"] and
          "2)" in meme_row["detail"] and "3)" in meme_row["detail"])
    check("newsjack brief includes DNA rules verbatim",
          all(rule in meme_row["detail"] for rule in dna_rules))

    conn = connect(db_path)
    runs = conn.execute("SELECT * FROM newsjack_runs").fetchall()
    conn.close()
    check("newsjack_runs row inserted",
          len(runs) == 1 and runs[0]["briefs_created"] == 2)

    try:
        newsjack.on_spike(db_path, "x", "y", ["nope"])
        check("newsjack rejects unknown niche", False)
    except ValueError:
        check("newsjack rejects unknown niche", True)


# ------------------------------------------------------------------- crisis
SCHEDULED_POSTS_DDL = """
CREATE TABLE scheduled_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    niche TEXT NOT NULL,
    slot_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TEXT NOT NULL
);
"""


def test_crisis():
    db_path = fresh_db()
    conn = connect(db_path)
    conn.execute(SCHEDULED_POSTS_DDL)
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [
        ("memeistan", today + "T09:00:00+00:00"),
        ("paheli", today + "T12:00:00+00:00"),
        ("pakwire", today + "T15:00:00+00:00"),
        ("memeistan", "2020-01-01T09:00:00+00:00"),  # old date, untouched
    ]
    for niche, slot in rows:
        conn.execute(
            "INSERT INTO scheduled_posts (idea_id, niche, slot_utc, status, created_at)"
            " VALUES (1, ?, ?, 'scheduled', ?)",
            (niche, slot, datetime.now(timezone.utc).isoformat()))
    conn.commit()

    before = conn.execute("SELECT COUNT(*) c FROM scheduled_posts").fetchone()["c"]
    conn.close()

    r = crisis.scan(db_path, feed_items=[("blast kills 12 in market", "Dawn")],
                    _today=today)
    check("crisis triggered", r["triggered"] is True)
    check("crisis paused only cheerful posts", r["paused_count"] == 2)
    event_id = r["event_id"]

    conn = connect(db_path)
    statuses = {(rw["niche"], rw["slot_utc"]): rw["status"]
                for rw in conn.execute(
                    "SELECT niche, slot_utc, status FROM scheduled_posts")}
    total = conn.execute("SELECT COUNT(*) c FROM scheduled_posts").fetchone()["c"]
    ev = conn.execute(
        "SELECT * FROM crisis_events WHERE id=?", (event_id,)).fetchone()
    conn.close()

    check("crisis never deletes rows", total == before)
    check("memeistan today paused",
          statuses[("memeistan", today + "T09:00:00+00:00")] == "paused_by_crisis")
    check("paheli today paused",
          statuses[("paheli", today + "T12:00:00+00:00")] == "paused_by_crisis")
    check("pakwire today untouched",
          statuses[("pakwire", today + "T15:00:00+00:00")] == "scheduled")
    check("old cheerful post untouched",
          statuses[("memeistan", "2020-01-01T09:00:00+00:00")] == "scheduled")
    check("crisis_events row recorded",
          ev is not None and ev["paused_count"] == 2 and
          ev["status"] == "active")

    # Log file written (ROOT-relative path)
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "workspace", "intel", "crisis.log")
    check("crisis.log written",
          os.path.exists(log_path) and "TRIGGERED" in open(log_path).read())

    # Resume restores
    rr = crisis.resume(db_path, event_id)
    check("crisis resume ok",
          rr == {"resumed": True, "event_id": event_id, "restored_count": 2})
    conn = connect(db_path)
    restored = conn.execute(
        "SELECT COUNT(*) c FROM scheduled_posts "
        "WHERE status='paused_by_crisis'").fetchone()["c"]
    sched = conn.execute(
        "SELECT COUNT(*) c FROM scheduled_posts "
        "WHERE status='scheduled' AND date(slot_utc)=?",
        (today,)).fetchone()["c"]
    ev2 = conn.execute(
        "SELECT status FROM crisis_events WHERE id=?", (event_id,)).fetchone()
    conn.close()
    check("no paused rows remain", restored == 0)
    check("today's posts back to scheduled", sched == 3)
    check("event resolved", ev2["status"] == "resolved")

    # Benign feed -> not triggered
    r3 = crisis.scan(db_path,
                     feed_items=[("New phone launched with great camera", "Tech")],
                     _today=today)
    check("crisis not triggered on benign feed", r3["triggered"] is False)

    rr2 = crisis.resume(db_path, 999999)
    check("resume unknown event handled", rr2["resumed"] is False)


# ---------------------------------------------------------------- festivals
def test_festivals():
    db_path = fresh_db()

    up = festivals.upcoming(days_ahead=7, _today=date(2026, 8, 10))
    names = [f["name"] for f in up]
    check("upcoming finds 14 August",
          "Independence Day (14 August)" in names)
    aug14 = [f for f in up if f["name"] == "Independence Day (14 August)"][0]
    check("pack_date correct", aug14["pack_date"] == "2026-08-14")
    check("23 March not in window", "Pakistan Day (23 March)" not in names)

    lunar = [f for f in festivals.FESTIVALS if f["month"] in (2, 3, 5)
             and "Eid" in f["name"] or f["name"] == "Ramadan start"]
    check("lunar festivals marked approximate",
          all("(date approximate — update yearly)" in f["note"] for f in lunar))

    r = festivals.generate_packs(db_path, days_ahead=7, _today=date(2026, 8, 10))
    check("generate_packs creates packs", r["packs"] >= 1)
    check("generate_packs creates ideas", r["ideas"] >= 5)

    conn = connect(db_path)
    packs = conn.execute("SELECT * FROM festival_packs").fetchall()
    ideas = conn.execute(
        "SELECT niche, title, status FROM ideas WHERE title LIKE '[FESTIVAL]%'"
    ).fetchall()
    conn.close()
    check("festival_packs rows planned",
          len(packs) == r["packs"] and
          all(p["status"] == "planned" for p in packs))
    check("festival ideas pending", all(i["status"] == "pending" for i in ideas))
    check("festival idea title format",
          all(i["title"].startswith("[FESTIVAL] ") and " — " in i["title"]
              for i in ideas))

    # Idempotent second run
    r2 = festivals.generate_packs(db_path, days_ahead=7, _today=date(2026, 8, 10))
    check("generate_packs idempotent", r2 == {"packs": 0, "ideas": 0})


if __name__ == "__main__":
    test_trends()
    test_newsjack()
    test_crisis()
    test_festivals()
    print("ALL INTEL SIGNALS TESTS PASSED")
