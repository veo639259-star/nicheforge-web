"""Tests for the NicheForge Phase 3 SAFETY CORE (browser_track).

mimic.py   — human delays in range, typing speed in cps range, TaskQueue
               strictly sequential (order + no timestamp overlap).
sentinel.py — rate-limit signals detected / clean text not, park expiry,
               next_available rotation.
guard.py    — captcha fixtures detected, clean page not, trip() pauses the
               profile + logs the event, human_resume() reactivates.

Plain asserts, temp DBs, no pytest. Run: python3 test_browser_safety.py
"""
import os
import sqlite3
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_track import mimic, sentinel, guard, profiles

TINY = mimic.MimicConfig(
    action_delay_min=0.001,
    action_delay_max=0.002,
    typing_cps_min=50.0,
    typing_cps_max=100.0,
    inter_task_gap_min=0.0,
    inter_task_gap_max=0.0,
    mouse_jitter=False,
)


def fresh_db():
    tmp = tempfile.mkdtemp()
    return os.path.join(tmp, "safety-test.db")


# ---------------------------------------------------------------- mimic

def test_human_sleep_ranges():
    slept = []
    with mock.patch("time.sleep", lambda s: slept.append(s)):
        mimic.human_sleep(TINY, kind="action")
        assert 0.001 <= slept[-1] <= 0.002, slept[-1]
        mimic.human_sleep(TINY, kind="task_gap")
        assert 0.0 <= slept[-1] <= 0.0, slept[-1]
        # default kind is "action"
        mimic.human_sleep(TINY)
        assert 0.001 <= slept[-1] <= 0.002, slept[-1]
    for kind in ("bogus", "", None):
        try:
            mimic.human_sleep(TINY, kind=kind)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for kind=%r" % (kind,))
    print("ok human_sleep ranges")


def test_type_text_speed_and_dry_run():
    cfg = mimic.MimicConfig(typing_cps_min=4.0, typing_cps_max=9.0)

    class FakeDriver:
        def __init__(self):
            self.chars = []

        def type_char(self, c):
            self.chars.append(c)

    driver = FakeDriver()
    delays = []
    with mock.patch("time.sleep", lambda s: delays.append(s)):
        mimic.type_text(driver, "hello", cfg)
    assert driver.chars == list("hello"), driver.chars
    assert len(delays) == 5, delays
    for d in delays:  # 1/9 <= delay <= 1/4
        assert 1.0 / 9.0 - 1e-9 <= d <= 1.0 / 4.0 + 1e-9, d

    # dry_run: records what WOULD be typed, touches nothing
    driver2 = FakeDriver()
    with mock.patch("time.sleep") as slp:
        transcript = mimic.type_text(driver2, "hi", cfg, dry_run=True)
    assert driver2.chars == [], driver2.chars
    assert slp.call_count == 0
    assert [t["char"] for t in transcript] == ["h", "i"]
    for t in transcript:
        assert 1.0 / 9.0 - 1e-9 <= t["delay_secs"] <= 1.0 / 4.0 + 1e-9

    # driver with only type_text(s) also accepted
    class TextDriver:
        def __init__(self):
            self.got = None

        def type_text(self, s):
            self.got = s

    td = TextDriver()
    with mock.patch("time.sleep"):
        mimic.type_text(td, "abc", cfg)
    assert td.got == "abc"

    # driver with neither method -> TypeError
    try:
        mimic.type_text(object(), "x", cfg)
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError for bad driver")
    print("ok type_text speed + dry_run")


def test_random_mouse_move_dry_run():
    class Mouse:
        def __init__(self):
            self.points = []

        def move_to(self, x, y):
            self.points.append((x, y))

    m = Mouse()
    path = mimic.random_mouse_move(m, TINY, dry_run=True)
    assert m.points == [], m.points
    assert len(path) == 1 and len(path[0]) == 2  # jitter off -> single target
    (x, y) = path[0]
    assert 0 <= x <= 1366 and 0 <= y <= 900, path

    cfg_j = mimic.MimicConfig(mouse_jitter=True)
    path2 = mimic.random_mouse_move(m, cfg_j, dry_run=True)
    assert 3 <= len(path2) <= 5, path2  # 2-4 jitter steps + target

    with mock.patch("time.sleep"):
        mimic.random_mouse_move(m, TINY)
    assert len(m.points) == 1

    try:
        mimic.random_mouse_move(object(), TINY)
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError for bad mouse driver")
    print("ok random_mouse_move")


