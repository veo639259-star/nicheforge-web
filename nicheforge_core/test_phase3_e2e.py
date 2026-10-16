#!/usr/bin/env python3
"""NicheForge Phase 3 end-to-end dry-run test.

Exercises the whole browser track without touching the network or a real
browser: profiles -> image queue (MockDriver) -> contact sheet -> pick,
paste points, harvest dry-run, sentinel parking + rotation, guard trip +
human resume, stealth window math.

Run:  python3 test_phase3_e2e.py
Plain asserts — no pytest dependency.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_track import profiles, sessions, mimic, sentinel, guard, stealth
from browser_track import images, paste_points, harvest

PASS = 0


def check(name, condition):
    global PASS
    assert condition, "FAIL: " + name
    PASS += 1
    print("ok - " + name)


def main():
    tmp = tempfile.mkdtemp(prefix="nf3e2e_")
    db_path = os.path.join(tmp, "e2e.db")
    root = os.path.join(tmp, "ws")
    os.makedirs(root, exist_ok=True)

    # --- 1. profiles + rotation -------------------------------------------
    profiles.init_profile_tables(db_path)
    cfg = {"browser_accounts": {"chatgpt": ["a@x.com", "b@x.com"],
                                "claude": [], "gemini": ["g@x.com"]}}
    rows = profiles.sync_accounts_from_config(db_path, cfg, "memeistan")
    check("sync registers 3 profiles", len(rows) == 3)
    rows2 = profiles.sync_accounts_from_config(db_path, cfg, "memeistan")
    check("sync idempotent", len(profiles.list_profiles(db_path)) == 3)

    tracker = sentinel.RateLimitTracker(db_path)
    parked = tracker.park("chatgpt", "a@x.com", "test limit", cooldown_secs=3600)
    check("park returns until ts", bool(parked))
    check("is_parked true", tracker.is_parked("chatgpt", "a@x.com") is True)
    nxt = profiles.next_available_profile(
        db_path, "memeistan", "chatgpt", tracker.is_parked)
    check("rotation skips parked email", nxt and nxt["email"] == "b@x.com")

    # --- 2. guard trip + human resume --------------------------------------
    g = guard.BlockGuard(db_path)
    hits = guard.scan("<html>Please complete the captcha to continue</html>")
    check("captcha detected", len(hits) > 0)
    check("clean page not flagged",
          guard.scan("<html>hello world</html>") == [])
    alert = g.trip("memeistan", "chatgpt", "b@x.com", "captcha")
    check("trip returns critical alert", alert.get("level") == "critical")
    p = profiles.get_profile(db_path, "memeistan", "chatgpt", "b@x.com")
    check("tripped profile paused", p is None)  # get_profile: active only
    g.human_resume("memeistan", "chatgpt", "b@x.com")
    p2 = profiles.get_profile(db_path, "memeistan", "chatgpt", "b@x.com")
    check("human resume reactivates", p2 is not None)

    # --- 3. stealth window --------------------------------------------------
    pkt = stealth.PKT
    monday_10 = datetime(2026, 10, 19, 10, 0, tzinfo=pkt)  # a Monday
    check("10:00 Monday inside window",
          stealth.within_window(at=monday_10) is True)
    monday_3am = datetime(2026, 10, 19, 3, 0, tzinfo=pkt)
    check("03:00 refused", stealth.within_window(at=monday_3am) is False)
    friday_12 = datetime(2026, 10, 16, 12, 0, tzinfo=pkt)  # Friday = off-day
    check("Friday off-day refused",
          stealth.within_window(at=friday_12) is False)
    nxt_start = stealth.next_allowed_start(at=monday_3am, seed=7)
    check("next start in future", nxt_start > monday_3am)
    check("next start never round hour", nxt_start.minute != 0)
    check("next start not off-day", nxt_start.weekday() != 4)

    # --- 4. image queue dry-run --------------------------------------------
    images.init_image_tables(db_path)
    prompt_path = os.path.join(root, "prompt_42.json")
    with open(prompt_path, "w") as fh:
        json.dump({"prompt_text": "A desi meme visual, text-free",
                   "sections": {}}, fh)
    ids = images.queue_from_prompts(db_path, "memeistan", [prompt_path])
    check("job queued", len(ids) == 1)
    runner = images.ImageJobRunner(db_path, images.MockDriver(),
                                   dry_run=True, assets_root=root)
    res = runner.run_job(ids[0])
    check("dry-run job done", res[0] is True)
    jobs = images.list_jobs(db_path)
    check("job marked done", jobs[0]["status"] == "done")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = os.path.join(root, "niches", "memeistan", "assets", date)
    pngs = [f for f in os.listdir(day_dir) if f.endswith(".png")] \
        if os.path.isdir(day_dir) else []
    check("4 pngs downloaded", len(pngs) == 4)
    check("manifest written",
          os.path.isfile(os.path.join(day_dir, "manifest_%d.json" % ids[0])))
    sheet = images.build_contact_sheet(db_path, "memeistan", date, root=root)
    check("contact sheet built", os.path.isfile(sheet))
    images.record_pick(db_path, "memeistan", date,
                       os.path.join(day_dir, pngs[0]))
    strays = images.verify_no_strays("memeistan", root=root)
    check("no stray assets", strays == [])

    # --- 5. paste points ----------------------------------------------------
    paste_points.init_paste_tables(db_path)
    pid = paste_points.request(db_path, "Flow prompt", "https://flow.test/",
                               "paste the meme prompt")
    check("paste requested", isinstance(pid, int))
    check("pending count 1", paste_points.pending_count(db_path) == 1)
    nxt_pp = paste_points.next_pending(db_path)
    check("next pending is ours", nxt_pp and nxt_pp["id"] == pid)
    paste_points.complete(db_path, pid)
    check("completed -> 0 pending", paste_points.pending_count(db_path) == 0)

    # --- 6. harvest dry-run -------------------------------------------------
    harvest.init_harvest_tables(db_path)
    tid = harvest.add_target(db_path, "memeistan",
                             "https://example.com/rival", "rival page")
    check("target added", isinstance(tid, int))

    class DryDriver:
        def goto(self, url):
            pass

        def extract_posts(self):
            return [{"snippet": "sample", "likes": 5,
                     "comments_count": 1, "posted_at_text": "1h"}]

    out = harvest.run_harvest(db_path, DryDriver(), niche="memeistan",
                              dry_run=True, min_gap_secs=0)
    check("harvest visited 1", out["visited"] == 1)
    check("harvest stored 1", out["posts"] == 1)
    check("harvest not stopped", out["stopped"] is False)

    # --- 7. sessions --------------------------------------------------------
    check("logged-out detected",
          sessions.check_login("<button>Log in</button>", "chatgpt") is False)
    check("logged-in detected",
          sessions.check_login("<div id='chat'>hello</div>", "chatgpt") is True)
    sessions.mark_expired(db_path, "memeistan", "gemini", "g@x.com")
    rep = sessions.login_status_report(db_path)
    exp = [r for r in rep if r["email"] == "g@x.com"]
    check("expired in report", exp and exp[0]["status"] == "expired")

    # --- 8. mimic task queue ------------------------------------------------
    mimic.init_mimic_tables(db_path)
    order = []
    q = mimic.TaskQueue(db_path)
    for i in (1, 2, 3):
        q.submit("t%d" % i, (lambda i=i: order.append(i)))
    q.run_all()
    check("tasks ran in order", order == [1, 2, 3])

    print("\nE2E ALL PASS (%d checks)" % PASS)


if __name__ == "__main__":
    main()
