"""NicheForge Slot Planner + Clash Detector (Phase 2).

Schedules APPROVED ideas into a posting day with Hmb's hard rules:
  * Posting window: 09:00-21:00 PKT (Asia/Karachi).
  * Per-niche spacing: >= 90 minutes between a niche's own posts.
  * GLOBAL clash rule (from the double-posting incidents): no two posts
    (any niche) within 30 minutes of each other.

Timezone handling:
  * Asia/Karachi (PKT) = UTC+5, no DST.
  * Slots are STORED in the DB as UTC ISO strings (like the rest of the app).
  * The UI layer works in PKT; plan_day returns slot_pkt, list_schedule
    computes slot_pkt per row.

This module only ADDS the scheduled_posts table. It never touches the
ideas or usage tables' schemas.
"""
import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")

WINDOW_START_HOUR = 9    # 09:00 PKT
WINDOW_END_HOUR = 21     # 21:00 PKT (inclusive slot)
SLOT_STEP_MIN = 5
NICHE_GAP_MIN = 90
GLOBAL_GAP_MIN = 30


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_date(date_str):
    """Strict YYYY-MM-DD -> datetime.date."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _utc_iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _pkt_iso(dt):
    return dt.astimezone(PKT).isoformat(timespec="seconds")


def _from_utc_iso(s):
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- tables

def init_schedule_tables(db_path):
    """Create the scheduled_posts table (and slot_utc index) if missing."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idea_id INTEGER NOT NULL,
                niche TEXT NOT NULL,
                slot_utc TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'scheduled',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_posts_slot_utc"
            " ON scheduled_posts (slot_utc)"
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- helpers

def _approved_ideas(conn, niche=None):
    """[{id, niche}, ...] for status='approved' ideas, oldest first."""
    sql = "SELECT id, niche FROM ideas WHERE status = 'approved'"
    params = []
    if niche:
        sql += " AND niche = ?"
        params.append(niche)
    sql += " ORDER BY id ASC"
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []  # ideas table not created yet; nothing to schedule


def _day_slots(day):
    """All 5-min candidate slots in the 09:00-21:00 PKT window (aware UTC)."""
    start = datetime(day.year, day.month, day.day, WINDOW_START_HOUR, 0,
                     tzinfo=PKT)
    end = datetime(day.year, day.month, day.day, WINDOW_END_HOUR, 0, tzinfo=PKT)
    slots, t = [], start
    while t <= end:
        slots.append(t.astimezone(timezone.utc))
        t += timedelta(minutes=SLOT_STEP_MIN)
    return slots


def _slot_ok(slot, niche, placed):
    """True if slot satisfies the 30-min global and 90-min niche gap rules
    against already-placed (slot_dt_utc, niche) pairs."""
    for p_slot, p_niche in placed:
        gap_min = abs((slot - p_slot).total_seconds()) / 60.0
        if gap_min < GLOBAL_GAP_MIN:
            return False
        if p_niche == niche and gap_min < NICHE_GAP_MIN:
            return False
    return True


def _pkt_day_bounds(date_str):
    """(start_utc_iso, end_utc_iso) covering date_str's full PKT day."""
    d = _parse_date(date_str)
    start_utc = datetime(d.year, d.month, d.day, 0, 0, tzinfo=PKT)\
        .astimezone(timezone.utc)
    end_utc = start_utc + timedelta(days=1)
    return start_utc.isoformat(timespec="seconds"), \
        end_utc.isoformat(timespec="seconds")


# ---------------------------------------------------------------- planning

