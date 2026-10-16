"""Tests for offline.py (Phase-5 Offline Queue).

All work is local SQLite — no network. Failed rows must stay visible;
only old done rows may be purged.
"""
import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import offline  # noqa: E402

_passed = 0


def check(name, fn):
    global _passed
    try:
        fn()
    except Exception as exc:
        print("FAIL - %s: %r" % (name, exc))
        raise SystemExit(1)
    _passed += 1
    print("ok - %s" % name)


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    offline.init_offline_tables(path)
    return path


def test_queue_work_returns_id_and_lists_fifo():
    p = _fresh_db()
    id1 = offline.queue_work(p, "publish", {"niche": "deen"})
    id2 = offline.queue_work(p, "publish", {"niche": "lafz"})
    assert id1 > 0 and id2 == id1 + 1
    rows = offline.list_queue(p)
    assert [r["id"] for r in rows] == [id1, id2]
    assert all(r["status"] == "queued" for r in rows)
    assert json.loads(rows[0]["payload_json"]) == {"niche": "deen"}
    os.unlink(p)


def test_queue_work_rejects_non_dict_payload():
    p = _fresh_db()
    try:
        offline.queue_work(p, "publish", ["not", "a", "dict"])
    except TypeError:
        os.unlink(p)
        return
    raise AssertionError("TypeError not raised for non-dict payload")


def test_list_queue_status_filter():
    p = _fresh_db()
    offline.queue_work(p, "a", {"x": 1})
    offline.queue_work(p, "b", {"x": 2})
    offline.replay_queue(p, {"a": lambda pl: None})
    assert len(offline.list_queue(p, status="done")) == 1
    # "b" had no handler: recorded as a failed attempt -> retrying
    assert len(offline.list_queue(p, status="retrying")) == 1
    assert len(offline.list_queue(p, status="queued")) == 0
    assert len(offline.list_queue(p)) == 2
    try:
        offline.list_queue(p, status="bogus")
    except ValueError:
        os.unlink(p)
        return
    raise AssertionError("ValueError not raised for bogus status")


def test_replay_success_marks_done():
    p = _fresh_db()
    seen = []
    offline.queue_work(p, "publish", {"niche": "deen", "nested": [1, 2]})
    summary = offline.replay_queue(p, {"publish": lambda pl: seen.append(pl)})
    assert summary == {"done": 1, "failed": 0, "remaining": 0}
    assert seen == [{"niche": "deen", "nested": [1, 2]}]
    rows = offline.list_queue(p)
    assert rows[0]["status"] == "done" and rows[0]["attempts"] == 0
    os.unlink(p)


def test_replay_failure_retries_then_fails():
    p = _fresh_db()

    def boom(pl):
        raise RuntimeError("downstream exploded")

    offline.queue_work(p, "publish", {"niche": "deen"})
    s1 = offline.replay_queue(p, {"publish": boom}, max_attempts=3)
    assert s1 == {"done": 0, "failed": 0, "remaining": 1}
    row = offline.list_queue(p)[0]
    assert row["status"] == "retrying" and row["attempts"] == 1
    assert "downstream exploded" in row["last_error"]
    s2 = offline.replay_queue(p, {"publish": boom}, max_attempts=3)
    assert s2 == {"done": 0, "failed": 0, "remaining": 1}
    s3 = offline.replay_queue(p, {"publish": boom}, max_attempts=3)
    assert s3 == {"done": 0, "failed": 1, "remaining": 0}
    row = offline.list_queue(p)[0]
    assert row["status"] == "failed" and row["attempts"] == 3
    os.unlink(p)


def test_unknown_kind_counts_as_attempt():
    p = _fresh_db()
    offline.queue_work(p, "mystery", {"x": 1})
    s = offline.replay_queue(p, {}, max_attempts=1)
    assert s == {"done": 0, "failed": 1, "remaining": 0}
    row = offline.list_queue(p)[0]
    assert row["status"] == "failed"
    assert "no handler" in row["last_error"]
    os.unlink(p)


def test_last_error_truncated():
    p = _fresh_db()
    offline.queue_work(p, "publish", {})
    offline.replay_queue(p, {"publish": lambda pl: (_ for _ in ()).throw(
        RuntimeError("E" * 2000))}, max_attempts=1)
    row = offline.list_queue(p)[0]
    assert len(row["last_error"]) <= 500
    os.unlink(p)


def test_purge_done_keeps_failed_and_recent():
    p = _fresh_db()
    # one failed row (must survive)
    offline.queue_work(p, "publish", {"a": 1})
    offline.replay_queue(p, {"publish": lambda pl: 1 / 0}, max_attempts=1)
    # one old done row (must be purged)
    old_id = offline.queue_work(p, "publish", {"b": 2})
    offline.replay_queue(p, {"publish": lambda pl: None})
    conn = sqlite3.connect(p)
    try:
        conn.execute(
            "UPDATE offline_queue SET status = 'done',"
            " updated_at = datetime('now', '-40 days') WHERE id = ?", (old_id,))
        conn.commit()
    finally:
        conn.close()
    deleted = offline.purge_done(p, older_than_days=30)
    assert deleted == 1
    remaining = offline.list_queue(p)
    assert len(remaining) == 1
    assert remaining[0]["status"] == "failed"
    # recent done rows are not purged either
    offline.queue_work(p, "publish", {"c": 3})
    offline.replay_queue(p, {"publish": lambda pl: None})
    assert offline.purge_done(p, older_than_days=30) == 0
    os.unlink(p)


def test_mixed_batch_summary_fifo_order():
    p = _fresh_db()
    order = []
    offline.queue_work(p, "one", {"n": 1})
    offline.queue_work(p, "two", {"n": 2})
    offline.queue_work(p, "three", {"n": 3})
    handlers = {
        "one": lambda pl: order.append(("one", pl["n"])),
        "two": lambda pl: (_ for _ in ()).throw(ValueError("nope")),
        "three": lambda pl: order.append(("three", pl["n"])),
    }
    s = offline.replay_queue(p, handlers, max_attempts=5)
    assert s["done"] == 2 and s["failed"] == 0 and s["remaining"] == 1
    assert order == [("one", 1), ("three", 3)]  # FIFO preserved
    os.unlink(p)


if __name__ == "__main__":
    check("queue_work returns id, list_queue FIFO", test_queue_work_returns_id_and_lists_fifo)
    check("queue_work rejects non-dict payload", test_queue_work_rejects_non_dict_payload)
    check("list_queue status filter + validation", test_list_queue_status_filter)
    check("replay success marks done, payload intact", test_replay_success_marks_done)
    check("replay failure retries then fails", test_replay_failure_retries_then_fails)
    check("unknown kind counts as failed attempt", test_unknown_kind_counts_as_attempt)
    check("last_error truncated to 500 chars", test_last_error_truncated)
    check("purge_done: old done purged, failed/recent kept", test_purge_done_keeps_failed_and_recent)
    check("mixed batch summary + FIFO order", test_mixed_batch_summary_fifo_order)
    print("ALL %d CHECKS PASSED" % _passed)
