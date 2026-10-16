"""test_phase2_text.py -- Phase-2 (research.py + captions.py) tests.

Uses a FAKE KeyLadder stub (no network, no keys). Run with:
    python test_phase2_text.py
Exits non-zero on the first failure.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import captions
import research

REPO_ROOT = Path(__file__).resolve().parent


class FakeLadder:
    """Stub with the KeyLadder .chat interface; returns canned replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, system=None, timeout=60, max_tokens=1024):
        self.calls.append({
            "messages": messages, "system": system,
            "timeout": timeout, "max_tokens": max_tokens,
        })
        if not self.replies:
            raise RuntimeError("FakeLadder exhausted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {
            "provider": "fake", "model": "fake-1",
            "text": reply, "tokens_in": 10, "tokens_out": 20,
        }


DOSSIER_JSON = json.dumps({
    "facts": ["Lahore's metro line carries 200,000 riders daily."],
    "angles": ["commuter impact", "expansion plans"],
    "sources": ["PakWire desk"],
    "avoid": ["unverified ridership claims"],
})


def check(name, fn):
    try:
        fn()
    except AssertionError as exc:
        print(f"FAIL: {name}: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {name}: unexpected {type(exc).__name__}: {exc}")
        return False
    print(f"PASS: {name}")
    return True


def main():
    tmp = Path(tempfile.mkdtemp(prefix="nicheforge_phase2_"))
    old_r, old_c = research.OUTPUT_ROOT, captions.OUTPUT_ROOT
    research.OUTPUT_ROOT = tmp
    captions.OUTPUT_ROOT = tmp
    failures = 0

    try:
        # 1. dossier JSON parsing + file write
        def t_dossier_basic():
            ladder = FakeLadder([DOSSIER_JSON])
            d = research.build_dossier("pakwire", "T001", "Metro story",
                                       "about ridership", ladder)
            assert d["facts"] == ["Lahore's metro line carries 200,000 riders daily."]
            path = tmp / "pakwire" / "output" / "dossier_T001.json"
            assert path.exists(), "dossier file not written"
            assert json.loads(path.read_text(encoding="utf-8")) == d
            assert ladder.calls[0]["system"].startswith("You are the content assistant")
        if not check("dossier JSON parse + file write", t_dossier_basic):
            failures += 1

        # 2. dossier JSON wrapped in markdown fences
        def t_dossier_fences():
            ladder = FakeLadder(["```json\n" + DOSSIER_JSON + "\n```"])
            d = research.build_dossier("pakwire", "T002", "x", "y", ladder)
            assert d["sources"] == ["PakWire desk"]
        if not check("dossier parses inside markdown fences", t_dossier_fences):
            failures += 1

        # 3. Devanagari guard trips on नमस्ते (research path)
        def t_dev_research():
            ladder = FakeLadder(['{"facts": ["नमस्ते"], "angles": [],'
                                 ' "sources": [], "avoid": []}'])
            try:
                research.build_dossier("pakwire", "T003", "x", "y", ladder)
            except ValueError as exc:
                assert str(exc) == "devanagari detected"
            else:
                raise AssertionError("ValueError not raised for Devanagari")
        if not check("devanagari guard trips on research ('नमस्ते')", t_dev_research):
            failures += 1

        # 4. caption file write + return value
        def t_caption():
            dossier = json.loads(DOSSIER_JSON)
            text = "Big day for Lahore commuters! Metro hits 200k riders. #Lahore #Metro"
            ladder = FakeLadder([text])
            out = captions.make_caption("pakwire", "T004", dossier, ladder)
            assert out == text
            path = tmp / "pakwire" / "output" / "caption_T004.txt"
            assert path.exists(), "caption file not written"
            assert path.read_text(encoding="utf-8") == text
        if not check("caption file write + return", t_caption):
            failures += 1

        # 5. Devanagari guard trips on नमस्ते (captions path)
        def t_dev_caption():
            ladder = FakeLadder(["नमस्ते, caption text"])
            try:
                captions.make_caption("pakwire", "T005", {"facts": []}, ladder)
            except ValueError as exc:
                assert str(exc) == "devanagari detected"
            else:
                raise AssertionError("ValueError not raised for Devanagari")
        if not check("devanagari guard trips on caption ('नमस्ते')", t_dev_caption):
            failures += 1

        # 6. ladder None -> RuntimeError (no fabrication)
        def t_no_ladder():
            for fn in (lambda: research.build_dossier("pakwire", "T006", "x", "y", None),
                       lambda: captions.make_caption("pakwire", "T006", {}, None)):
                try:
                    fn()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("RuntimeError not raised for None ladder")
        if not check("None ladder raises RuntimeError", t_no_ladder):
            failures += 1

        # 7. ladder failure -> RuntimeError with context
        def t_ladder_failure():
            ladder = FakeLadder([RuntimeError("all providers failed")])
            try:
                research.build_dossier("pakwire", "T007", "x", "y", ladder)
            except RuntimeError as exc:
                assert "T007" in str(exc)
            else:
                raise AssertionError("RuntimeError not raised on ladder failure")
        if not check("ladder failure raises RuntimeError with context", t_ladder_failure):
            failures += 1

        # 8. invalid JSON -> RuntimeError
        def t_bad_json():
            ladder = FakeLadder(["this is not json at all"])
            try:
                research.build_dossier("pakwire", "T008", "x", "y", ladder)
            except RuntimeError:
                pass
            else:
                raise AssertionError("RuntimeError not raised for invalid JSON")
        if not check("invalid JSON raises RuntimeError", t_bad_json):
            failures += 1

        # 9. missing required keys -> RuntimeError
        def t_missing_keys():
            ladder = FakeLadder(['{"facts": [], "angles": []}'])
            try:
                research.build_dossier("pakwire", "T009", "x", "y", ladder)
            except RuntimeError as exc:
                assert "sources" in str(exc)
            else:
                raise AssertionError("RuntimeError not raised for missing keys")
        if not check("missing dossier keys raise RuntimeError", t_missing_keys):
            failures += 1

        # 10. unknown niche -> RuntimeError
        def t_bad_niche():
            try:
                research.build_dossier("nosuchniche", "T010", "x", "y", FakeLadder([]))
            except RuntimeError:
                pass
            else:
                raise AssertionError("RuntimeError not raised for unknown niche")
        if not check("unknown niche raises RuntimeError", t_bad_niche):
            failures += 1

        # 11. grounding brief carries the grounded flag for pakwire
        def t_grounding():
            ladder = FakeLadder([DOSSIER_JSON])
            research.build_dossier("pakwire", "T011", "x", "y", ladder)
            user_text = ladder.calls[0]["messages"][0]["content"]
            assert "web-grounded, source-backed facts" in user_text
        if not check("grounded niche gets grounding line in brief", t_grounding):
            failures += 1
    finally:
        research.OUTPUT_ROOT = old_r
        captions.OUTPUT_ROOT = old_c
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{11 - failures}/11 tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