def test_task_queue_sequential():
    db_path = fresh_db()
    q = mimic.TaskQueue(db_path, cfg=TINY)
    events = []  # (label, "start"/"end", time.time())

    def make(label):
        def _fn():
            events.append((label, "start", time.time()))
            time.sleep(0.01)
            events.append((label, "end", time.time()))

        return _fn

    assert q.submit("task-1", make(1)) == 1
    assert q.submit("task-2", make(2)) == 2
    assert q.submit("task-3", make(3)) == 3
    assert q.pending_count() == 3
    results = q.run_all()
    assert [r["status"] for r in results] == ["done", "done", "done"], results
    assert q.pending_count() == 0

    # execution order 1,2,3
    starts = [e[0] for e in events if e[1] == "start"]
    assert starts == [1, 2, 3], events

    # no timestamp overlap: each task ends before the next starts
    by_label = {}
    for label, kind, ts in events:
        by_label.setdefault(label, {})[kind] = ts
    for a, b in ((1, 2), (2, 3)):
        assert by_label[a]["end"] <= by_label[b]["start"], (a, b, by_label)

    # DB log: 3 rows, all done, labels in order
    rows = mimic.list_tasks(db_path)
    assert [r["label"] for r in rows] == ["task-1", "task-2", "task-3"], rows
    assert all(r["status"] == "done" for r in rows), rows
    assert all(r["started_at"] and r["ended_at"] for r in rows), rows
    print("ok TaskQueue sequential")


def test_task_queue_failure_and_reentry():
    db_path = fresh_db()
    q = mimic.TaskQueue(db_path, cfg=TINY)
    ran = []

    def boom():
        raise RuntimeError("kaboom")

    def fine():
        ran.append("fine")

    def reenter():
        q.run_all()  # must raise RuntimeError, never deadlock

    q.submit("boom", boom)
    q.submit("fine", fine)
    q.submit("reenter", reenter)
    results = q.run_all()
    assert results[0]["status"] == "failed" and "kaboom" in results[0]["error"], results
    assert results[1]["status"] == "done" and ran == ["fine"], results
    assert results[2]["status"] == "failed", results
    assert "already running" in results[2]["error"], results[2]
    # queue usable again afterwards
    q.submit("after", fine)
    assert q.run_all()[0]["status"] == "done"
    rows = mimic.list_tasks(db_path)
    assert [r["status"] for r in rows] == ["failed", "done", "failed", "done"], rows
    print("ok TaskQueue failure + re-entry guard")


# ---------------------------------------------------------------- sentinel

def test_sentinel_check_text():
    hit = sentinel.check_text("You've reached your limit, try again later")
    assert hit is not None, "limit fixture missed"
    assert hit["signal"] in sentinel.LIMIT_SIGNALS, hit
    assert hit["cooldown_secs"] == 3600, hit

    hit429 = sentinel.check_text("Error 429 from the server")
    assert hit429 is not None and hit429["signal"] == "HTTP 429", hit429

    for negative in ("hello world", "unlimited plan", "", None, "welcome back"):
        assert sentinel.check_text(negative) is None, negative

    assert sentinel.check_status_code(429)["signal"] == "HTTP 429"
    assert sentinel.check_status_code("429")["signal"] == "HTTP 429"
    assert sentinel.check_status_code(200) is None
    assert sentinel.check_status_code(500) is None
    print("ok sentinel check_text / check_status_code")


