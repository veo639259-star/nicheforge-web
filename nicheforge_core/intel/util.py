"""Shared helpers for the intel package."""
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import NICHE_IDS  # noqa: E402  (db never imports intel)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
