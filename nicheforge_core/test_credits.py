"""Tests for credits.py (Phase-5 Credit Guard).

Pure logic on the Phase-1 usage table — no network, no real providers.
The usage table is created by db.init_db(); credits.py must never create
it itself.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "providers"))

import db  # noqa: E402
import credits  # noqa: E402
from usage import log_usage  # noqa: E402

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
    db.init_db(path)  # creates usage table; credits must not create it
    return path


def test_default_quotas_cover_six_providers():
    for name in ("gemini", "groq", "nvidia", "openrouter", "pollinations", "zai"):
        assert name in credits.QUOTAS, "missing provider %s" % name
        assert credits.QUOTAS[name]["requests_per_day"] > 0
        assert "CONFIGURABLE" in credits.QUOTAS[name]["note"]


def test_load_quotas_override_merges():
    quotas = credits.load_quotas({"quotas": {"gemini": {"requests_per_day": 10}}})
    assert quotas["gemini"]["requests_per_day"] == 10
    assert quotas["groq"]["requests_per_day"] == credits.QUOTAS["groq"]["requests_per_day"]
    # QUOTAS constant untouched
    assert credits.QUOTAS["gemini"]["requests_per_day"] != 10


def test_load_quotas_from_file_path():
    fd, cfg_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write('{"quotas": {"nvidia": 5}}')
    try:
        quotas = credits.load_quotas(cfg_path)
        assert quotas["nvidia"]["requests_per_day"] == 5
    finally:
        os.unlink(cfg_path)


def test_usage_today_aggregates():
    p = _fresh_db()
    for _ in range(3):
        log_usage(p, "gemini", "flash", tokens_in=10, tokens_out=5)
    log_usage(p, "groq", "llama", tokens_in=100, tokens_out=50)
    agg = credits.usage_today(p)
    assert agg["gemini"]["requests"] == 3
    assert agg["gemini"]["tokens_in"] == 30
    assert agg["gemini"]["tokens_out"] == 15
    assert agg["groq"]["requests"] == 1
    assert agg["groq"]["tokens_in"] == 100
    os.unlink(p)


def test_credit_status_ok_when_quota_plenty():
    p = _fresh_db()
    log_usage(p, "gemini", "flash")
    status = credits.credit_status(p)
    g = status["providers"]["gemini"]
    assert g["used"] == 1 and g["quota"] == 1500
    assert g["state"] == "ok"
    assert status["ai_paused"] is False
    os.unlink(p)


def test_warning_at_80_percent():
    p = _fresh_db()
    for _ in range(8):
        log_usage(p, "groq", "llama")
    status = credits.credit_status(p, {"quotas": {"groq": {"requests_per_day": 10}}})
    g = status["providers"]["groq"]
    assert g["pct"] == 80.0
    assert g["state"] == "warning"
    # below 80% stays ok
    p2 = _fresh_db()
    for _ in range(7):
        log_usage(p2, "groq", "llama")
    st2 = credits.credit_status(p2, {"quotas": {"groq": {"requests_per_day": 10}}})
    assert st2["providers"]["groq"]["state"] == "ok"
    os.unlink(p)
    os.unlink(p2)


def test_exhausted_at_100_percent_auto_pauses():
    p = _fresh_db()
    for _ in range(10):
        log_usage(p, "nvidia", "nemotron")
    status = credits.check_and_enforce(p, {"quotas": {"nvidia": {"requests_per_day": 10}}})
    n = status["providers"]["nvidia"]
    assert n["pct"] == 100.0 and n["state"] == "exhausted"
    assert status["ai_paused"] is True
    assert credits.is_ai_allowed(p) is False
    reason = credits.pause_reason(p)
    assert reason and "nvidia" in reason and "10" in reason
    os.unlink(p)


def test_clear_ai_pause_resumes():
    p = _fresh_db()
    credits.set_ai_paused(p, "manual test")
    assert credits.is_ai_allowed(p) is False
    credits.clear_ai_pause(p)
    assert credits.is_ai_allowed(p) is True
    assert credits.pause_reason(p) is None
    os.unlink(p)


def test_enforce_is_one_directional():
    # Exhaustion pauses; a day with no usage does NOT auto-clear the pause —
    # only clear_ai_pause() resumes.
    p = _fresh_db()
    for _ in range(5):
        log_usage(p, "gemini", "flash")
    credits.check_and_enforce(p, {"quotas": {"gemini": {"requests_per_day": 5}}})
    assert credits.is_ai_allowed(p) is False
    p2 = _fresh_db()
    # simulate "next day, still paused": pause row present, nothing exhausted
    credits.set_ai_paused(p2, "quota exhausted: gemini")
    credits.check_and_enforce(p2)  # no usage today, nothing exhausted
    assert credits.is_ai_allowed(p2) is False  # still paused: manual resume only
    os.unlink(p)
    os.unlink(p2)


def test_credits_does_not_create_usage_table():
    # credits.credit_status on a db WITHOUT the usage table must fail —
    # it is only allowed to SELECT, never create.
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    credits.init_credit_tables(p)
    import sqlite3

    conn = sqlite3.connect(p)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()
    assert "usage" not in tables
    assert "ai_pause" in tables
    os.unlink(p)


if __name__ == "__main__":
    check("default QUOTAS cover 6 providers, marked estimates", test_default_quotas_cover_six_providers)
    check("load_quotas merges overrides, constant untouched", test_load_quotas_override_merges)
    check("load_quotas accepts config file path", test_load_quotas_from_file_path)
    check("usage_today aggregates requests and tokens", test_usage_today_aggregates)
    check("credit_status ok when quota plenty", test_credit_status_ok_when_quota_plenty)
    check("warning at 80% threshold", test_warning_at_80_percent)
    check("exhausted at 100% auto-pauses AI", test_exhausted_at_100_percent_auto_pauses)
    check("clear_ai_pause resumes manually", test_clear_ai_pause_resumes)
    check("enforce is one-directional (manual resume only)", test_enforce_is_one_directional)
    check("credits never creates the usage table", test_credits_does_not_create_usage_table)
    print("ALL %d CHECKS PASSED" % _passed)
