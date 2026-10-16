"""Creative intel modules test: weaver, recycle, autopsy. Fixtures only."""
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from intel import init_intel_tables
from intel.util import connect, utc_now
from intel import weaver, recycle, autopsy

NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)


def fresh_db():
    path = tempfile.mktemp(suffix=".db")
    db.init_db(path)
    init_intel_tables(path)
    return path


# ---------------- weaver ----------------
db_path = fresh_db()
res = weaver.weave(
    db_path,
    "Pakistan wins T20 final by 6 wickets",
    ["Pakistani bowlers defend 170 in the final over",
     "Captain lifts the trophy in front of a home crowd"],
)
assert len(res["briefs"]) == 14, "expected 14 briefs"
fits = [b for b in res["briefs"] if b["fit"]]
nofits = [b for b in res["briefs"] if not b["fit"]]
assert len(fits) == 13, "expected 13 fit, got {}".format(len(fits))
assert len(nofits) == 1 and nofits[0]["niche"] == "techsathi", \
    "expected only techsathi no-fit"
wick = [b for b in res["briefs"] if b["niche"] == "wicketverse"][0]
assert "NEVER generate fake photorealistic player faces." in wick["brief"], \
    "DNA rules missing from brief"
deen = [b for b in res["briefs"] if b["niche"] == "deen"][0]
assert "zero Arabic" in deen["brief"], "deen angle missing"
weave_ideas = db.list_ideas(db_path, status="pending")
assert sum(1 for i in weave_ideas if i["title"].startswith("[WEAVE]")) == 14, \
    "expected 14 [WEAVE] ideas"

# ---------------- recycle ----------------
db_path = fresh_db()
conn = connect(db_path)
fixtures = [
    ("wicketverse", "post_top", "2026-05-01T10:00:00+00:00", 500, 120, 80),   # engagement 700
    ("pakwire", "post_mid", "2026-05-10T09:00:00+00:00", 100, 40, 30),       # 170
    ("memeistan", "post_mid2", "2026-06-01T12:00:00+00:00", 90, 30, 20),      # 140
    ("lafz", "post_mid3", "2026-06-15T08:00:00+00:00", 70, 20, 15),           # 105
    ("deen", "post_low", "2026-07-01T20:00:00+00:00", 20, 5, 5),              # 30
    ("maloomat", "post_recent", "2026-10-01T10:00:00+00:00", 900, 400, 300), # too new
]
for niche, pid, posted, l, s, c in fixtures:
    conn.execute(
        "INSERT INTO post_metrics (niche, post_id, posted_at, likes, shares, "
        "comments, reach, source, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, 'fixture', ?)",
        (niche, pid, posted, l, s, c, utc_now()),
    )
conn.commit()
conn.close()

cands = recycle.find_candidates(db_path, min_age_days=90, _now=NOW)
assert len(cands) == 3, "expected top 3, got {}".format(len(cands))
assert cands[0]["post_id"] == "post_top", "top post not first"
assert cands[0]["engagement"] == 700, "engagement math wrong"
assert all(c["post_id"] != "post_recent" for c in cands), "recent post leaked in"
out = recycle.make_briefs(db_path, _now=NOW)
assert out["briefs_created"] == 3, "expected 3 briefs"
conn = connect(db_path)
n_rows = conn.execute("SELECT COUNT(*) FROM recycle_briefs").fetchone()[0]
conn.close()
assert n_rows == 3, "expected 3 recycle_briefs rows"
rec_ideas = db.list_ideas(db_path, status="pending")
assert sum(1 for i in rec_ideas if i["title"].startswith("[RECYCLE]")) == 3, \
    "expected 3 [RECYCLE] ideas"

# ---------------- autopsy ----------------
db_path = fresh_db()
res = autopsy.analyze(
    db_path,
    "memeistan",
    "https://www.facebook.com/post/123",
    "5 records broken in one night! \U0001F525\n"
    "Pakistan vs India T20 final. What a night! Comment your favourite moment \U0001F447",
    {"posted_hour": 21},
)
t = res["teardown"]
for key in ("hook", "format_guess", "emoji_count", "has_cta",
            "length", "timing_note", "strengths", "weaknesses"):
    assert key in t, "teardown missing key: {}".format(key)
assert t["hook"] == "5 records broken in one night! \U0001F525", "hook wrong"
assert t["emoji_count"] == 2, "emoji count wrong"
assert t["has_cta"] is True, "CTA not detected"
assert t["format_guess"] == "text", "format guess wrong"
assert "evening prime slot" in t["timing_note"], "timing note wrong"
assert any("strong hook" in s for s in t["strengths"]), "strong hook strength missing"
assert res["brief"].startswith("Make our version:"), "brief format wrong"
assert "obey" in res["brief"], "brief should reference DNA rule"
conn = connect(db_path)
rows = conn.execute("SELECT brief, teardown_json FROM autopsies").fetchall()
conn.close()
assert len(rows) == 1 and rows[0][0] == res["brief"], "autopsy row not saved"
aut_ideas = db.list_ideas(db_path, status="pending")
assert any(i["title"].startswith("[AUTOPSY]") for i in aut_ideas), \
    "[AUTOPSY] idea not saved"

print("ALL INTEL CREATIVE TESTS PASSED")
