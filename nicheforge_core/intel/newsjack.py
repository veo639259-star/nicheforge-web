"""Newsjacking Autopilot — turn a breaking story into per-niche speed briefs.

With ladder=None (the default) every brief is a plain template — no AI call,
no network. The ``ladder`` parameter is reserved for a future AI-enhanced
brief path; passing one currently still produces the template brief.
"""
from intel.util import utc_now, connect, NICHE_IDS
import db
from research import load_dna, reject_devanagari


def _template_brief(niche, headline, facts):
    dna = load_dna(niche)
    display = dna.get("display_name", niche)
    rules = list(dna.get("rules", []))[:3]
    lines = [
        "1) What happened: {}".format(headline),
        "   Key facts: {}".format(facts),
        "2) {} angle: hook today's audience to this story fast — "
        "speed beats polish.".format(display),
        "3) Post format: text + one strong visual, posted within the hour; "
        "obey the niche rules below.",
    ]
    lines.append("Niche rules to obey:")
    for rule in rules:
        lines.append("- {}".format(rule))
    return "\n".join(lines)


def on_spike(db_path, headline, facts, niches, ladder=None):
    """Create one speed brief per niche and push each to the approval inbox.

    Returns {"briefs_created": n}. Raises ValueError on an unknown niche.
    """
    briefs = 0
    for niche in niches or []:
        if niche not in NICHE_IDS:
            raise ValueError("unknown niche '{}'".format(niche))
        title = "[NEWSJACK] " + (headline or "")[:80]
        detail = _template_brief(niche, headline, facts)
        reject_devanagari(title, "newsjack title")
        reject_devanagari(detail, "newsjack brief")
        ok, _info = db.add_idea(db_path, niche, title, detail)
        if ok:
            briefs += 1

    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO newsjack_runs "
            "(headline, niches_csv, briefs_created, created_at) "
            "VALUES (?, ?, ?, ?)",
            (headline or "", ",".join(niches or []), briefs, utc_now()))
        conn.commit()
    finally:
        conn.close()
    return {"briefs_created": briefs}
