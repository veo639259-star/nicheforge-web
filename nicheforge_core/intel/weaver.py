"""Story Weaver — spin one event/headline into per-niche content briefs.

Template-driven in v1 (works with ladder=None). Every brief is grounded in
the niche's DNA rules so downstream steps (captions, prompts, overlay) stay
on-brand. The ladder parameter is accepted for future AI-generated briefs.
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from intel.util import connect, utc_now, NICHE_IDS  # noqa: E402
from research import load_dna, reject_devanagari  # noqa: E402

NICHE_ANGLES = {
    "wicketverse": "match/result card angle: score-focused, fan emotion",
    "pakwire": "straight news card: headline + 2 key facts",
    "memeistan": "meme angle: relatable joke on the event",
    "sukhan": "couplet theme: pick a classical theme matching the mood",
    "lafz": "motivational quote angle",
    "deen": "reflection/reminder angle (zero Arabic, Urdu only)",
    "maloomat": "fact angle: one verified fact from the event",
    "paheli": "riddle inspired by the event (riddle text on card, answer NEVER shown, no visual clues)",
    "parhai": "study tie-in: exam motivation or GK fact",
    "aangan": "family/community angle",
    "angrezi": "English-learning angle: 3 vocabulary words from the event",
    "techsathi": "tech angle if the event has one, else mark no-fit",
    "imtihan": "exam-prep angle",
    "marvelverse": "epic cinematic theme angle (backgrounds only, no faces)",
}

TECH_KEYWORDS = (
    "tech", "ai", "app", "software", "internet", "gadget", "smartphone",
    "cyber", "digital", "5g", "robot", "startup", "chip", "data", "hack",
    "phone", "laptop", "crypto", "blockchain", "google", "meta", "tiktok",
    "instagram", "youtube", "satellite", "space", "electric vehicle",
    "computer", "wifi", "social media",
)


def _dna_rules(dna):
    rules = dna.get("rules")
    if rules:
        return list(rules[:3])
    role = dna.get("role") or ""
    return [role] if role else []


def _fits(niche, text_blob):
    if niche != "techsathi":
        return True
    blob = (text_blob or "").lower()
    for kw in TECH_KEYWORDS:
        if len(kw) <= 3:
            # short keywords need whole-word match ("ai" must not fire on
            # "Captain", "ev" must not fire on "defend")
            if re.search(r"\b" + re.escape(kw) + r"\b", blob):
                return True
        elif kw in blob:
            return True
    return False


def weave(db_path, headline, facts, ladder=None):
    """Build one content brief per niche for a news/event headline.

    facts: list of fact strings. ladder: optional KeyLadder (unused in v1 —
    briefs are template-composed; pass None to skip AI).
    Returns {"briefs": [{"niche", "brief", "fit"}]} and stores each as a
    pending idea titled "[WEAVE] <headline>".
    """
    headline = (headline or "").strip()
    facts_blob = "\n".join(facts or [])

    briefs = []
    for niche in NICHE_IDS:
        dna = load_dna(niche)
        angle = NICHE_ANGLES.get(niche, "general angle")
        rules = _dna_rules(dna)
        rules_line = "; ".join(rules) if rules else "follow niche DNA"
        brief = (
            "Story-weave brief for {}:\n"
            "Headline: {}\n"
            "Facts:\n{}\n"
            "Angle: {}\n"
            "DNA rules: {}"
        ).format(niche, headline, facts_blob or "(no facts given)", angle,
                 rules_line)
        reject_devanagari(brief, "weaver brief for {}".format(niche))
        fit = _fits(niche, headline + "\n" + facts_blob)
        title = "[WEAVE] " + headline[:70]
        db.add_idea(db_path, niche, title, detail=brief)
        briefs.append({"niche": niche, "brief": brief, "fit": fit})

    return {"briefs": briefs}
