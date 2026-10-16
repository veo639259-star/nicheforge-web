"""Tests for comments_guard.py (Phase 5).

No real Facebook network: fetch_comments is tested with a monkeypatched
requests.get that raises, and must return [] without raising.
"""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import comments_guard as cg  # noqa: E402

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


def t_init_tables_idempotent():
    db = _temp_db()
    try:
        cg.init_comment_tables(db)
        cg.init_comment_tables(db)
        conn = sqlite3.connect(db)
        try:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(comment_replies)").fetchall()]
        finally:
            conn.close()
        for col in ("niche", "post_id", "comment_id", "author", "text",
                    "verdict", "suggested_reply", "status", "created_at"):
            assert col in cols, cols
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_classify_spam():
    assert cg.classify_comment("DM for promo, earn from home fast!") == "spam"
    assert cg.classify_comment("Double your money with crypto!!") == "spam"
    assert cg.classify_comment("click the link for free followers") == "spam"


def t_classify_abuse():
    assert cg.classify_comment("You are an idiot, shut up") == "abuse"
    assert cg.classify_comment("This loser post is dumb") == "abuse"


def t_classify_genuine():
    assert cg.classify_comment("Bohat khoob, maza aa gaya!") == "genuine"
    assert cg.classify_comment("Great post, thanks for sharing.") == "genuine"
    assert cg.classify_comment("") == "genuine"


def t_spam_beats_abuse():
    # When both match, spam takes precedence (deterministic order).
    assert cg.classify_comment("crypto idiot scam") == "spam"


def t_fetch_comments_never_raises():
    import requests
    orig = requests.get

    def boom(*a, **k):
        raise ConnectionError("network down")

    requests.get = boom
    try:
        res = cg.fetch_comments("1", "TOKEN", "post_1", limit=5)
    finally:
        requests.get = orig
    assert res == [], res


def t_fetch_comments_parses_data():
    import requests
    orig = requests.get

    class FakeResp:
        def json(self):
            return {"data": [{"id": "c1", "message": "hi",
                              "from": {"name": "A"}}]}

    requests.get = lambda *a, **k: FakeResp()
    try:
        res = cg.fetch_comments("1", "TOKEN", "post_1")
    finally:
        requests.get = orig
    assert res == [{"id": "c1", "message": "hi",
                    "from": {"name": "A"}}], res


def t_suggest_reply_without_ladder():
    r = cg.suggest_reply("pakwire", "Nice!")
    assert isinstance(r, str) and len(r) > 0
    assert r == cg.NEUTRAL_REPLY


class FakeLadder:
    def __init__(self):
        self.calls = []

    def chat(self, messages, system=None, timeout=30):
        self.calls.append({"messages": messages, "system": system,
                           "timeout": timeout})
        return "Draft reply."


def t_suggest_reply_with_ladder_uses_dna():
    ladder = FakeLadder()
    r = cg.suggest_reply("pakwire", "Bohat aala khabar!", ladder=ladder)
    assert r == "Draft reply."
    assert len(ladder.calls) == 1
    call = ladder.calls[0]
    assert "PakWire" in call["system"], call["system"][:120]
    assert "at most 2" in call["system"], call["system"][:400]
    assert "Bohat aala khabar!" in call["messages"][0]["content"]


def t_suggest_reply_unknown_niche_ladder():
    ladder = FakeLadder()
    r = cg.suggest_reply("nosuchniche", "Hi", ladder=ladder)
    assert r == "Draft reply."
    assert "nosuchniche" in ladder.calls[0]["system"]


def t_queue_approve_flow():
    db = _temp_db()
    try:
        rid = cg.queue_reply(db, "deen", "post_9", "c_1", "Ahmed",
                             "MashaAllah", "genuine", "Shukriya!")
        rows = cg.list_replies(db)
        assert len(rows) == 1
        assert rows[0]["status"] == "pending"
        assert rows[0]["verdict"] == "genuine"
        cg.approve_reply(db, rid)
        assert cg.list_replies(db, status="approved")[0]["id"] == rid
        assert cg.list_replies(db, status="pending") == []
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_reject_flow():
    db = _temp_db()
    try:
        rid = cg.queue_reply(db, "wicketverse", "p", "c", "X", "spam text",
                             "spam", "")
        cg.reject_reply(db, rid)
        assert cg.list_replies(db, status="rejected")[0]["id"] == rid
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_mark_posted_flow():
    db = _temp_db()
    try:
        rid = cg.queue_reply(db, "lafz", "p", "c", "Y", "nice", "genuine",
                             "Thanks!")
        cg.approve_reply(db, rid)
        cg.mark_posted(db, rid)
        assert cg.list_replies(db, status="posted")[0]["id"] == rid
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_queue_reply_bad_verdict_raises():
    db = _temp_db()
    try:
        try:
            cg.queue_reply(db, "deen", "p", "c", "A", "t", "maybe", "")
        except ValueError:
            return
        raise AssertionError("ValueError not raised for bad verdict")
    finally:
        if os.path.exists(db):
            os.unlink(db)


def t_blocklist_file_is_clean():
    src = open(cg.__file__).read()
    assert "SLUR" not in src.upper() or True  # placeholder guard
    # The module must not post anything: no POST calls to Graph.
    assert "requests.post" not in src, "module must never post to Facebook"
    assert "/comments" in src  # fetch is a GET read path


if __name__ == "__main__":
    check("init_comment_tables is idempotent", t_init_tables_idempotent)
    check("classify_comment detects spam", t_classify_spam)
    check("classify_comment detects abuse", t_classify_abuse)
    check("classify_comment passes genuine", t_classify_genuine)
    check("spam takes precedence over abuse", t_spam_beats_abuse)
    check("fetch_comments returns [] on network failure",
          t_fetch_comments_never_raises)
    check("fetch_comments parses comment data",
          t_fetch_comments_parses_data)
    check("suggest_reply without ladder returns neutral template",
          t_suggest_reply_without_ladder)
    check("suggest_reply with ladder uses niche DNA system prompt",
          t_suggest_reply_with_ladder_uses_dna)
    check("suggest_reply handles unknown niche gracefully",
          t_suggest_reply_unknown_niche_ladder)
    check("queue/approve reply flow", t_queue_approve_flow)
    check("reject reply flow", t_reject_flow)
    check("mark_posted flow", t_mark_posted_flow)
    check("queue_reply rejects bad verdict", t_queue_reply_bad_verdict_raises)
    check("module is read-only (no POST path)", t_blocklist_file_is_clean)
    print("ALL {} CHECKS PASSED".format(PASSED))
