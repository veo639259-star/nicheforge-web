"""research.py -- Phase-2 research dossier builder for NicheForge.

Builds a source-backed research dossier for one idea via the provider key
ladder (no direct network calls; no key handling here). Output is strict JSON
saved under workspace/niches/<niche>/output/dossier_<idea_id>.json.

Constraints: en-GB / Roman Urdu only, never Devanagari (U+0900-U+097F).
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DNA_DIR = REPO_ROOT / "dna"
OUTPUT_ROOT = REPO_ROOT / "workspace" / "niches"

REQUIRED_KEYS = ("facts", "angles", "sources", "avoid")


def load_grounding() -> dict:
    """Read repo-root grounding.json; missing file -> all ungrounded."""
    path = REPO_ROOT / "grounding.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


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


def _strip_fences(text: str) -> str:
    """Remove markdown code fences around a JSON payload."""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _parse_dossier_json(text: str, context: str) -> dict:
    """Parse strict dossier JSON, tolerating markdown fences and stray prose."""
    candidate = _strip_fences(text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # Last resort: extract between the first '{' and the last '}'.
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise RuntimeError(f"{context}: ladder reply was not valid JSON")
        try:
            data = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{context}: ladder reply was not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise RuntimeError(f"{context}: dossier JSON is not an object")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise RuntimeError(f"{context}: dossier missing keys: {', '.join(missing)}")
    for key in REQUIRED_KEYS:
        if not isinstance(data[key], list):
            raise RuntimeError(f"{context}: dossier key '{key}' must be a list")
    return data


def build_dossier(niche: str, idea_id: str, idea_title: str, idea_detail: str,
                  ladder) -> dict:
    """Research one idea into a structured dossier dict.

    Loads the niche DNA system prompt, asks the ladder for strict JSON
    {"facts","angles","sources","avoid"}, validates it, saves it to
    workspace/niches/<niche>/output/dossier_<idea_id>.json and returns it.

    Raises RuntimeError on ladder failure, invalid niche, or invalid JSON;
    raises ValueError if the ladder output contains Devanagari.
    """
    dna = load_dna(niche)
    system_prompt = dna.get("system_prompt", "")
    if ladder is None:
        raise RuntimeError(
            f"research failed for {niche}/{idea_id}: no KeyLadder provided")

    grounded = load_grounding().get(niche, False)

    brief_lines = [
        "You are producing a RESEARCH DOSSIER for a social-media content idea.",
        f"Niche: {dna.get('display_name', niche)}",
        f"Idea ID: {idea_id}",
        f"Idea title: {idea_title}",
        f"Idea detail: {idea_detail}",
        "",
        "Rules for the research:",
        "- Language of the dossier: English (British spelling) or Roman Urdu only.",
        "  NEVER use Devanagari script anywhere.",
        "- Every fact must be source-backed. Include the source URL or",
        "  publication name in 'sources'; only cite sources you can stand behind.",
    ]
    if grounded:
        brief_lines.append(
            "- Use web-grounded, source-backed facts; cite sources.")
    brief_lines += [
        "",
        "Return STRICT JSON ONLY, no prose, no markdown fences, with exactly",
        "these keys:",
        '{"facts": [...], "angles": [...], "sources": [...], "avoid": [...]}',
        "- 'facts': 5-10 key facts about the topic, each a full sentence.",
        "- 'angles': 3-5 distinct content angles to present the idea.",
        "- 'sources': the sources backing the facts (names and/or URLs).",
        "- 'avoid': pitfalls, false claims or sensitivities to avoid.",
    ]
    brief = "\n".join(brief_lines)

    try:
        result = ladder.chat(
            messages=[{"role": "user", "content": brief}],
            system=system_prompt,
            timeout=90,
            max_tokens=2048,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"research failed for {niche}/{idea_id}: {exc}") from exc

    text = (result.get("text") or "").strip()
    if not text:
        raise RuntimeError(f"research failed for {niche}/{idea_id}: empty reply")

    reject_devanagari(text, f"dossier for {niche}/{idea_id}")
    dossier = _parse_dossier_json(text, f"research failed for {niche}/{idea_id}")

    out_dir = OUTPUT_ROOT / niche / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"dossier_{_safe_id(idea_id)}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(dossier, fh, ensure_ascii=False, indent=2)

    return dossier
