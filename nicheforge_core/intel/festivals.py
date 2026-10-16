"""Festival Auto-Calendar — upcoming festivals become planned packs + inbox ideas.

Lunar festivals move each year; their notes carry the marker
"(date approximate — update yearly)". Idempotent: generate_packs() skips any
festival whose name+pack_date row already exists.
"""
from datetime import date, datetime, timezone

from intel.util import utc_now, connect, NICHE_IDS
import db

APPROX = "(date approximate — update yearly)"

FESTIVALS = [
    {"name": "Eid ul-Fitr", "month": 3, "day": 20,
     "niches": ["deen", "aangan", "memeistan", "lafz", "sukhan"],
     "note": "lunar — confirm moon sighting " + APPROX},
    {"name": "Eid ul-Adha", "month": 5, "day": 27,
     "niches": ["deen", "aangan", "memeistan", "lafz", "sukhan"],
     "note": "lunar — confirm moon sighting " + APPROX},
    {"name": "Ramadan start", "month": 2, "day": 18,
     "niches": ["deen", "lafz", "sukhan"],
     "note": "lunar — confirm moon sighting " + APPROX},
    {"name": "Independence Day (14 August)", "month": 8, "day": 14,
     "niches": ["pakwire", "maloomat", "aangan", "memeistan", "deen"],
     "note": ""},
    {"name": "Pakistan Day (23 March)", "month": 3, "day": 23,
     "niches": ["pakwire", "maloomat", "parhai"],
     "note": ""},
    {"name": "Quaid Day / Christmas (25 December)", "month": 12, "day": 25,
     "niches": ["pakwire", "maloomat", "aangan"],
     "note": ""},
    {"name": "Defence Day (6 September)", "month": 9, "day": 6,
     "niches": ["pakwire", "maloomat", "deen"],
     "note": ""},
    {"name": "BISE exam season", "month": 3, "day": 1,
     "niches": ["parhai", "imtihan", "angrezi"],
     "note": "March window — confirm board dates " + APPROX},
    {"name": "BISE supplementary exams", "month": 11, "day": 1,
     "niches": ["parhai", "imtihan"],
     "note": "November window — confirm board dates " + APPROX},
    {"name": "PSL window", "month": 2, "day": 7,
     "niches": ["wicketverse", "memeistan"],
     "note": "approx — confirm PCB schedule " + APPROX},
    {"name": "ICC event window", "month": 2, "day": 10,
     "niches": ["wicketverse"],
     "note": "generic — update with the ICC calendar " + APPROX},
]


def _as_date(_today):
    if _today is None:
        return datetime.now(timezone.utc).date()
    if isinstance(_today, date):
        return _today
    return date.fromisoformat(str(_today))


def upcoming(days_ahead=7, _today=None):
    """Festivals whose next occurrence falls within the coming window."""
    today = _as_date(_today)
    out = []
    for fest in FESTIVALS:
        try:
            occ = date(today.year, fest["month"], fest["day"])
        except ValueError:
            continue
        if occ < today:
            occ = date(today.year + 1, fest["month"], fest["day"])
        delta = (occ - today).days
        if 0 <= delta <= days_ahead:
            out.append({
                "name": fest["name"],
                "pack_date": occ.isoformat(),
                "niches": list(fest["niches"]),
                "note": fest["note"],
            })
    return sorted(out, key=lambda x: x["pack_date"])


def generate_packs(db_path, days_ahead=7, _today=None):
    """Insert festival_packs rows and per-niche pending ideas. Idempotent."""
    packs = 0
    ideas = 0
    conn = connect(db_path)
    try:
        for fest in upcoming(days_ahead=days_ahead, _today=_today):
            exists = conn.execute(
                "SELECT id FROM festival_packs WHERE name=? AND pack_date=?",
                (fest["name"], fest["pack_date"])).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO festival_packs "
                "(name, pack_date, niches_csv, status, created_at) "
                "VALUES (?, ?, ?, 'planned', ?)",
                (fest["name"], fest["pack_date"], ",".join(fest["niches"]),
                 utc_now()))
            conn.commit()
            packs += 1
            for niche in fest["niches"]:
                if niche not in NICHE_IDS:
                    continue
                title = "[FESTIVAL] {} — {}".format(fest["name"], niche)
                detail = "Festival pack for {}. {}".format(
                    fest["name"], fest["note"] or
                    "Plan niche-appropriate posts for this occasion.")
                ok, _info = db.add_idea(db_path, niche, title, detail)
                if ok:
                    ideas += 1
    finally:
        conn.close()
    return {"packs": packs, "ideas": ideas}


def list_packs(db_path, limit=30):
    """Festival packs, soonest first."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, pack_date, niches_csv, status, created_at FROM festival_packs"
            " ORDER BY pack_date ASC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
