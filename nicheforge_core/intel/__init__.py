"""NicheForge intelligence layer — shared table schemas.

All Phase-4 tables are created here. Never alters Phase 1-3 tables.
"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS post_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche TEXT NOT NULL,
    post_id TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    likes INTEGER NOT NULL DEFAULT 0,
    shares INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    reach INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trend_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    niches_csv TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    detected_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS crisis_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    headline TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    detected_at TEXT NOT NULL,
    paused_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    resumed_at TEXT
);
CREATE TABLE IF NOT EXISTS festival_packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    pack_date TEXT NOT NULL,
    niches_csv TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recycle_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche TEXT NOT NULL,
    post_id TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    engagement INTEGER NOT NULL DEFAULT 0,
    new_angle TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS autopsies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    teardown_json TEXT NOT NULL DEFAULT '{}',
    brief TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idea_scores (
    idea_id INTEGER PRIMARY KEY,
    score REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    scored_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS niche_health (
    niche TEXT PRIMARY KEY,
    score INTEGER NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS newsjack_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    headline TEXT NOT NULL,
    niches_csv TEXT NOT NULL DEFAULT '',
    briefs_created INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    median_reach INTEGER NOT NULL DEFAULT 0,
    current_reach INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS intel_state (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL DEFAULT ''
);
"""


def init_intel_tables(db_path):
    """Create all Phase-4 tables if missing. Idempotent."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
