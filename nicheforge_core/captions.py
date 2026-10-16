"""captions.py -- Phase-2 humanized caption writer for NicheForge.

Turns a research dossier into a ready-to-post caption via the provider key
ladder (no direct network calls; no key handling here). Output is saved to
workspace/niches/<niche>/output/caption_<idea_id>.txt.

Constraints: en-GB / Roman Urdu only, never Devanagari (U+0900-U+097F).
For deen/sukhan/lafz, any Urdu stays in accurate Urdu script.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DNA_DIR = REPO_ROOT / "dna"
OUTPUT_ROOT = REPO_ROOT / "workspace" / "niches"

# Niches whose captions may carry Urdu text in Urdu script (Arabic script,
# not Devanagari -- the Devanagari guard stays active regardless).
URDU_SCRIPT_NICHES = {"deen", "sukhan", "lafz"}


def load_dna(niche: str) -> dict:
    """Load the DNA file for a niche; raise RuntimeError on unknown niche."""
    dna_path = DNA_DIR / f"{niche}.json"
    if not dna_path.exists():
        raise RuntimeError(f"unknown niche '{niche}' (no {dna_path.name})")
    with open(dna_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def reject_devanagari(text: str, what: str = "output") -> None:
    """Raise ValueError if any Devanagari codepoint (U+0900-U+097F) is found."""
    for ch in text:
        if "\u0900" <= ch <= "\u097f":
            raise ValueError("devanagari detected")


def _safe_id(idea_id: str) -> str:
    """Strip anything unsafe for use in a filename."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(idea_id))
    if not cleaned:
        raise RuntimeError("idea_id must contain at least one safe character")
    return cleaned


def _dossier_lines(dossier: dict) -> str:
    """Render the dossier facts/angles into a compact reference block."""
    lines = []
    facts = dossier.get("facts") or []
    if facts:
        lines.append("Key facts:")
        lines.extend(f"- {f}" for f in facts)
    angles = dossier.get("angles") or []
    if angles:
        lines.append("Content angles:")
        lines.extend(f"- {a}" for a in angles)
    avoid = dossier.get("avoid") or []
    if avoid:
        lines.append("Things to avoid:")
        lines.extend(f"- {a}" for a in avoid)
    return "\n".join(lines)


def make_caption(niche: str, idea_id: str, dossier: dict, ladder) -> str:
    """Write a humanized caption for one idea from its dossier.

    The caption follows the niche DNA lane (Roman Urdu or English per the
    niche; British spelling for English), carries the full details plus
    relevant, non-spammy hashtags, and never uses Devanagari. For deen,
    sukhan and lafz, any Urdu stays in accurate Urdu script.

    Saves to workspace/niches/<niche>/output/caption_<idea_id>.txt and
    returns the caption text.

    Raises RuntimeError on ladder failure or invalid niche; raises
    ValueError if the ladder output contains Devanagari.
    """
    dna = load_dna(niche)
    system_prompt = dna.get("system_prompt", "")
    if ladder is None:
        raise RuntimeError(
            f"caption failed for {niche}/{idea_id}: no KeyLadder provided")
    if not isinstance(dossier, dict):
        raise RuntimeError(
            f"caption failed for {niche}/{idea_id}: dossier must be a dict")

    brief_lines = [
        "You are writing a humanized social-media CAPTION for one content idea.",
        f"Niche: {dna.get('display_name', niche)}",
        f"Idea ID: {idea_id}",
        "",
        "Research dossier to draw on:",
        _dossier_lines(dossier),
        "",
        "Caption requirements:",
        "- Sound like a real human wrote it -- warm, natural, conversational.",
        "- Language: Roman Urdu or English, matching the niche's lane.",
        "  English uses British spelling. NEVER use Devanagari script anywhere.",
        "- Include the FULL details from the dossier (names, dates, places,",
        "  figures) -- no vague filler.",
        "- End with relevant, non-spammy hashtags (max 8, actually relevant).",
    ]
    if niche in URDU_SCRIPT_NICHES:
        brief_lines.append(
            "- Any Urdu in the caption must be accurate Urdu script.")
    brief_lines += [
        "",
        "Return ONLY the caption text, no commentary, no quotes around it.",
    ]
    brief = "\n".join(brief_lines)

    try:
        result = ladder.chat(
            messages=[{"role": "user", "content": brief}],
            system=system_prompt,
            timeout=60,
            max_tokens=1024,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"caption failed for {niche}/{idea_id}: {exc}") from exc

    caption = (result.get("text") or "").strip()
    if not caption:
        raise RuntimeError(f"caption failed for {niche}/{idea_id}: empty reply")

    reject_devanagari(caption, f"caption for {niche}/{idea_id}")

    out_dir = OUTPUT_ROOT / niche / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"caption_{_safe_id(idea_id)}.txt"
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(caption)

    return caption
