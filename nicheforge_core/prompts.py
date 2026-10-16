#!/usr/bin/env python3
"""NicheForge Prompt Forge (Phase 2).

Deterministic composer — NO API calls. Converts a research dossier into a
detailed image-generation prompt following Hmb's 8-section structured
convention (see ~/workspace/niche-branding-chatgpt/flow-structured-prompts-all-niches.md):

    1. ROLE  2. BRAND STYLE LOCK  3. SCENE / CONTENT  4. TEXT RULES
    5. COMPOSITION  6. LIGHTING & MOOD  7. HARD NEGATIVES  8. OUTPUT

Universal settings: agent mode OFF, 4 versions, pick best 1, 1:1 1080x1080
unless the niche says otherwise.

NicheForge text rules:
- TEXT-FREE bases (Urdu overlaid later by overlay.py): deen, sukhan, lafz,
  wicketverse. MarvelVerse is also text-free (backgrounds only).
- Full-text cards (text rendered in image): memeistan, techsathi, paheli,
  pakwire, maloomat, aangan (minimal), angrezi, parhai, imtihan.

Dossier shape: {"facts": [...], "angles": [...], "sources": [...], "avoid": [...]}
stored at workspace/niches/<niche>/output/dossier_<idea_id>.json
(or passed directly to forge_prompt).
"""

import json
import os
import re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(ROOT, "workspace")

NICHE_IDS = [
    "wicketverse", "pakwire", "maloomat", "sukhan", "paheli",
    "memeistan", "lafz", "deen", "parhai", "aangan",
    "angrezi", "techsathi", "imtihan", "marvelverse",
]

TEXT_FREE_NICHES = {"deen", "sukhan", "lafz", "wicketverse", "marvelverse", "pakwire"}

IDEA_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

UNIVERSAL_NEGATIVES = [
    "NO watermarks, NO logos (except the niche wordmark where stated), NO fake UI.",
    "NO distorted faces, NO warped objects, NO extra fingers, NO AI slop.",
    "NO Devanagari script anywhere.",
    "NO extra text beyond what the TEXT RULES section allows.",
]

GENERATION_SETTINGS = (
    "Generation settings: agent mode OFF. Generate 4 versions and pick the best 1. "
    "Aspect ratio 1:1, 1080x1080 square."
)

# ---------------------------------------------------------------------------
# Per-niche specs
# ---------------------------------------------------------------------------
# text_mode one of: text_free, meme, tech_card, riddle, fact_card,
#                  minimal_text, educational, study_card

