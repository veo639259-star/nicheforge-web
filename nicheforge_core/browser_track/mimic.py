"""NicheForge Phase 3 — Human-Mimic Engine.

Safety-critical: every browser action goes through this module so the
automation behaves like a human (variable delays, char-by-char typing,
small mouse jitter) and — most importantly — tasks run STRICTLY
one-at-a-time. Parallel bursts get accounts banned; that rule is enforced
here by TaskQueue's lock + re-entry guard.

The driver is duck-typed on purpose: a real playwright page wrapper only
needs ``type_char(c)`` (or ``type_text(s)``) and ``move_to(x, y)``. No
playwright import here so the module (and its tests) work without it.
"""

import random
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_mimic_tables(db_path):
    """Create the browser_tasks log table if it does not exist."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS browser_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                error TEXT DEFAULT ''
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- config

@dataclass
class MimicConfig:
    """Human-mimic timing knobs. Defaults are conservative on purpose."""
    action_delay_min: float = 1.5   # seconds between UI actions
    action_delay_max: float = 4.0
    typing_cps_min: float = 4.0     # characters per second
    typing_cps_max: float = 9.0
    inter_task_gap_min: float = 20.0  # seconds between queued tasks
    inter_task_gap_max: float = 60.0
    mouse_jitter: bool = True


# ---------------------------------------------------------------- sleeps

def human_sleep(cfg, kind="action"):
    """Sleep a random uniform delay in the configured range.

    kind="action" -> action_delay_min/max; kind="task_gap" ->
    inter_task_gap_min/max. Raises ValueError for anything else.
    """
    if kind == "action":
        lo, hi = cfg.action_delay_min, cfg.action_delay_max
    elif kind == "task_gap":
        lo, hi = cfg.inter_task_gap_min, cfg.inter_task_gap_max
    else:
        raise ValueError("human_sleep kind must be 'action' or 'task_gap', got %r" % (kind,))
    if lo < 0 or hi < 0 or hi < lo:
        raise ValueError("invalid delay range: %r-%r" % (lo, hi))
    time.sleep(random.uniform(lo, hi))


def _per_char_delay(cfg):
    """Delay before one keystroke: 1 / random chars-per-second in range."""
    cps = random.uniform(cfg.typing_cps_min, cfg.typing_cps_max)
    if cps <= 0:
        raise ValueError("typing cps range must be positive")
    return 1.0 / cps


# ---------------------------------------------------------------- typing

def type_text(driver, text, cfg, dry_run=False):
    """Type text char-by-char with human per-keystroke delays.

    driver must provide ``type_char(c)``; if it only has ``type_text(s)``
    the whole string is handed over at once and the human delay is slept
    afterwards. Raises TypeError when the driver offers neither.

    dry_run: sleep nothing, touch the driver nothing; returns the
    transcript [{"char": c, "delay_secs": d}] of what WOULD be typed.
    """
    text = text or ""
    delays = [_per_char_delay(cfg) for _ in text]
    if dry_run:
        return [{"char": c, "delay_secs": d} for c, d in zip(text, delays)]

    has_char = hasattr(driver, "type_char") and callable(driver.type_char)
    has_text = hasattr(driver, "type_text") and callable(driver.type_text)
    if not (has_char or has_text):
        raise TypeError("driver needs .type_char(c) or .type_text(s)")

    if has_char:
        for c, d in zip(text, delays):
            driver.type_char(c)
            time.sleep(d)
    else:
        driver.type_text(text)
        time.sleep(sum(delays))
    return None


# ---------------------------------------------------------------- mouse

# Matches the viewport used by the profile vault's launch_kwargs.
_VIEWPORT_W, _VIEWPORT_H = 1366, 900


def random_mouse_move(driver, cfg, dry_run=False):
    """Move the mouse to a random point; with mouse_jitter enabled the move
    goes through a few small intermediate steps like a human hand.

    driver must provide ``move_to(x, y)``. dry_run returns the list of
    (x, y) points that WOULD be visited without touching the driver.
    """
    if not (hasattr(driver, "move_to") and callable(driver.move_to)):
        raise TypeError("driver needs .move_to(x, y)")
    tx, ty = random.randint(0, _VIEWPORT_W), random.randint(0, _VIEWPORT_H)
    if cfg.mouse_jitter:
        steps = random.randint(2, 4)
        path = []
        for _ in range(steps):
            path.append(
                (tx + random.randint(-25, 25), ty + random.randint(-25, 25))
            )
        path.append((tx, ty))
    else:
        path = [(tx, ty)]
    if dry_run:
        return path
    for x, y in path:
        driver.move_to(x, y)
        time.sleep(random.uniform(0.05, 0.25))
    return None


# ---------------------------------------------------------------- queue

TASK_STATUSES = {"done", "failed"}


class TaskQueue:
    """Strictly sequential FIFO task runner. NEVER parallel.

    Enforcement is two-layered: a threading.Lock (non-blocking acquire —
    a second run_all, even re-entered from inside a task, raises
    RuntimeError immediately instead of deadlocking) plus an internal
    _running flag asserted on entry. Between tasks a human inter-task gap
    is slept. Every task is logged to browser_tasks.
    """

    def __init__(self, db_path, cfg=None):
        self.db_path = db_path
        self.cfg = cfg or MimicConfig()
        self._pending = []
        self._lock = threading.Lock()
        self._running = False
        init_mimic_tables(db_path)

    def submit(self, label, fn):
        """Queue a zero-arg callable under a human-readable label."""
        if not callable(fn):
            raise TypeError("fn must be callable")
        self._pending.append((label, fn))
        return len(self._pending)

    def pending_count(self):
        return len(self._pending)

    def _log_task(self, label, started_at, ended_at, status, error=""):
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO browser_tasks (label, started_at, ended_at, status, error)"
                " VALUES (?, ?, ?, ?, ?)",
                (label, started_at, ended_at, status, error or ""),
            )
            conn.commit()
        finally:
            conn.close()

    def run_all(self):
        """Drain the queue strictly one task at a time. A task that raises
        is logged as failed and the queue continues; results are returned
        as [{"label", "status", "error"}]. Raises RuntimeError if re-entered
        while already running."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError(
                "TaskQueue.run_all re-entered while already running: "
                "browser work is strictly sequential, never parallel"
            )
        try:
            assert not self._running, "TaskQueue re-entered while already running"
            self._running = True
            results = []
            first = True
            while self._pending:
                label, fn = self._pending.pop(0)
                if not first:
                    human_sleep(self.cfg, kind="task_gap")
                first = False
                started = utc_now()
                try:
                    fn()
                    self._log_task(label, started, utc_now(), "done")
                    results.append({"label": label, "status": "done", "error": ""})
                except Exception as e:  # never let one task kill the queue
                    self._log_task(label, started, utc_now(), "failed", str(e))
                    results.append({"label": label, "status": "failed", "error": str(e)})
            return results
        finally:
            self._running = False
            self._lock.release()


def list_tasks(db_path):
    """All logged browser_tasks, oldest first, as dicts."""
    init_mimic_tables(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, label, started_at, ended_at, status, error"
            " FROM browser_tasks ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