def plan_day(db_path, date_str, niche=None, ideas=None):
    """Assign APPROVED ideas to slots on date_str (YYYY-MM-DD).

    ideas: optional explicit list of dicts with id/niche; when omitted,
    approved ideas are read from the ideas table (optionally filtered by
    niche). Ideas that already have a 'scheduled' row are skipped so a
    day is never double-planned.

    Greedy: round-robin across niches (alphabetical); each idea takes the
    earliest 5-min slot satisfying the 30-min global and 90-min niche gaps.

    Writes rows with status 'scheduled'.
    Returns {"placed": [{"idea_id", "niche", "slot_pkt"}], "unplaced": [ids]}.
    """
    day = _parse_date(date_str)
    init_schedule_tables(db_path)
    conn = _connect(db_path)
    try:
        if ideas is None:
            ideas = _approved_ideas(conn, niche)
        else:
            ideas = [dict(d) for d in ideas
                     if niche is None or d.get("niche") == niche]

        # Skip ideas that already have an active scheduled row (never
        # double-book the same idea).
        already = {r["idea_id"] for r in conn.execute(
            "SELECT idea_id FROM scheduled_posts WHERE status = 'scheduled'")}

        # Round-robin queues per niche, alphabetical.
        queues = {}
        for d in ideas:
            if d.get("id") in already or "id" not in d or "niche" not in d:
                continue
            queues.setdefault(d["niche"], []).append(d)

        # Existing scheduled posts anywhere (they also claim their slots).
        placed = [(_from_utc_iso(r["slot_utc"]), r["niche"])
                  for r in conn.execute(
                      "SELECT slot_utc, niche FROM scheduled_posts"
                      " WHERE status = 'scheduled'")]

        slots = _day_slots(day)
        placed_out, unplaced = [], []
        now = utc_now()
        while any(queues.values()):
            for nch in sorted(queues):
                if not queues[nch]:
                    continue
                idea = queues[nch].pop(0)
                slot = next((s for s in slots if _slot_ok(s, nch, placed)),
                            None)
                if slot is None:
                    unplaced.append(idea["id"])
                else:
                    conn.execute(
                        "INSERT INTO scheduled_posts"
                        " (idea_id, niche, slot_utc, status, created_at)"
                        " VALUES (?, ?, ?, 'scheduled', ?)",
                        (idea["id"], nch, _utc_iso(slot), now),
                    )
                    placed.append((slot, nch))
                    placed_out.append({
                        "idea_id": idea["id"],
                        "niche": nch,
                        "slot_pkt": _pkt_iso(slot),
                    })
        conn.commit()
        return {"placed": placed_out, "unplaced": unplaced}
    finally:
        conn.close()


# ---------------------------------------------------------------- clash detection

def detect_clashes(db_path, date_str=None):
    """Find scheduled posts less than 30 min apart.

    Returns [{"a_id", "b_id", "a_niche", "b_niche", "gap_min"}]; each pair
    appears once. Optionally filtered to one PKT day.
    """
    init_schedule_tables(db_path)
    conn = _connect(db_path)
    try:
        sql = ("SELECT id, niche, slot_utc FROM scheduled_posts"
               " WHERE status = 'scheduled'")
        params = []
        if date_str:
            lo, hi = _pkt_day_bounds(date_str)
            sql += " AND slot_utc >= ? AND slot_utc < ?"
            params = [lo, hi]
        sql += " ORDER BY slot_utc ASC"
        rows = conn.execute(sql, params).fetchall()

        parsed = [(r["id"], r["niche"], _from_utc_iso(r["slot_utc"]))
                  for r in rows]
        clashes = []
        for i in range(len(parsed)):
            a_id, a_niche, a_dt = parsed[i]
            for j in range(i + 1, len(parsed)):
                b_id, b_niche, b_dt = parsed[j]
                gap_min = (b_dt - a_dt).total_seconds() / 60.0
                if gap_min >= GLOBAL_GAP_MIN:
                    break  # sorted; later pairs are wider apart
                clashes.append({
                    "a_id": a_id,
                    "b_id": b_id,
                    "a_niche": a_niche,
                    "b_niche": b_niche,
                    "gap_min": round(gap_min, 1),
                })
        return clashes
    finally:
        conn.close()


# ---------------------------------------------------------------- day ops

def list_schedule(db_path, date_str):
    """Rows scheduled on date_str (PKT day), oldest slot first, with
    slot_pkt computed. Dicts: id, idea_id, niche, slot_utc, slot_pkt,
    status, created_at."""
    init_schedule_tables(db_path)
    lo, hi = _pkt_day_bounds(date_str)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, idea_id, niche, slot_utc, status, created_at"
            " FROM scheduled_posts WHERE slot_utc >= ? AND slot_utc < ?"
            " ORDER BY slot_utc ASC",
            (lo, hi),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["slot_pkt"] = _pkt_iso(_from_utc_iso(d["slot_utc"]))
            out.append(d)
        return out
    finally:
        conn.close()


def clear_day(db_path, date_str):
    """Delete all scheduled rows whose slot falls in date_str's PKT day
    (for re-planning). Returns the number of rows deleted."""
    init_schedule_tables(db_path)
    lo, hi = _pkt_day_bounds(date_str)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM scheduled_posts WHERE slot_utc >= ? AND slot_utc < ?",
            (lo, hi),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
