#!/usr/bin/env python3
"""Tests for NicheForge Urdu Overlay Studio (overlay.py)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overlay as ov
from PIL import Image

BASE = tempfile.mkdtemp(prefix="overlay-test-")

VERSES = {
    "deen": ["علم حاصل کرو چاہے چین جانا پڑے", "کیونکہ علم ہر مسلمان پر فرض ہے"],
    "sukhan": ["ہزاروں خواہشیں ایسی کہ ہر خواہش پہ دم نکلے",
               "بہت نکلے مرے ارمان لیکن پھر بھی کم نکلے"],
    "lafz": ["دل ناامید تو نہیں ناکام ہی تو ہے",
             "لمبی ہے غم کی شام مگر شام ہی تو ہے"],
}
ATTRS = {"deen": "حدیثِ نبوی ﷺ", "sukhan": "مرزا غالب", "lafz": "فیض احمد فیض"}


def make_base(path, colour):
    Image.new("RGB", (1080, 1080), colour).save(path)


def test_each_niche():
    colours = [(10, 20, 30), (20, 30, 25), (30, 25, 20)]
    for niche, colour in zip(["deen", "sukhan", "lafz"], colours):
        base = os.path.join(BASE, f"base-{niche}.png")
        out = os.path.join(BASE, f"out-{niche}.png")
        make_base(base, colour)
        got = ov.overlay_urdu(base, niche, VERSES[niche], output_path=out,
                              attribution=ATTRS[niche])
        assert os.path.isfile(got), f"{niche}: output missing"
        im = Image.open(got)
        assert im.size == (1080, 1080), f"{niche}: size {im.size}"
        print(f"PASS {niche}: {got} {im.size}")


def test_jpeg_output():
    base = os.path.join(BASE, "base-jpg.png")
    out = os.path.join(BASE, "out-sukhan.jpg")
    make_base(base, (15, 25, 22))
    got = ov.overlay_urdu(base, "sukhan", VERSES["sukhan"], output_path=out)
    im = Image.open(got)
    assert im.size == (1080, 1080) and im.format == "JPEG", im.format
    print(f"PASS jpeg: {got}")


def test_niche_guard():
    for niche in ["wicketverse", "maloomat", "memistan", "angrezi", ""]:
        try:
            ov.overlay_urdu("x.png", niche, ["ٹیسٹ"])
        except ValueError:
            print(f"PASS niche guard: {niche!r} -> ValueError")
        else:
            raise AssertionError(f"niche guard failed for {niche!r}")
    try:
        ov.list_overlays("wicketverse")
    except ValueError:
        print("PASS list_overlays guard")
    else:
        raise AssertionError("list_overlays guard failed")


def test_missing_base():
    try:
        ov.overlay_urdu(os.path.join(BASE, "nope.png"), "deen", ["ٹیسٹ"])
    except FileNotFoundError:
        print("PASS missing base -> FileNotFoundError")
    else:
        raise AssertionError("missing base guard failed")


def test_devanagari_rejected():
    base = os.path.join(BASE, "base-dev.png")
    make_base(base, (10, 20, 30))
    try:
        ov.overlay_urdu(base, "deen", ["यह हिंदी है"])
    except ValueError:
        print("PASS devanagari lines -> ValueError")
    else:
        raise AssertionError("devanagari line guard failed")
    try:
        ov.overlay_urdu(base, "deen", ["ٹیسٹ"], attribution="कवि")
    except ValueError:
        print("PASS devanagari attribution -> ValueError")
    else:
        raise AssertionError("devanagari attribution guard failed")


def test_list_overlays():
    # default output path exercise: no explicit output_path
    base = os.path.join(BASE, "listme.png")
    make_base(base, (12, 18, 16))
    got = ov.overlay_urdu(base, "lafz", VERSES["lafz"])
    assert got.startswith(os.path.join(os.path.expanduser("~"), "workspace",
                                       "nicheforge", "workspace", "niches",
                                       "lafz", "output"))
    finals = ov.list_overlays("lafz")
    assert "listme-final.png" in finals, finals
    assert ov.list_overlays("deen") == []
    print(f"PASS list_overlays: default={got}")


if __name__ == "__main__":
    test_each_niche()
    test_jpeg_output()
    test_niche_guard()
    test_missing_base()
    test_devanagari_rejected()
    test_list_overlays()
    print("ALL TESTS PASSED")