NICHE_SPECS = {
    "deen": {
        "display": "Deen",
        "role": "You are a premium Islamic editorial illustrator for Deen, a Pakistani Islamic reminders page.",
        "brand": (
            "Deep Emerald Night #0A1420 + Sacred Gold #FFD23F premium sacred editorial style. "
            "Elegant illustrated background (mosque silhouette, geometric Islamic pattern, soft light rays). "
            "Calm, reverent, premium. No clutter."
        ),
        "scene_flavor": (
            "A serene illustrated Islamic background — e.g. a mosque courtyard at dusk, crescent moon, "
            "soft golden light, geometric patterns. Keep the center visually quiet for the later text overlay."
        ),
        "text_mode": "text_free",
        "text_extra": "ZERO Arabic — not a single Arabic letter anywhere. Keep the center area quiet and uncluttered.",
        "composition": "Atmospheric background with a large quiet center area for the later verse/reminder overlay; motifs framing the edges.",
        "mood": "Sacred, peaceful. Soft golden glow against deep emerald night tones.",
        "negatives": [
            "NO Arabic script of any kind. NO invented or misspelled text of any kind.",
            "Content must stay within approved Deobandi-source subject matter; nothing from forbidden sources.",
        ],
    },
    "sukhan": {
        "display": "Sukhan",
        "role": "You are a premium Urdu poetry illustrator for Sukhan, a Pakistani shayari page.",
        "brand": (
            "Warmer palette: deep teal + terracotta accents on a dark base, tasteful motifs. "
            "Elegant, literary, romantic. Textures allowed (old paper, ink, dusk sky)."
        ),
        "scene_flavor": (
            "A text-free poetic background — e.g. a dusk sky over old Lahore rooftops, birds in flight, "
            "terracotta glow on the horizon. NO words of any kind."
        ),
        "text_mode": "text_free",
        "text_extra": "NO Urdu, NO calligraphy, NO scribbles, NO decorative text-like marks. The verse is added later via PIL (Nastaleeq).",
        "composition": "Large empty center for the later verse overlay, motifs framing the edges.",
        "mood": "Poetic, nostalgic. Warm terracotta dusk light against deep teal shadows.",
        "negatives": [
            "NO text of any kind, including decorative calligraphy-like marks.",
            "Only verified verses with attribution are used on cards — never invent verse text.",
        ],
    },
    "lafz": {
        "display": "Lafz",
        "role": "You are a premium minimal editorial illustrator for Lafz, a Pakistani motivational quotes brand.",
        "brand": (
            "Obsidian Charcoal + Literary Ivory + Royal Emerald + Antique Gold. "
            "Minimal, literary, premium. Textures allowed (paper grain, ink wash, soft light)."
        ),
        "scene_flavor": (
            "A text-free atmospheric background — e.g. dark charcoal texture with a single emerald light streak "
            "and gold dust particles. NO words."
        ),
        "text_mode": "text_free",
        "text_extra": "NO English words anywhere. Text is added later by the card builder (PIL). Leave a large quiet center area.",
        "composition": "Large empty center/upper area for later text overlay, visual interest at the edges.",
        "mood": "Contemplative, warm. Soft gold light against dark charcoal, emerald accents.",
        "negatives": ["NO text of any kind. NO clutter."],
    },
    "wicketverse": {
        "display": "Wicketverse",
        "role": "You are a premium sports illustrator for Wicketverse, a Pakistani cricket page.",
        "brand": (
            "Electric stadium aesthetic: floodlight white + deep green + gold energy. "
            "Cinematic sports photography. High detail, dynamic."
        ),
        "scene_flavor": (
            "One cricket moment — e.g. a fast bowler mid-delivery stride at night, floodlights flaring, crowd bokeh. "
            "Dynamic action, no identifiable real-player faces."
        ),
        "text_mode": "text_free",
        "text_extra": "NO scores, NO words, NO numbers anywhere. Text is added by the card builder. Leave a quiet upper-third area.",
        "composition": "Dynamic action centered, rule-of-thirds, dark negative space in the upper third for card text.",
        "mood": "Electric, intense. Floodlight glare against deep night tones, gold accents.",
        "negatives": [
            "NO text of any kind.",
            "NEVER generate fake photorealistic player faces — no real-player likenesses.",
        ],
    },
    "marvelverse": {
        "display": "MarvelVerse",
        "role": (
            "You are a cinematic environment artist for MarvelVerse. "
            "BACKGROUNDS AND ENVIRONMENTS ONLY — you never draw people."
        ),
        "brand": (
            "Cinematic environment art: epic scale, rich atmospheric detail, dramatic depth. "
            "Premium fantasy/sci-fi environment look, no characters."
        ),
        "scene_flavor": (
            "A breathtaking environment/background scene — e.g. a vast alien cityscape at dusk, ancient ruins "
            "under twin moons, a storm-lit canyon. Empty of people; scale conveyed through architecture and nature."
        ),
        "text_mode": "text_free",
        "text_extra": (
            "TEXT-FREE environment art. NO text, NO words, NO letters anywhere. "
            "BACKGROUNDS ONLY — this is an environment plate, not a poster."
        ),
        "composition": "Wide environmental composition, strong foreground/midground/background depth, no central figure.",
        "mood": "Epic, atmospheric. Dramatic light, rich colour, cinematic scale.",
        "negatives": [
            "ABSOLUTE RULE: NO faces, NO actors, NO characters, NO character likenesses — backgrounds only.",
            "NO people, NO silhouettes of people, NO crowds.",
        ],
    },
    "memeistan": {
        "display": "Memeistan",
        "role": "You are a meme image creator for Memeistan, a Pakistani meme page (Roman Urdu + English lanes).",
        "brand": (
            "Bold meme aesthetic: high contrast, expressive subjects, clean readable text areas. "
            "Fun, relatable, desi humour. One clear joke per image."
        ),
        "scene_flavor": (
            "The meme visual — an expressive person, animal or situation matching the joke. "
            "Leave clear top and bottom zones for the caption text."
        ),
        "text_mode": "meme",
        "text_extra": "",
        "composition": "Subject centered, clear empty bands top and bottom for the caption text.",
        "mood": "Bright, punchy, high-energy. Matches the joke's vibe.",
        "negatives": ["NO misspelled text."],
    },
    "techsathi": {
        "display": "TechSathi",
        "role": "You are a premium minimal tech-card designer for TechSathi.",
        "brand": (
            "Premium minimal TECH CARD. Clean, modern, uncluttered. "
            "NO fixed layout template — you decide the composition per card."
        ),
        "scene_flavor": (
            "One relevant realistic picture per topic illustrating the tech idea. "
            "Avoid clutter, fake UI, and stock-photo look."
        ),
        "text_mode": "tech_card",
        "text_extra": "",
        "composition": (
            "You decide the layout. One picture, headline prominent, subline subtle, "
            "small TechSathi mark in a corner. Generous negative space."
        ),
        "mood": "Clean, premium tech feel. Soft studio light, refined tones.",
        "negatives": [
            "NO clutter, NO fake UI, NO stock-photo look.",
            "NO extra text beyond headline + subline + mark.",
        ],
    },
    "paheli": {
        "display": "Paheli",
        "role": "You are a playful puzzle-card designer for Paheli, a riddles page (English + Roman Urdu).",
        "brand": (
            "Playful mystery aesthetic: deep purple/indigo + gold question-mark energy. "
            "Curious, fun, premium. One riddle per card."
        ),
        "scene_flavor": (
            "A mysterious playful visual hinting at the riddle theme — e.g. a glowing question mark formed by "
            "stars over a dark library. The artwork itself must contain NO riddle or answer clues."
        ),
        "text_mode": "riddle",
        "text_extra": "",
        "composition": "Riddle text centered over a quiet area with a soft scrim, visual framing the edges.",
        "mood": "Mysterious, inviting. Gold glow against deep indigo.",
        "negatives": [
            "Answer NEVER on the card. NO answer hints hidden in the artwork.",
            "NO misspelled text.",
        ],
    },
    "pakwire": {
        "display": "PakWire",
        "role": "You are a premium news-card designer for PakWire, a Pakistani news page.",
        "brand": (
            "Newsroom premium: ink-green + ivory + archive-gold. "
            "Clean editorial news-card look, photographic realism, trustworthy and sharp."
        ),
        "scene_flavor": (
            "A realistic news-style visual for the story — real-event photograph feel (street, building, crowd, "
            "press-style framing). Factual, never sensationalised."
        ),
        "text_mode": "text_free",
        "text_extra": "",
        "composition": "Photographic news-style visual, completely text-free, with quiet areas for local headline overlay; small PakWire mark in a corner.",
        "mood": "Serious, credible, premium. Crisp daylight or clean studio tones.",
        "negatives": [
            "NO invented facts, NO sensationalised imagery, NO fake quotes.",
            "NO misspelled text.",
        ],
    },
    "maloomat": {
        "display": "Maloomat",
        "role": "You are a premium infotainment card designer for Maloomat, a Pakistani verified-facts page.",
        "brand": (
            "Colourful premium infotainment style: gold/charcoal with jewel accents. "
            "Slim Maloomat header/footer bands (NOT wide). Bold, modern, scroll-stopping. "
            "One clear visual per fact."
        ),
        "scene_flavor": (
            "One single vivid realistic visual illustrating the fact — a real-photo look, directly on topic."
        ),
        "text_mode": "fact_card",
        "text_extra": "",
        "composition": "Slim bands top/bottom, fact visual center, headline over a quiet area with a soft dark scrim.",
        "mood": "Vibrant, energetic, premium. Jewel-tone accents on a dark charcoal base.",
        "negatives": [
            "Facts must be verified — never invent or embellish facts.",
            "NO misspelled Roman Urdu. NO Arabic script.",
            "NO wide header/footer.",
        ],
    },
    "aangan": {
        "display": "Aangan",
        "role": "You are a warm lifestyle illustrator for Aangan, a Pakistani women's content brand.",
        "brand": (
            "Warm lifestyle aesthetic: warm cream + rosewood + soft copper tones. "
            "Gentle, homely, premium. Soft domestic scenes, tasteful and modest."
        ),
        "scene_flavor": (
            "A warm lifestyle visual for the topic — e.g. a sunlit kitchen corner, a cosy reading nook, "
            "hands arranging fresh flowers. Modest, tasteful, warm."
        ),
        "text_mode": "minimal_text",
        "text_extra": "",
        "composition": "Warm scene with generous quiet space; one short caption line and a small Aangan mark, never crowded.",
        "mood": "Warm, gentle, inviting. Soft natural light, cosy tones.",
        "negatives": ["NO cluttered text, NO loud colours."],
    },
    "angrezi": {
        "display": "Angrezi",
        "role": "You are a clean educational card designer for Angrezi, an English-learning page for Pakistanis.",
        "brand": (
            "Clean educational: ivory + deep navy + friendly amber accent. "
            "Crisp, friendly, classroom-clear. No fixed template — clarity first."
        ),
        "scene_flavor": (
            "A clean educational visual supporting the lesson — e.g. a bright study-desk detail, chalkboard-style "
            "motif, friendly icons around the lesson point."
        ),
        "text_mode": "educational",
        "text_extra": "",
        "composition": "One clear lesson point big and centered with generous white space; support line small beneath.",
        "mood": "Bright, encouraging, focused. Clean daylight tones.",
        "negatives": [
            "English must be dominant and 100% correct — no grammar or spelling slips.",
            "Roman Urdu support in Latin script only.",
        ],
    },
    "parhai": {
        "display": "Parhai",
        "role": "You are a premium study-card designer for Parhai, a Pakistani study-prep page.",
        "brand": (
            "Focused study premium: deep study-navy + paper white + amber highlight. "
            "Clean, organised, motivating. One topic per card."
        ),
        "scene_flavor": (
            "A premium study visual for the topic — e.g. a tidy desk with notebooks, a chalkboard with a neat "
            "diagram motif, soft focus bookshelves."
        ),
        "text_mode": "study_card",
        "text_extra": "",
        "composition": "Title top, key points as a short crisp list, one amber highlight box for the must-remember line.",
        "mood": "Focused, calm, motivating. Soft study-lamp warmth on deep navy.",
        "negatives": ["NO misspelled text. NO cluttered lists."],
    },
    "imtihan": {
        "display": "Imtihan",
        "role": "You are a premium exam-prep card designer for Imtihan, a Pakistani exam-prep page.",
        "brand": (
            "Confident exam premium: exam-blue + paper white + gold accent. "
            "Sharp, high-yield, encouraging. One exam topic per card."
        ),
        "scene_flavor": (
            "A sharp exam-prep visual for the topic — e.g. a clean exam-hall detail, a highlighted formula motif, "
            "a confident study flat-lay."
        ),
        "text_mode": "study_card",
        "text_extra": "",
        "composition": "Title top, key points as a short crisp list, one gold highlight box for the must-remember line.",
        "mood": "Sharp, confident, encouraging. Clean bright tones with gold energy.",
        "negatives": ["NO misspelled text. NO cluttered lists."],
    },
}

