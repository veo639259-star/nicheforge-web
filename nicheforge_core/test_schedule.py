"""Tests for NicheForge schedule.py (Slot Planner + Clash Detector).

Seeds a tmp DB with approved ideas for 3 niches, plans a day, asserts the
window and both gap rules, then manually inserts two clashing rows and
asserts detect_clashes finds exactly one clash.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db as ideas_db
import schedule

PKT = ZoneInfo("Asia/Karachi")
DATE = "2026-10-16"
NICHES = ["deen", "maloomat", "paheli"]


def seed(db_path):
    ideas_db.init_db(db_path)
    idea_ids = []
    for nch in NICHES:
        for i in range(4):
            ok, info = ideas_db.add_idea(
                db_path, nch, "post {} for {}".format(i, nch), "detail")
            assert ok, info
            idea_ids.append(int(info.split("#")[1].split()[0]))
    for iid in idea_ids:
        assert ideas_db.set_status(db_path, iid, "approved")
    return idea_ids


def test_plan_and_clashes():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "nicheforge-test.db")
        seed(db_path)

        result = schedule.plan_day(db_path, DATE)
        assert set(result) == {"placed", "unplaced"}, result.keys()

        # Everything should fit: 12 ideas, 145 slots, gaps allow ~30 posts.
        assert result["unplaced"] == [], result["unplaced"]
        assert len(result["placed"]) == 12

        # All placed inside 09:00-21:00 PKT.
        for p in result["placed"]:
            local = datetime.fromisoformat(p["slot_pkt"])
            assert local.hour * 60 + local.minute >= 9 * 60, p
            assert local.hour * 60 + local.minute <= 21 * 60, p

        # Per-niche gaps >= 90 min.
        by_niche = {}
        for p in result["placed"]:
            by_niche.setdefault(p["niche"], []).append(
                datetime.fromisoformat(p["slot_pkt"]))
        for nch, times in by_niche.items():
            times.sort()
            assert nch in NICHES
            for a, b in zip(times, times[1:]):
                gap = (b - a).total_seconds() / 60.0
                assert gap >= 90.0, (nch, a, b, gap)

        # Global gaps >= 30 min.
        all_times = sorted(datetime.fromisoformat(p["slot_pkt"])
                           for p in result["placed"])
        for a, b in zip(all_times, all_times[1:]):
            gap = (b - a).total_seconds() / 60.0
            assert gap >= 30.0, (a, b, gap)

        # Round-robin: first three placements follow alphabetical niche order.
        first_three = [p["niche"] for p in result["placed"][:3]]
        assert first_three == sorted(NICHES), first_three

        # No clashes after planning.
        assert schedule.detect_clashes(db_path, DATE) == []

        # list_schedule agrees and exposes slot_pkt.
        rows = schedule.list_schedule(db_path, DATE)
        assert len(rows) == 12
        assert [r["slot_pkt"] for r in rows] == sorted(
            r["slot_pkt"] for r in rows)
        assert all(r["status"] == "scheduled" for r in rows)

        # Clear the day, then insert two clashing rows (10:00 and 10:15 PKT)
        # so the clash count is exact.
        assert schedule.clear_day(db_path, DATE) == 12
        t0 = datetime(2026, 10, 16, 10, 0, tzinfo=PKT).astimezone(timezone.utc)
        conn = schedule._connect(db_path)
        try:
            conn.execute(
                "INSERT INTO scheduled_posts (idea_id, niche, slot_utc,"
                " status, created_at) VALUES (?, ?, ?, 'scheduled', ?)",
                (9998, "deen", t0.isoformat(timespec="seconds"),
                 schedule.utc_now()))
            conn.execute(
                "INSERT INTO scheduled_posts (idea_id, niche, slot_utc,"
                " status, created_at) VALUES (?, ?, ?, 'scheduled', ?)",
                (9999, "paheli", (t0 + timedelta(minutes=15))
                 .isoformat(timespec="seconds"), schedule.utc_now()))
            conn.commit()
        finally:
            conn.close()

        clashes = schedule.detect_clashes(db_path, DATE)
        assert len(clashes) == 1, clashes
        c = clashes[0]
        assert {c["a_niche"], c["b_niche"]} == {"deen", "paheli"}, c
        assert c["gap_min"] == 15.0, c

        # Without date filter the clash is still found.
        assert len(schedule.detect_clashes(db_path)) >= 1

        # clear_day wipes the day's rows; re-plan works from scratch.
        deleted = schedule.clear_day(db_path, DATE)
        assert deleted == 2, deleted
        assert schedule.list_schedule(db_path, DATE) == []
        result2 = schedule.plan_day(db_path, DATE)
        assert len(result2["placed"]) == 12, result2
        assert result2["unplaced"] == []
        assert schedule.detect_clashes(db_path, DATE) == []

        # Explicit ideas are honoured; already-scheduled ones are skipped.
        r = schedule.plan_day(db_path, DATE,
                              ideas=[{"id": 7777, "niche": "deen"}])
        assert len(r["placed"]) == 1 and r["unplaced"] == [], r
        r = schedule.plan_day(db_path, DATE,
                              ideas=[{"id": 7777, "niche": "deen"}])
        assert r == {"placed": [], "unplaced": []}, r  # skipped: already set


def test_empty_day():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "nicheforge-empty.db")
        schedule.init_schedule_tables(db_path)
        assert schedule.plan_day(db_path, DATE) == {"placed": [],
                                                    "unplaced": []}
        assert schedule.detect_clashes(db_path, DATE) == []
        assert schedule.list_schedule(db_path, DATE) == []
        assert schedule.clear_day(db_path, DATE) == 0


if __name__ == "__main__":
    test_plan_and_clashes()
    test_empty_day()
    print("ALL SCHEDULE TESTS PASSED")
