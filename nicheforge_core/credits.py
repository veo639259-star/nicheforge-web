"""NicheForge Credit Guard (Phase 5).

Watches daily AI usage per provider and auto-pauses AI work when a free
quota is exhausted. Pure logic on the Phase-1 ``usage`` table — NO network
calls are made here. The usage table is owned by Phase 1; this module only
INSERTs/SELECTs it, never creates it (the integrator must have run
db.init_db() before credit_status() is called).

QUOTAS are CONFIGURABLE ESTIMATES of free-tier daily request limits, not
billed totals — each provider counts "requests" differently and free tiers
change. Override any provider in config.json:

    {"quotas": {"gemini": {"requests_per_day": 500}}}

``load_quotas(config)`` merges those overrides over the defaults below.
A provider hitting 100% of its estimate auto-pauses AI (via the ai_pause
single-row table) until the user resumes manually with clear_ai_pause().
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROVIDERS_DIR = os.path.join(_ROOT, "providers")
if _PROVIDERS_DIR not in sys.path:
    sys.path.insert(0, _PROVIDERS_DIR)

from usage import get_usage  # noqa: E402 — Phase-1 providers/usage.py, read-only

WARNING_PCT = 80.0
EXHAUSTED_PCT = 100.0


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- quotas

QUOTAS = {
    "gemini": {
        "requests_per_day": 1500,
        "note": "CONFIGURABLE ESTIMATE — free-tier requests/day for current "
                "Gemini Flash models. Check Google AI Studio for the live "
                "limit and override in config.json under 'quotas'.",
    },
    "groq": {
        "requests_per_day": 14400,
        "note": "CONFIGURABLE ESTIMATE — Groq free tier is request-rate "
                "limited; this is a conservative daily figure. Override in "
                "config.json under 'quotas'.",
    },
    "nvidia": {
        "requests_per_day": 1000,
        "note": "CONFIGURABLE ESTIMATE — NVIDIA Build free credit pool "
                "expressed as requests/day. Override in config.json under "
                "'quotas'.",
    },
    "openrouter": {
        "requests_per_day": 200,
        "note": "CONFIGURABLE ESTIMATE — OpenRouter free-model daily "
                "request allowance varies by model. Override in config.json "
                "under 'quotas'.",
    },
    "pollinations": {
        "requests_per_day": 10000,
        "note": "CONFIGURABLE ESTIMATE — Pollinations is generous but "
                "rate-limited; treat this as a soft guard. Override in "
                "config.json under 'quotas'.",
    },
    "zai": {
        "requests_per_day": 10000,
        "note": "CONFIGURABLE ESTIMATE — Z.ai free-tier daily requests "
                "for the ladder's fallback models. Override in config.json "
                "under 'quotas'.",
    },
}


def load_quotas(config=None):
    """Merge quota overrides from config over QUOTAS; returns a fresh dict.

    ``config`` may be a dict (as loaded from config.json), a path to a JSON
    config file, or None. Only "requests_per_day" and "note" keys are
    honoured per provider; unknown providers in the override are added.
    The QUOTAS constant itself is never mutated.
    """
    merged = {name: dict(q) for name, q in QUOTAS.items()}
    overrides = {}
    if isinstance(config, str) and config:
        with open(config, encoding="utf-8") as fh:
            overrides = (json.load(fh) or {}).get("quotas", {}) or {}
    elif isinstance(config, dict):
        overrides = config.get("quotas", {}) or {}
    for provider, ov in overrides.items():
        entry = merged.setdefault(
            provider, {"requests_per_day": 0, "note": "user-defined quota"})
        if isinstance(ov, dict):
            for key in ("requests_per_day", "note"):
                if key in ov:
                    entry[key] = ov[key]
        else:
            entry["requests_per_day"] = int(ov)
    return merged


# ---------------------------------------------------------------- usage

def usage_today(db_path):
    """Aggregate the last 24h of usage per provider.

    Returns {provider: {"requests": n, "tokens_in": t, "tokens_out": t}}.
    Every logged row counts as one request — including failed attempts,
    since providers often bill the attempt. Reads via providers.usage.
    """
    rows = get_usage(db_path, days=1)
    agg = {}
    for row in rows:
        provider = row.get("provider") or "unknown"
        entry = agg.setdefault(
            provider, {"requests": 0, "tokens_in": 0, "tokens_out": 0})
        entry["requests"] += 1
        entry["tokens_in"] += int(row.get("tokens_in") or 0)
        entry["tokens_out"] += int(row.get("tokens_out") or 0)
    return agg


# ---------------------------------------------------------------- pause flag

def init_credit_tables(db_path):
    """Create the ai_pause single-row table if it doesn't exist."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_pause (
                paused INTEGER NOT NULL DEFAULT 0,
                reason TEXT DEFAULT '',
                at TEXT DEFAULT ''
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def set_ai_paused(db_path, reason):
    """Pause AI work with a human-readable reason (single row, replaced)."""
    init_credit_tables(db_path)
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM ai_pause")
        conn.execute(
            "INSERT INTO ai_pause (paused, reason, at) VALUES (1, ?, ?)",
            (reason or "", _utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def clear_ai_pause(db_path):
    """Manual resume: clear the AI pause. Quota usage is NOT reset."""
    init_credit_tables(db_path)
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM ai_pause")
        conn.commit()
    finally:
        conn.close()


def is_ai_allowed(db_path):
    """True unless the ai_pause row says paused."""
    init_credit_tables(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT paused FROM ai_pause LIMIT 1").fetchone()
        return row is None or int(row["paused"]) == 0
    finally:
        conn.close()


def pause_reason(db_path):
    """The recorded pause reason, or None when AI is allowed."""
    init_credit_tables(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT reason FROM ai_pause WHERE paused = 1 LIMIT 1").fetchone()
        return row["reason"] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------- status

def credit_status(db_path, config=None):
    """Snapshot of quota consumption per provider.

    Returns {"providers": {name: {"used", "quota", "pct", "state"}},
             "ai_paused": bool}. State is "ok", "warning" (>=80%) or
    "exhausted" (>=100%). Providers with no usage still appear with
    used=0 so the UI can render the full quota table.
    """
    init_credit_tables(db_path)
    quotas = load_quotas(config)
    used = usage_today(db_path)
    providers = {}
    for name, quota_cfg in quotas.items():
        quota = int(quota_cfg.get("requests_per_day") or 0)
        consumed = used.get(name, {}).get("requests", 0)
        pct = 0.0 if quota <= 0 else round(consumed / quota * 100.0, 1)
        if pct >= EXHAUSTED_PCT:
            state = "exhausted"
        elif pct >= WARNING_PCT:
            state = "warning"
        else:
            state = "ok"
        providers[name] = {
            "used": consumed,
            "quota": quota,
            "pct": pct,
            "state": state,
        }
    return {"providers": providers, "ai_paused": not is_ai_allowed(db_path)}


def check_and_enforce(db_path, config=None):
    """Compute credit_status(); auto-pause AI when any provider is exhausted.

    Auto-pause is one-directional: quota exhaustion engages the pause, but
    only a manual clear_ai_pause() resumes AI (the pause reason records
    which provider tripped it, so the user knows why). Returns the status
    dict with ai_paused reflecting the pause state after enforcement.
    """
    status = credit_status(db_path, config)
    exhausted = [
        name for name, info in status["providers"].items()
        if info["state"] == "exhausted"
    ]
    if exhausted:
        detail = ", ".join(
            "%s (%d/%d requests)" % (
                name, status["providers"][name]["used"],
                status["providers"][name]["quota"])
            for name in sorted(exhausted)
        )
        set_ai_paused(db_path, "quota exhausted: " + detail)
        status["ai_paused"] = True
    return status
