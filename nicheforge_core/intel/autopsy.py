"""Viral Autopsy — tear down a viral external post, then plan "our version".

analyze(): builds a heuristic teardown (hook, format guess, emoji count,
CTA check, length, timing note) plus strengths/weaknesses, saves the
autopsy row, and inserts a pending [AUTOPSY] idea with the brief.

ladder: accepted but unused in v1 (heuristics only) — reserved for a
future LLM-powered teardown.
"""
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from intel.util import connect, utc_now  # noqa: E402
from research import load_dna, reject_devanagari  # noqa: E402

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D"
    "\U0001F000-\U0001F9FF\U0001FA70-\U0001FAFF]"
)

_CTA_WORDS = ("?", "comment", "share", "follow", "subscribe", "tag")


def _format_guess(text):
    blob = (text or "").lower()
    if "meme" in blob:
        return "meme"
    if any(w in blob for w in ("card", "poster", "carousel", "infographic")):
        return "card"
    if any(w in blob for w in ("photo", "pic", "image", "snapshot")):
        return "photo"
    return "text"


def _hook(text):
    first = (text or "").split("\n", 1)[0].strip()
    return first[:120]


def analyze(db_path, niche, source_url, text, metrics, ladder=None):
    """Tear down a viral post and brief "our version" for one niche.

    metrics: dict, may carry 'posted_hour' (0-23). Returns
    {"teardown": {...}, "brief": "..."}.
    """
    text = text or ""
    metrics = metrics or {}

    hook = _hook(text)
    format_guess = _format_guess(text)
    emoji_count = len(_EMOJI_RE.findall(text))
    lowered = text.lower()
    has_cta = any(w in lowered for w in _CTA_WORDS)
    length = len(text)

    posted_hour = metrics.get("posted_hour")
    if posted_hour is None:
        timing_note = "No timing data — test multiple slots."
    elif 5 <= posted_hour < 12:
        timing_note = "Posted at {:02d}:00 — morning slot; test 08:00-11:00.".format(
            posted_hour)
    elif 12 <= posted_hour < 17:
        timing_note = "Posted at {:02d}:00 — midday slot; test 12:30-15:30.".format(
            posted_hour)
    elif 17 <= posted_hour < 22:
        timing_note = "Posted at {:02d}:00 — evening prime slot; test 18:30-21:00.".format(
            posted_hour)
    else:
        timing_note = "Posted at {:02d}:00 — late-night slot; test 21:00-23:00.".format(
            posted_hour)

    strengths = []
    weaknesses = []
    if hook and len(hook) <= 60:
        strengths.append("strong hook (first line under 60 chars)")
    if emoji_count:
        strengths.append("uses emoji for scannability ({} found)".format(emoji_count))
    if has_cta:
        strengths.append("has an explicit call to action")
    if not strengths:
        strengths.append("viral source — the topic itself has proven pull")
    if not has_cta:
        weaknesses.append("no CTA (no '?', 'comment', 'share' or 'follow')")
    if length > 500:
        weaknesses.append("caption too long ({} chars) — risks drop-off".format(length))
    if not hook:
        weaknesses.append("missing hook — no opening line at all")
    if emoji_count == 0:
        weaknesses.append("no emoji — lower visual scan speed")

    teardown = {
        "hook": hook,
        "format_guess": format_guess,
        "emoji_count": emoji_count,
        "has_cta": has_cta,
        "length": length,
        "timing_note": timing_note,
        "strengths": strengths,
        "weaknesses": weaknesses,
    }

    dna = load_dna(niche)
    rules = dna.get("rules") or ([dna.get("role")] if dna.get("role") else [])
    top_rule = rules[0] if rules else "follow niche DNA"
    fix = weaknesses[0] if weaknesses else "keep the format as-is"
    keep = strengths[0] if strengths else "copy the topic"

    brief = (
        "Make our version:\n"
        "- DNA rule to obey: {}\n"
        "- Copy what worked: {}\n"
        "- Fix what failed: {}"
    ).format(top_rule, keep, fix)
    reject_devanagari(brief, "autopsy brief for {}".format(niche))

    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO autopsies "
            "(niche, source_url, teardown_json, brief, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (niche, source_url or "", json.dumps(teardown, ensure_ascii=False),
             brief, utc_now()),
        )
        conn.commit()
    finally:
        conn.close()

    db.add_idea(db_path, niche,
                "[AUTOPSY] make our version — {}".format(niche),
                detail=brief)

    return {"teardown": teardown, "brief": brief}