TEXT_FREE_RULES = (
    "TEXT RULES (strict, zero tolerance):\n"
    "- TEXT-FREE image. NO text, NO words, NO letters, NO numbers, NO calligraphy-like marks anywhere.\n"
    "- Text is overlaid later by the card builder (PIL). Leave a large quiet center area for the overlay."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pick(seq, index, default=""):
    if isinstance(seq, list) and len(seq) > index:
        val = seq[index]
        return str(val).strip() if val is not None else default
    return default


def _trim(text, limit):
    text = str(text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip() + "..."


def _dossier_lists(dossier):
    facts = dossier.get("facts") or []
    angles = dossier.get("angles") or []
    sources = dossier.get("sources") or []
    avoid = dossier.get("avoid") or []
    facts = [str(x).strip() for x in facts if str(x).strip()]
    angles = [str(x).strip() for x in angles if str(x).strip()]
    sources = [str(x).strip() for x in sources if str(x).strip()]
    avoid = [str(x).strip() for x in avoid if str(x).strip()]
    return facts, angles, sources, avoid


def _load_dossier(niche, idea_id):
    path = os.path.join(WORKSPACE, "niches", niche, "output", "dossier_" + idea_id + ".json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Dossier not found: %s (run research first, or pass dossier= directly)" % path
        )
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("Dossier file is not a JSON object: %s" % path)
    return data


def _check_devanagari(text):
    if DEVANAGARI_RE.search(text):
        raise ValueError(
            "Prompt text contains Devanagari (U+0900-U+097F) — Roman Urdu or English only."
        )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_text_rules(spec, dossier):
    facts, angles, sources, _avoid = _dossier_lists(dossier)
    mode = spec["text_mode"]
    extra = spec.get("text_extra", "").strip()

    if mode == "text_free":
        block = TEXT_FREE_RULES
        if extra:
            block += "\n- " + extra
        return block

    if mode == "meme":
        top = _trim(_pick(facts, 0, _pick(angles, 0, "TBA")), 70)
        bottom = _trim(_pick(facts, 1, _pick(angles, 1, "TBA")), 70)
        return (
            "TEXT RULES:\n"
            "- Render the FULL meme WITH text.\n"
            "- Top text / bottom text in the meme's lane language: Roman Urdu (Latin script) "
            "for the Pakistani lane, English for the English lane. 100% accurate spelling.\n"
            "- Text big, bold, white with black outline, fully legible.\n"
            "EXACT TEXT:\n"
            "TOP: " + top + "\n"
            "BOTTOM: " + bottom
        )

    if mode == "tech_card":
        headline = _trim(_pick(angles, 0, _pick(facts, 0, "TBA")), 70)
        subline = _trim(_pick(facts, 0, _pick(angles, 1, "TBA")), 110)
        return (
            "TEXT RULES:\n"
            "- Render the FULL card WITH text. Text 100% accurate in the idea's lane: "
            "English ideas go English only; Roman Urdu ideas go Roman Urdu Latin script only.\n"
            "- Short intelligent headline + one tiny subline + one small TechSathi mark. "
            "No fixed template — you decide the layout.\n"
            "EXACT TEXT:\n"
            "HEADLINE: " + headline + "\n"
            "SUBLINE: " + subline
        )

    if mode == "riddle":
        lines = facts[:3] if facts else angles[:3]
        riddle = "\n".join(_trim(line, 90) for line in lines) if lines else "TBA"
        return (
            "TEXT RULES:\n"
            "- Render the FULL card WITH text. Riddle text 100% accurate in its lane: "
            "English lane goes English; Roman Urdu lane goes Roman Urdu Latin script.\n"
            "- Short, punchy riddle lines. Small \"Paheli\" mark in a corner. "
            "Answer NEVER on the card.\n"
            "EXACT TEXT:\n"
            "RIDDLE:\n" + riddle
        )

    if mode == "fact_card":
        headline = _trim(_pick(facts, 0, _pick(angles, 0, "TBA")), 90)
        reference = _pick(sources, 0, "TBA")
        return (
            "TEXT RULES:\n"
            "- Render the FULL facts card WITH text. Headline in fully human, natural Roman Urdu "
            "(Latin script only), short and punchy, 100% accurate.\n"
            "- Slim Maloomat header/footer bands. Small source reference line. No Arabic of any kind.\n"
            "EXACT TEXT:\n"
            "HEADLINE: " + headline + "\n"
            "REFERENCE: " + reference
        )

    if mode == "minimal_text":
        caption = _trim(_pick(facts, 0, _pick(angles, 0, "TBA")), 90)
        return (
            "TEXT RULES:\n"
            "- Warm lifestyle visual with MINIMAL text: one short caption line + one small Aangan mark only.\n"
            "- Caption in the idea's lane (English or Roman Urdu, Latin script). 100% accurate spelling.\n"
            "EXACT TEXT:\n"
            "CAPTION: " + caption
        )

    if mode == "educational":
        lesson = _trim(_pick(facts, 0, _pick(angles, 0, "TBA")), 90)
        support = _trim(_pick(facts, 1, _pick(angles, 1, "TBA")), 110)
        return (
            "TEXT RULES:\n"
            "- Render the FULL educational card WITH text. English dominant and 100% correct; "
            "Roman Urdu support in Latin script only.\n"
            "- One clear lesson point, big and legible, generous white space.\n"
            "EXACT TEXT:\n"
            "LESSON: " + lesson + "\n"
            "SUPPORT: " + support
        )

    if mode == "study_card":
        title = _trim(_pick(angles, 0, _pick(facts, 0, "TBA")), 70)
        points = facts[:4] if facts else angles[:4]
        key_points = "\n".join("- " + _trim(p, 100) for p in points) if points else "- TBA"
        highlight = _trim(_pick(facts, 0, "TBA"), 90)
        return (
            "TEXT RULES:\n"
            "- Render the FULL study card WITH text. English-first with Roman Urdu support "
            "(Latin script only). 100% accurate spelling.\n"
            "- Key points as a short crisp list, one highlight box for the must-remember line.\n"
            "EXACT TEXT:\n"
            "TITLE: " + title + "\n"
            "KEY POINTS:\n" + key_points + "\n"
            "MUST REMEMBER: " + highlight
        )

    raise ValueError("Unknown text_mode: %r" % mode)


def _build_scene(spec, dossier):
    facts, angles, sources, avoid = _dossier_lists(dossier)
    lines = ["SCENE / CONTENT:"]
    if angles:
        lines.append("Primary angle: " + angles[0])
    if facts:
        lines.append("Key facts to reflect visually:")
        for fact in facts[:4]:
            lines.append("  - " + fact)
    if sources:
        lines.append("Source reference: " + sources[0])
    if avoid:
        lines.append("Avoid depicting: " + "; ".join(avoid[:4]))
    lines.append("Scene direction: " + spec["scene_flavor"])
    return "\n".join(lines)


def _build_negatives(spec, dossier):
    _facts, _angles, _sources, avoid = _dossier_lists(dossier)
    lines = ["HARD NEGATIVES (never violate):"]
    for neg in UNIVERSAL_NEGATIVES:
        lines.append("- " + neg)
    for neg in spec.get("negatives", []):
        lines.append("- " + neg)
    if avoid:
        lines.append("- Do NOT depict or imply: " + "; ".join(avoid[:4]) + ".")
    return "\n".join(lines)


def _build_output(spec):
    if spec["text_mode"] == "text_free":
        tail = "One square 1080x1080 text-free background, ready for PIL text overlay."
    else:
        tail = "One square 1080x1080 image, full card with exact text, ready to post."
    return "OUTPUT:\n" + GENERATION_SETTINGS + "\n" + tail


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def forge_prompt(niche, idea_id, dossier=None):
    """Compose the 8-section image prompt for a niche + idea.

    Returns {"niche", "idea_id", "generated_at", "sections", "prompt_text"}
    and saves it to workspace/niches/<niche>/output/prompt_<idea_id>.json.
    """
    if niche not in NICHE_SPECS:
        raise ValueError(
            "Unknown niche %r — expected one of: %s" % (niche, ", ".join(NICHE_IDS))
        )
    if not IDEA_ID_RE.match(str(idea_id)):
        raise ValueError(
            "Invalid idea_id %r — use letters, numbers, dashes, underscores (max 80 chars)" % (idea_id,)
        )
    idea_id = str(idea_id)

    spec = NICHE_SPECS[niche]
    if dossier is None:
        dossier = _load_dossier(niche, idea_id)
    if not isinstance(dossier, dict):
        raise ValueError("dossier must be a dict with facts/angles/sources/avoid lists")

    sections = {
        "role": "ROLE:\n" + spec["role"],
        "brand_style_lock": "BRAND STYLE LOCK:\n" + spec["brand"],
        "scene_content": _build_scene(spec, dossier),
        "text_rules": _build_text_rules(spec, dossier),
        "composition": "COMPOSITION:\n" + spec["composition"],
        "lighting_mood": "LIGHTING & MOOD:\n" + spec["mood"],
        "hard_negatives": _build_negatives(spec, dossier),
        "output": _build_output(spec),
    }

    order = [
        "role", "brand_style_lock", "scene_content", "text_rules",
        "composition", "lighting_mood", "hard_negatives", "output",
    ]
    prompt_text = "\n\n".join(sections[key] for key in order)
    _check_devanagari(prompt_text)

    result = {
        "niche": niche,
        "idea_id": idea_id,
        "generated_at": _utc_now(),
        "sections": sections,
        "prompt_text": prompt_text,
    }

    out_dir = os.path.join(WORKSPACE, "niches", niche, "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "prompt_" + idea_id + ".json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    return result


def main(argv):
    import sys
    if len(argv) != 3:
        print("usage: prompts.py <niche> <idea_id>", file=sys.stderr)
        return 2
    result = forge_prompt(argv[1], argv[2])
    out_path = os.path.join(WORKSPACE, "niches", result["niche"], "output",
                            "prompt_" + result["idea_id"] + ".json")
    print("wrote " + out_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