def test_sentinel_tracker():
    db_path = fresh_db()
    t = sentinel.RateLimitTracker(db_path)
    emails = ["a@x.com", "b@x.com", "c@x.com"]

    assert t.next_available("chatgpt", emails) == "a@x.com"
    assert not t.is_parked("chatgpt", "a@x.com")

    t.park("chatgpt", "a@x.com", "rate limit", cooldown_secs=3600)
    assert t.is_parked("chatgpt", "a@x.com")
    assert not t.is_parked("chatgpt", "b@x.com")
    assert t.next_available("chatgpt", emails) == "b@x.com"

    # expired park (negative cooldown) auto-expires on read
    t.park("chatgpt", "b@x.com", "old", cooldown_secs=-10)
    assert not t.is_parked("chatgpt", "b@x.com")
    assert t.next_available("chatgpt", emails) == "b@x.com"

    parks = t.list_parks()
    assert [p["email"] for p in parks] == ["a@x.com"], parks
    assert parks[0]["reason"] == "rate limit" and parks[0]["service"] == "chatgpt"

    # park everything -> nothing available
    t.park("chatgpt", "b@x.com", "x", cooldown_secs=3600)
    t.park("chatgpt", "c@x.com", "x", cooldown_secs=3600)
    assert t.next_available("chatgpt", emails) is None
    print("ok sentinel RateLimitTracker")


# ---------------------------------------------------------------- guard

def test_guard_scan():
    captcha_html = (
        "<html><body><div>Please complete the captcha to continue. "
        "Verify you are human.</div></body></html>"
    )
    hits = guard.scan(captcha_html)
    assert "captcha" in hits and "verify you are human" in hits, hits

    assert guard.scan("<div>Welcome back, here is your dashboard</div>") == []
    assert guard.scan("") == [] and guard.scan(None) == []
    # case-insensitive
    assert "account suspended" in guard.scan("ACCOUNT SUSPENDED for policy reasons")
    print("ok guard scan")


def test_guard_trip_and_resume():
    db_path = fresh_db()
    profiles.init_profile_tables(db_path)
    profiles.register_profile(db_path, "deen", "chatgpt", "a@x.com")
    g = guard.BlockGuard(db_path)

    alert = g.trip("deen", "chatgpt", "a@x.com", "captcha")
    assert alert["level"] == "critical", alert
    assert "captcha" in alert["message"] and "human_resume" in alert["message"], alert

    # profile paused: not returned as active anymore
    assert profiles.get_profile(db_path, "deen", "chatgpt", email="a@x.com") is None
    prof = [p for p in profiles.list_profiles(db_path) if p["email"] == "a@x.com"][0]
    assert prof["status"] == "paused", prof

    # block event logged
    events = g.recent_events(niche="deen")
    assert any(e["kind"] == "block" and "captcha" in e["detail"] for e in events), events

    # only explicit human resume reactivates
    assert g.human_resume("deen", "chatgpt", "a@x.com") is True
    back = profiles.get_profile(db_path, "deen", "chatgpt", email="a@x.com")
    assert back is not None and back["status"] == "active", back
    events = g.recent_events(niche="deen")
    assert any(e["kind"] == "resume" for e in events), events

    # resume of a nonexistent profile is a no-op
    assert g.human_resume("deen", "chatgpt", "ghost@x.com") is False
    print("ok guard trip + human_resume")


def test_guard_trip_unknown_profile():
    # defensive: tripping a profile row that was never registered still
    # pauses it (created already paused) so no runner can pick it up.
    db_path = fresh_db()
    g = guard.BlockGuard(db_path)
    alert = g.trip("paheli", "claude", "new@x.com", "unusual activity")
    assert alert["level"] == "critical"
    prof = [p for p in profiles.list_profiles(db_path) if p["email"] == "new@x.com"][0]
    assert prof["status"] == "paused", prof
    print("ok guard trip on unregistered profile")


if __name__ == "__main__":
    test_human_sleep_ranges()
    test_type_text_speed_and_dry_run()
    test_random_mouse_move_dry_run()
    test_task_queue_sequential()
    test_task_queue_failure_and_reentry()
    test_sentinel_check_text()
    test_sentinel_tracker()
    test_guard_scan()
    test_guard_trip_and_resume()
    test_guard_trip_unknown_profile()
    print("\nALL BROWSER SAFETY TESTS PASSED (10)")
