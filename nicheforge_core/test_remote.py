"""Tests for remote.py (Phase-5 WhatsApp Remote command protocol).

No real WhatsApp connection is used — all state moves through wa_inbox /
wa_outbox / remote_pauses tables in a throwaway SQLite file.
"""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import db  # noqa: E402
import remote  # noqa: E402

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
    db.init_db(path)          # Phase-1 tables (ideas + usage)
    remote.init_remote_tables(path)
    return path


def _inbox_rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM wa_inbox").fetchall()]
    finally:
        conn.close()


def _add_id(db_path, niche, title):
    """add_idea returns (ok, info); extract the new row id via list_ideas."""
    ok, info = db.add_idea(db_path, niche, title)
    assert ok, info
    return db.list_ideas(db_path, niche=niche, status="pending")[0]["id"]
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM wa_inbox").fetchall()]
    finally:
        conn.close()


def test_parse_command_basic():
    assert remote.parse_command("APPROVE 12") == ("APPROVE", ["12"])
    assert remote.parse_command("status") == ("STATUS", [])
    assert remote.parse_command("  Pause   deen  ") == ("PAUSE", ["deen"])


def test_parse_command_empty_is_help():
    assert remote.parse_command("") == ("HELP", [])
    assert remote.parse_command("   ") == ("HELP", [])


def test_parse_command_unknown_keeps_token():
    assert remote.parse_command("FOOBAR x y") == ("FOOBAR", ["x", "y"])


def test_webhook_ingest_stages_message():
    p = _fresh_db()
    row_id = remote.webhook_ingest(p, "+923001234567", "STATUS")
    assert row_id > 0
    rows = _inbox_rows(p)
    assert len(rows) == 1
    assert rows[0]["sender"] == "+923001234567"
    assert rows[0]["body"] == "STATUS"
    assert rows[0]["processed"] == 0
    os.unlink(p)


def test_process_status_writes_reply():
    p = _fresh_db()
    remote.webhook_ingest(p, "me", "STATUS")
    n = remote.process_inbox(p, remote.default_handlers())
    assert n == 1
    pending = remote.get_outbox_pending(p)
    assert len(pending) == 1
    assert pending[0]["recipient"] == "me"
    assert "Pending approvals" in pending[0]["body"]
    assert "AI allowed" in pending[0]["body"]
    # row is marked processed — a second pass does nothing
    assert remote.process_inbox(p, remote.default_handlers()) == 0
    os.unlink(p)


def test_approve_flow():
    p = _fresh_db()
    idea_id = _add_id(p, "deen", "Test wazaif idea")
    remote.webhook_ingest(p, "me", "approve %d" % idea_id)
    remote.process_inbox(p, remote.default_handlers())
    ideas = db.list_ideas(p, status="approved")
    assert any(i["id"] == idea_id for i in ideas)
    reply = remote.get_outbox_pending(p)[0]["body"]
    assert "Approved idea #%d" % idea_id in reply
    os.unlink(p)


def test_reject_flow_and_unknown_id():
    p = _fresh_db()
    idea_id = _add_id(p, "pakwire", "Reject me please")
    remote.webhook_ingest(p, "me", "REJECT %d" % idea_id)
    remote.webhook_ingest(p, "me", "APPROVE 999999")
    remote.process_inbox(p, remote.default_handlers())
    assert any(i["id"] == idea_id for i in db.list_ideas(p, status="rejected"))
    replies = [r["body"] for r in remote.get_outbox_pending(p)]
    assert any("Rejected idea #%d" % idea_id in r for r in replies)
    assert any("No idea with id 999999" in r for r in replies)
    os.unlink(p)


def test_pause_resume_toggle():
    p = _fresh_db()
    remote.webhook_ingest(p, "me", "PAUSE deen")
    remote.process_inbox(p, remote.default_handlers())
    assert remote.is_niche_paused(p, "deen") is True
    reply = remote.get_outbox_pending(p)[-1]["body"]
    assert "Paused posting for niche 'deen'" in reply
    remote.webhook_ingest(p, "me", "resume DEEN")
    remote.process_inbox(p, remote.default_handlers())
    assert remote.is_niche_paused(p, "deen") is False
    os.unlink(p)


def test_pause_unknown_niche_rejected():
    p = _fresh_db()
    remote.webhook_ingest(p, "me", "PAUSE nosuchniche")
    remote.process_inbox(p, remote.default_handlers())
    assert remote.is_niche_paused(p, "nosuchniche") is False
    reply = remote.get_outbox_pending(p)[-1]["body"]
    assert "Unknown niche" in reply
    os.unlink(p)


def test_unknown_command_gets_help():
    p = _fresh_db()
    remote.webhook_ingest(p, "me", "BLASTOFF")
    remote.process_inbox(p, remote.default_handlers())
    reply = remote.get_outbox_pending(p)[-1]["body"]
    assert "remote commands" in reply
    assert "APPROVE <idea_id>" in reply
    os.unlink(p)


def test_queue_lists_pending():
    p = _fresh_db()
    id1 = _add_id(p, "wicketverse", "Cricket fact idea number one")
    _add_id(p, "lafz", "A quote idea for lafz")
    db.set_status(p, id1, "approved")  # not pending any more
    remote.webhook_ingest(p, "me", "QUEUE")
    remote.process_inbox(p, remote.default_handlers())
    reply = remote.get_outbox_pending(p)[-1]["body"]
    assert "Pending approvals (1)" in reply
    assert "A quote idea for lafz" in reply
    assert "Cricket fact idea" not in reply
    os.unlink(p)


def test_outbox_pending_and_sent():
    p = _fresh_db()
    remote.webhook_ingest(p, "me", "HELP")
    remote.process_inbox(p, remote.default_handlers())
    pending = remote.get_outbox_pending(p)
    assert len(pending) == 1
    assert remote.mark_outbox_sent(p, pending[0]["id"]) is True
    assert remote.get_outbox_pending(p) == []
    assert remote.mark_outbox_sent(p, 424242) is False
    os.unlink(p)


def test_handler_exception_becomes_reply():
    p = _fresh_db()

    def boom(db_path, args):
        raise RuntimeError("kaboom")

    remote.webhook_ingest(p, "me", "BOOM")
    n = remote.process_inbox(p, {"BOOM": boom, "HELP": remote.default_handlers()["HELP"]})
    assert n == 1
    reply = remote.get_outbox_pending(p)[-1]["body"]
    assert "Error processing" in reply and "kaboom" in reply
    os.unlink(p)


if __name__ == "__main__":
    check("parse_command basic forms", test_parse_command_basic)
    check("parse_command empty input is HELP", test_parse_command_empty_is_help)
    check("parse_command unknown keeps token", test_parse_command_unknown_keeps_token)
    check("webhook_ingest stages unprocessed message", test_webhook_ingest_stages_message)
    check("process_inbox STATUS writes outbox reply", test_process_status_writes_reply)
    check("APPROVE flow approves idea + replies", test_approve_flow)
    check("REJECT flow and unknown id", test_reject_flow_and_unknown_id)
    check("PAUSE/RESUME toggle niche flag", test_pause_resume_toggle)
    check("PAUSE unknown niche rejected", test_pause_unknown_niche_rejected)
    check("unknown command falls back to HELP", test_unknown_command_gets_help)
    check("QUEUE lists only pending ideas", test_queue_lists_pending)
    check("get_outbox_pending / mark_outbox_sent", test_outbox_pending_and_sent)
    check("handler exception becomes error reply", test_handler_exception_becomes_reply)
    print("ALL %d CHECKS PASSED" % _passed)
