"""Tests for NicheForge intel modules (Phase-4): pulse, feedback, health, shadow.

Plain asserts on a temp DB. No network. Exits non-zero on first failure.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db as ideas_db
import schedule
from intel import init_intel_tables
from intel import pulse, feedback, health, shadow

NOW = datetime.now(timezone.utc)


def _iso(hours=18, minutes=30, days_ago=0):
    dt = (NOW - timedelta(days=days_ago)).replace(
        hour=hours, minute=minutes, second=0, microsecond=0)
    return dt.isoformat(timespec="seconds")


def seed_metrics(db_path):
    init_intel_tables(db_path)
    # memeistan: 6 posts, mixed hours/reach
    pulse.record_metric(db_path, "memeistan", "mem-a", _iso(18), 400, 200, 100, 10000)
    pulse.record_metric(db_path, "memeistan", "mem-b", _iso(18), 350, 150, 80, 9000)
    pulse.record_metric(db_path, "memeistan", "mem-c", _iso(9), 100, 40, 20, 4000)
    pulse.record_metric(db_path, "memeistan", "mem-d", _iso(10), 90, 30, 15, 3500)
    pulse.record_metric(db_path, "memeistan", "mem-e", _iso(20), 200, 80, 40, 6000)
    pulse.record_metric(db_path, "memeistan", "mem-f", _iso(8), 70, 20, 10, 3000)
    # deen: 2 posts
    pulse.record_metric(db_path, "deen", "deen-1", _iso(12), 200, 70, 30, 5000)
    pulse.record_metric(db_path, "deen", "deen-2", _iso(14), 170, 60, 20, 4500)


def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    ideas_db.init_db(db_path)
    seed_metrics(db_path)

    # ---- pulse.record_metric
    rid = pulse.record_metric(db_path, "maloomat", "mal-x", _iso(16),
                              10, 5, 2, 1000)
    assert isinstance(rid, int) and rid > 0, "record_metric must return row id"
    try:
        pulse.record_metric(db_path, "nope", "x", _iso(), 1, 1, 1, 1)
        assert False, "bad niche should raise"
    except ValueError:
        pass

    # ---- pulse.import_csv
    csv_text = (
        "niche,post_id,posted_at,likes,shares,comments,reach\n"
        "memeistan,mem-csv,{},80,20,10,2500\n"
        "badniche,bad-1,{},10,5,2,500\n"
        "memeistan,bad-2,{},notanum,5,2,500\n"
    ).format(_iso(21), _iso(21), _iso(21))
    assert pulse.import_csv(db_path, csv_text) == 1, "import skips bad rows"
    try:
        pulse.import_csv(db_path, "niche,post_id\nx,y\n")
        assert False, "bad header should raise"
    except ValueError:
        pass

    # ---- pulse.summary
    s = pulse.summary(db_path, "memeistan")["memeistan"]
    assert s["posts"] == 7, s
    assert s["total_likes"] == 1290, s
    assert s["total_shares"] == 540, s
    assert s["total_comments"] == 275, s
    assert abs(s["avg_reach"] - 38000 / 7) < 0.01, s
    assert s["best_post"] == {"post_id": "mem-a", "engagement": 700}, s
    assert s["worst_post"] == {"post_id": "mem-f", "engagement": 100}, s
    assert s["best_hour"] == 18, s
    assert "18:00" in s["insight"], s["insight"]
    assert "morning" in s["insight"], s["insight"]
    assert "2.7x" in s["insight"], s["insight"]

    all_s = pulse.summary(db_path)
    assert "memeistan" in all_s and "deen" in all_s, all_s.keys()
    deen_s = pulse.summary(db_path, "deen")["deen"]
    assert deen_s["posts"] == 2, deen_s
    assert deen_s["insight"] == pulse.INSUFFICIENT_DATA, deen_s["insight"]
    try:
        pulse.summary(db_path, "nope")
        assert False, "bad niche should raise"
    except ValueError:
        pass

    # ---- feedback: scoring with data
    ok, _ = ideas_db.add_idea(db_path, "memeistan",
                              "funniest cat fails caught on camera 2025",
                              "clip ideas")
    assert ok
    ok, _ = ideas_db.add_idea(db_path, "deen",
                              "daily seerah quiz number 12 for students",
                              "quiz detail")
    assert ok
    idea_a = ideas_db.list_ideas(db_path, niche="memeistan")[0]
    # score a NEW idea (not yet stored): its title shares keywords with
    # memeistan's top posts' titles via the stored idea pool
    score, reason = feedback.score_idea(
        db_path, 9999,
        "what are the funniest cat fails of 2026 so far?", "detail",
        "memeistan")
    assert isinstance(score, float), type(score)
    assert 0.0 <= score <= 100.0
    # 50 base + 25 engagement (niche avg beats global avg) + 10 length
    # + 5 question + 5 digit + 5 keyword overlap, clamped
    assert score == 100.0, (score, reason)
    assert reason, "reason must be non-empty"

    # ---- feedback: cold start (no metrics at all)
    tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp2.close()
    db2 = tmp2.name
    init_intel_tables(db2)
    cscore, creason = feedback.score_idea(
        db2, 999, "Why is the sky blue on a clear day?", "", "techsathi")
    assert cscore == 55.0, (cscore, creason)  # 50 + 5 question only
    assert "cold start" in creason.lower(), creason

    # ---- feedback.refresh_scores
    n = feedback.refresh_scores(db_path)
    assert n == 2, n
    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT idea_id, score, reason FROM idea_scores").fetchall()
    assert len(rows) == 2, rows
    assert all(r[1] >= 0 and r[2] for r in rows), rows
    conn.close()

    # ---- shadow: stable niche stays quiet
    mres = shadow.check(db_path, "memeistan")
    assert mres["alert"] is False, mres
    assert mres["median_reach"] == 4000, mres
    assert mres["current_reach"] == 2500, mres  # mem-csv at 21:00
    assert mres["drop_pct"] == 37.5, mres
    conn = sqlite3.connect(db_path)
    alerts = conn.execute("SELECT COUNT(*) c FROM shadow_alerts").fetchone()[0]
    assert alerts == 0, "stable niche must not insert alerts"
    conn.close()

    # ---- shadow: planted drop triggers alert
    for i in range(6):
        pulse.record_metric(db_path, "deen", "deen-old-%d" % i,
                            _iso(12, days_ago=2 + (i % 3)),
                            150, 40, 10, 5000)
    pulse.record_metric(db_path, "deen", "deen-drop", _iso(23),
                        70, 20, 10, 500)
    dres = shadow.check(db_path, "deen")
    assert dres["alert"] is True, dres
    assert dres["median_reach"] == 5000, dres
    assert dres["current_reach"] == 500, dres
    assert dres["drop_pct"] == 90.0, dres
    assert "possible restriction — check manually" in dres["message"], \
        dres["message"]
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT niche, median_reach, current_reach, status FROM shadow_alerts"
    ).fetchall()
    assert len(rows) == 1 and rows[0][0] == "deen" and rows[0][3] == "new", rows
    assert rows[0][1] == 5000 and rows[0][2] == 500, rows
    conn.close()

    # ---- shadow: insufficient data
    nores = shadow.check(db2, "techsathi")
    assert nores["status"] == "ok-no-data", nores
    try:
        shadow.check(db_path, "nope")
        assert False, "bad niche should raise"
    except ValueError:
        pass

    # ---- health: fixtures
    schedule.init_schedule_tables(db_path)
    conn = sqlite3.connect(db_path)
    for i in range(10):
        slot = (NOW - timedelta(hours=i)).isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO scheduled_posts (idea_id, niche, slot_utc, status,"
            " created_at) VALUES (1, 'memeistan', ?, 'scheduled', ?)",
            (slot, NOW.isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    # deen prior data (20 days ago) for trend comparison
    pulse.record_metric(db_path, "deen", "deen-p1", _iso(12, days_ago=20),
                        80, 30, 10, 3000)
    pulse.record_metric(db_path, "deen", "deen-p2", _iso(13, days_ago=20),
                        90, 20, 10, 3200)

    hscore, detail = health.compute_health(db_path, "memeistan")
    # consistency 10/35*40 = 11.43; trend 35 (no prior data, recent>0);
    # freshness 25 (ideas added just now)
    assert hscore == 71, (hscore, detail)
    assert detail["flags"] == [], detail
    assert detail["scheduled_7d"] == 10, detail
    assert detail["consistency_pts"] == 11.43, detail
    assert detail["trend_pts"] == 35.0, detail
    assert detail["freshness_pts"] == 25.0, detail

    dscore, ddetail = health.compute_health(db_path, "deen")
    # recent avg 205.56 vs prior avg 150 -> capped ratio 1.5 -> trend 35
    assert ddetail["trend_pts"] == 35.0, ddetail
    assert dscore == 60, (dscore, ddetail)
    assert ddetail["flags"] == ["quiet"], ddetail

    wscore, wdetail = health.compute_health(db_path, "wicketverse")
    assert wscore == 18, (wscore, wdetail)  # 0 + 17.5 + 0
    assert wdetail["flags"] == ["needs attention", "quiet", "no data"], \
        wdetail
    try:
        health.compute_health(db_path, "nope")
        assert False, "bad niche should raise"
    except ValueError:
        pass

    # ---- health.refresh_all
    all_health = health.refresh_all(db_path)
    assert set(all_health.keys()) == set(ideas_db.NICHE_IDS), all_health.keys()
    assert all_health["memeistan"] == 71, all_health
    assert all(isinstance(v, int) and 0 <= v <= 100
               for v in all_health.values()), all_health
    conn = sqlite3.connect(db_path)
    nrows = conn.execute("SELECT COUNT(*) c FROM niche_health").fetchone()[0]
    assert nrows == len(ideas_db.NICHE_IDS), nrows
    conn.close()

    print("ALL INTEL METRICS TESTS PASSED")


if __name__ == "__main__":
    main()
