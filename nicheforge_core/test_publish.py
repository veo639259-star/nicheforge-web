"""Tests for publish.py (Phase-2 FB publisher) and setup_keys FB extension.

No real tokens and no real network. The fake token "TEST_TOKEN_1234" must
never appear in any logged field.
"""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from publish import FBPublisher, mask_token, scrub_token  # noqa: E402

FAKE_TOKEN = "TEST_TOKEN_1234"
FAKE_CONFIG = {
    "facebook_pages": [
        {"label": "wicketverse", "page_id": "111222333", "token": FAKE_TOKEN},
    ]
}


def _make_image():
    fh = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    fh.write(b"\xff\xd8\xff\xe0fakejpeg")
    fh.close()
    return fh.name


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM fb_posts").fetchall()]
    finally:
        conn.close()


def test_dry_run_returns_without_network():
    db = tempfile.mktemp(suffix=".db")
    img = _make_image()
    try:
        import requests

        def boom(*a, **k):
            raise AssertionError("network must not be touched in dry_run")

        requests.post, orig = boom, requests.post
        try:
            pub = FBPublisher(FAKE_CONFIG, db, dry_run=True)
            res = pub.publish_photo("wicketverse", img, "Hello world")
        finally:
            requests.post = orig
    finally:
        os.unlink(img)
    assert res["dry_run"] is True
    assert res["page_id"] == "111222333"
    assert res["caption_len"] == len("Hello world")
    rows = _rows(db)
    assert len(rows) == 1 and rows[0]["status"] == "dry_run"
    os.unlink(db)
    print("test_dry_run_returns_without_network: PASS")


def test_unknown_label_raises_valueerror():
    db = tempfile.mktemp(suffix=".db")
    try:
        pub = FBPublisher(FAKE_CONFIG, db, dry_run=True)
        try:
            pub.publish_photo("nosuchpage", "/tmp/x.jpg", "cap")
        except ValueError:
            print("test_unknown_label_raises_valueerror: PASS")
            return
        raise AssertionError("ValueError not raised for unknown label")
    finally:
        if os.path.exists(db):
            os.unlink(db)


def test_token_masked_in_logged_error():
    db = tempfile.mktemp(suffix=".db")
    img = _make_image()

    class FakeResp:
        status_code = 400
        text = "bad"
        content = b"{}"

        def json(self):
            # Graph API error that echoes the raw token back (worst case).
            return {"error": {"message": "Invalid token " + FAKE_TOKEN}}

    import requests
    requests.post, orig = (lambda *a, **k: FakeResp()), requests.post
    try:
        pub = FBPublisher(FAKE_CONFIG, db, dry_run=False)
        res = pub.publish_photo("wicketverse", img, "cap")
    finally:
        requests.post = orig
        os.unlink(img)
    assert res["ok"] is False
    rows = _rows(db)
    assert len(rows) == 1 and rows[0]["status"] == "failed"
    dumped = " ".join(str(v) for v in rows[0].values())
    assert FAKE_TOKEN not in dumped, "raw token leaked into db log"
    assert FAKE_TOKEN not in res["error"], "raw token leaked into error"
    assert "***1234" in rows[0]["error"] or "***1234" in res["error"]
    os.unlink(db)
    print("test_token_masked_in_logged_error: PASS")


def test_setup_keys_import():
    import setup_keys

    assert callable(setup_keys.do_check)
    assert callable(setup_keys.ask_facebook_pages)
    src = open(setup_keys.__file__).read()
    assert "facebook_pages" in src
    print("test_setup_keys_import: PASS")


def test_mask_helpers():
    assert mask_token(FAKE_TOKEN) == "***1234"
    assert "secret" not in scrub_token("bad " + FAKE_TOKEN, FAKE_TOKEN)
    print("test_mask_helpers: PASS")


if __name__ == "__main__":
    test_dry_run_returns_without_network()
    test_unknown_label_raises_valueerror()
    test_token_masked_in_logged_error()
    test_setup_keys_import()
    test_mask_helpers()
    print("ALL TESTS PASSED")
