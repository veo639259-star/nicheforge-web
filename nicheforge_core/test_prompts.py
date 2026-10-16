#!/usr/bin/env python3
"""Tests for NicheForge Prompt Forge (prompts.py).

Run:  python3 test_prompts.py
Plain asserts — no pytest dependency. Exits non-zero on first failure.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prompts

PASS = 0


def check(name, condition):
    global PASS
    assert condition, "FAIL: " + name
    PASS += 1
    print("ok - " + name)


SAMPLE_DOSSIER = {
    "facts": [
        "Sheikhupura fort was built during the Mughal era and still stands today.",
        "Local guides say the fort walls are over four hundred years old.",
    ],
    "angles": ["A dusk shot of the old fort walls with a storytelling angle."],
    "sources": ["Punjab tourism archive"],
    "avoid": ["modern skyscrapers", "crowds"],
}

EXPECTED_SECTIONS = [
    "role", "brand_style_lock", "scene_content", "text_rules",
    "composition", "lighting_mood", "hard_negatives", "output",
]

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def main():
    # 1. Forge for all 14 niches with a sample dossier.
    for niche in prompts.NICHE_IDS:
        idea_id = "test-idea-01"
        result = prompts.forge_prompt(niche, idea_id, dossier=SAMPLE_DOSSIER)

        check(niche + ": returns dict with niche/idea_id", (
            result["niche"] == niche and result["idea_id"] == idea_id
        ))
        check(niche + ": all 8 sections present", (
            isinstance(result["sections"], dict)
            and all(k in result["sections"] for k in EXPECTED_SECTIONS)
        ))
        check(niche + ": prompt_text composes all sections", all(
            result["sections"][k] in result["prompt_text"] for k in EXPECTED_SECTIONS
        ))
        check(niche + ": no Devanagari in prompt text",
              not DEVANAGARI_RE.search(result["prompt_text"]))
        check(niche + ": dossier facts woven into scene", (
            "Sheikhupura fort" in result["sections"]["scene_content"]
        ))
        check(niche + ": dossier avoid list in hard negatives", (
            "modern skyscrapers" in result["sections"]["hard_negatives"]
        ))

        if niche in prompts.TEXT_FREE_NICHES:
            check(niche + ": text-free niche prompt contains TEXT-FREE",
                  "TEXT-FREE" in result["prompt_text"])

        # Output file written and reloadable.
        out_path = os.path.join(
            prompts.WORKSPACE, "niches", niche, "output",
            "prompt_" + idea_id + ".json",
        )
        check(niche + ": output file written", os.path.exists(out_path))
        with open(out_path, encoding="utf-8") as fh:
            saved = json.load(fh)
        check(niche + ": saved file matches result", (
            saved["prompt_text"] == result["prompt_text"]
            and saved["sections"] == result["sections"]
        ))

    # 2. MarvelVerse hard negative: no faces / actors / characters / likenesses.
    mv = prompts.forge_prompt("marvelverse", "test-mv-01", dossier=SAMPLE_DOSSIER)
    check("marvelverse: no-faces hard negative",
          "NO faces" in mv["sections"]["hard_negatives"]
          and "NO actors" in mv["sections"]["hard_negatives"]
          and "NO character likenesses" in mv["sections"]["hard_negatives"])

    # 3. Unknown niche -> ValueError.
    try:
        prompts.forge_prompt("notaniche", "x", dossier=SAMPLE_DOSSIER)
        raise AssertionError("FAIL: unknown niche did not raise ValueError")
    except ValueError:
        check("unknown niche raises ValueError", True)

    # 4. Invalid idea_id -> ValueError.
    for bad in ["../evil", "a/b", "", "x" * 81, "idea id"]:
        try:
            prompts.forge_prompt("deen", bad, dossier=SAMPLE_DOSSIER)
            raise AssertionError("FAIL: bad idea_id %r did not raise" % bad)
        except ValueError:
            pass
    check("invalid idea_id raises ValueError", True)

    # 5. Dossier loaded from file when dossier=None.
    niche, idea_id = "paheli", "test-fileload-01"
    dos_path = os.path.join(
        prompts.WORKSPACE, "niches", niche, "output", "dossier_" + idea_id + ".json")
    os.makedirs(os.path.dirname(dos_path), exist_ok=True)
    with open(dos_path, "w", encoding="utf-8") as fh:
        json.dump(SAMPLE_DOSSIER, fh)
    loaded = prompts.forge_prompt(niche, idea_id)
    check("dossier=None loads dossier file from workspace",
          "Sheikhupura fort" in loaded["sections"]["scene_content"])

    # 6. Missing dossier file -> FileNotFoundError.
    try:
        prompts.forge_prompt("paheli", "test-missing-99")
        raise AssertionError("FAIL: missing dossier did not raise FileNotFoundError")
    except FileNotFoundError:
        check("missing dossier file raises FileNotFoundError", True)

    # 7. Devanagari in dossier -> ValueError (Roman Urdu / English only).
    bad_dossier = {
        "facts": ["\u092f\u0939 \u091f\u0947\u0938\u094d\u091f \u0939\u0948"],
        "angles": [], "sources": [], "avoid": [],
    }
    try:
        prompts.forge_prompt("deen", "test-deva-01", dossier=bad_dossier)
        raise AssertionError("FAIL: Devanagari dossier did not raise ValueError")
    except ValueError:
        check("Devanagari in dossier raises ValueError", True)

    # 8. Full-text niches render exact-text blocks.
    meme = prompts.forge_prompt("memeistan", "test-meme-01", dossier=SAMPLE_DOSSIER)
    check("memeistan: EXACT TEXT top/bottom block",
          "TOP:" in meme["sections"]["text_rules"] and "BOTTOM:" in meme["sections"]["text_rules"])
    paheli = prompts.forge_prompt("paheli", "test-paheli-01", dossier=SAMPLE_DOSSIER)
    check("paheli: answer NEVER on card",
          "Answer NEVER on the card" in paheli["sections"]["text_rules"])
    tech = prompts.forge_prompt("techsathi", "test-tech-01", dossier=SAMPLE_DOSSIER)
    check("techsathi: headline + subline + mark",
          "HEADLINE:" in tech["sections"]["text_rules"]
          and "SUBLINE:" in tech["sections"]["text_rules"]
          and "TechSathi mark" in tech["sections"]["text_rules"])

    print("\nALL %d CHECKS PASSED" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
