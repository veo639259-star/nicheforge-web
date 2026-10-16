"""Tests for reels.py (Phase 5).

ffmpeg-dependent build tests run only when ffmpeg is actually installed;
everything else runs without it.
"""
import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import reels  # noqa: E402

PASSED = 0


def check(name, fn):
    global PASSED
    try:
        fn()
    except Exception as exc:
        print("FAIL - {}: {!r}".format(name, exc))
        sys.exit(1)
    PASSED += 1
    print("ok - {}".format(name))


def _temp_db():
    return tempfile.mktemp(suffix=".db")


def _make_ppm(path, r, g, b, w=320, h=568):
    with open(path, "wb") as fh:
        fh.write("P6\n{} {}\n255\n".format(w, h).encode("ascii"))
        fh.write(bytes([r, g, b]) * (w * h))


def t_check_ffmpeg_returns_bool():
    res = reels.check_ffmpeg()
    assert isinstance(res, bool)
    assert res == (shutil.which("ffmpeg") is not None)


def t_init_tables_idempotent():
    db = _temp_db()
    try:
        reels.init_reel_tables(db)
        reels.init_reel_tables(db)
        conn = sqlite3.connect(db)
        try:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(reel_queue)").fetchall()]
        finally:
            conn.close()
        for col in ("niche", "image_paths_json", "caption", "status",
                    "out_path", "slot_note", "created_at"):
            assert col in cols, cols
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_queue_list_mark_flow():
    db = _temp_db()
    try:
        rid = reels.queue_reel(db, "pakwire", ["/tmp/a.jpg", "/tmp/b.jpg"],
                               "test caption")
        assert isinstance(rid, int) and rid > 0
        rows = reels.list_reels(db)
        assert len(rows) == 1
        assert rows[0]["niche"] == "pakwire"
        assert rows[0]["status"] == "queued"
        assert rows[0]["caption"] == "test caption"
        import json
        assert json.loads(rows[0]["image_paths_json"]) == ["/tmp/a.jpg",
                                                            "/tmp/b.jpg"]
        reels.mark_reel(db, rid, "building")
        assert reels.list_reels(db, status="building")[0]["id"] == rid
        reels.mark_reel(db, rid, "ready", out_path="/tmp/reel.mp4")
        row = reels.list_reels(db, niche="pakwire")[0]
        assert row["status"] == "ready" and row["out_path"] == "/tmp/reel.mp4"
        assert reels.list_reels(db, niche="other") == []
        assert reels.list_reels(db, status="failed") == []
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_mark_reel_invalid_status_raises():
    db = _temp_db()
    try:
        rid = reels.queue_reel(db, "deen", [])
        try:
            reels.mark_reel(db, rid, "exploding")
        except ValueError:
            return
        raise AssertionError("ValueError not raised for bad status")
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_schedule_reel_records_slot_note():
    db = _temp_db()
    try:
        rid = reels.queue_reel(db, "memeistan", [])
        reels.schedule_reel(db, rid, "2026-10-17 18:00 PKT slot")
        row = reels.list_reels(db)[0]
        assert row["slot_note"] == "2026-10-17 18:00 PKT slot", row
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_build_reel_raises_without_ffmpeg():
    orig = shutil.which
    shutil.which = lambda name: None
    try:
        try:
            reels.build_reel(["/tmp/a.jpg"], "cap", "/tmp/out.mp4")
        except RuntimeError as exc:
            assert "ffmpeg" in str(exc).lower(), exc
            return
        raise AssertionError("RuntimeError not raised without ffmpeg")
    finally:
        shutil.which = orig


def t_build_reel_requires_images():
    if not reels.check_ffmpeg():
        return  # covered by the missing-ffmpeg test above
    try:
        reels.build_reel([], "cap", "/tmp/out.mp4")
    except ValueError:
        return
    raise AssertionError("ValueError not raised for empty image list")


def t_build_reel_real():
    if not reels.check_ffmpeg():
        return "skipped: no ffmpeg"
    tmpdir = tempfile.mkdtemp()
    try:
        a = os.path.join(tmpdir, "a.ppm")
        b = os.path.join(tmpdir, "b.ppm")
        _make_ppm(a, 200, 30, 30)
        _make_ppm(b, 30, 30, 200)
        out = os.path.join(tmpdir, "reel.mp4")
        ret = reels.build_reel([a, b], "Test caption", out,
                               per_image_secs=1, max_total_secs=55)
        assert ret == out, ret
        assert os.path.isfile(out) and os.path.getsize(out) > 1000
        return ""
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    check("check_ffmpeg returns bool", t_check_ffmpeg_returns_bool)
    check("init_reel_tables is idempotent", t_init_tables_idempotent)
    check("queue/list/mark reel flow", t_queue_list_mark_flow)
    check("mark_reel rejects invalid status",
          t_mark_reel_invalid_status_raises)
    check("schedule_reel records slot note", t_schedule_reel_records_slot_note)
    check("build_reel raises RuntimeError without ffmpeg",
          t_build_reel_raises_without_ffmpeg)
    check("build_reel requires at least one image",
          t_build_reel_requires_images)
    note = t_build_reel_real()
    PASSED += 1
    print("ok - build_reel end-to-end render" +
          (" (" + note + ")" if note else ""))
    print("ALL {} CHECKS PASSED".format(PASSED))
