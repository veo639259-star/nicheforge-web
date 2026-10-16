#!/usr/bin/env python3
"""Phase 2 end-to-end test.

dossier -> caption -> prompt -> overlay -> schedule -> publish(dry-run),
using a fake KeyLadder and temp dirs. Cleans up after itself.
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = "/home/hatch/workspace/nicheforge"
sys.path.insert(0, ROOT)

import db
import research
import captions
import prompts
import overlay
import schedule
import publish

tmp = tempfile.mkdtemp(prefix="nf-e2e-")
try:
    db_path = os.path.join(tmp, "e2e.db")
    out_root = Path(tmp) / "niches"
    (out_root / "deen" / "output").mkdir(parents=True)

    # Redirect module output roots to temp dir
    research.OUTPUT_ROOT = out_root
    captions.OUTPUT_ROOT = out_root
    prompts.WORKSPACE = str(Path(tmp))

    db.init_db(db_path)
    schedule.init_schedule_tables(db_path)
    publish.init_publish_tables(db_path)

    class FakeLadder:
        def chat(self, messages, system=None, timeout=60, max_tokens=1024):
            content = " ".join(m.get("content", "") for m in (messages or []))
            if '"facts"' in content:
                text = json.dumps({
                    "facts": ["Patience is a virtue in Islam."],
                    "angles": ["emotional reminder"],
                    "sources": ["maarifulquran.net"],
                    "avoid": ["arabic text"]})
            else:
                text = ("Sabr ka phal meetha hota hai. Mushkil waqt mein sabr "
                        "ka daaman thaame rakho. #Deen #Sabr #IslamicReminder")
            return {"provider": "fake", "model": "fake", "text": text,
                    "tokens_in": 10, "tokens_out": 20}

    ladder = FakeLadder()

    # 1. idea -> approved
    ok, info = db.add_idea(db_path, "deen", "Sabr par yaad-dihani",
                           "Patience reminder card")
    assert ok, info
    idea_id = int(re.search(r"#(\d+)", info).group(1))
    assert db.set_status(db_path, idea_id, "approved")
    print("1. idea approved: #%d" % idea_id)

    # 2. dossier
    dossier = research.build_dossier("deen", str(idea_id),
                                     "Sabr par yaad-dihani",
                                     "Patience reminder card", ladder)
    assert {"facts", "angles", "sources", "avoid"} <= set(dossier)
    assert (out_root / "deen" / "output" /
            ("dossier_%d.json" % idea_id)).is_file()
    print("2. dossier built")

    # 3. caption
    cap = captions.make_caption("deen", str(idea_id), dossier, ladder)
    assert len(cap) > 10 and "#" in cap
    assert (out_root / "deen" / "output" /
            ("caption_%d.txt" % idea_id)).is_file()
    print("3. caption generated (%d chars)" % len(cap))

    # 4. prompt
    pr = prompts.forge_prompt("deen", str(idea_id), dossier)
    assert len(pr["sections"]) == 8, pr["sections"].keys()
    assert "TEXT-FREE" in pr["prompt_text"]
    print("4. prompt forged (8 sections, text-free)")

    # 5. overlay
    base = os.path.join(tmp, "base.png")
    Image.new("RGB", (1080, 1080), (15, 25, 30)).save(base)
    final = overlay.overlay_urdu(
        base, "deen", ["صبر کا پھل میٹھا ہوتا ہے"],
        attribution="صحیح بخاری",
        output_path=os.path.join(tmp, "final.png"))
    assert Image.open(final).size == (1080, 1080)
    print("5. overlay rendered 1080x1080")

    # 6. schedule
    res = schedule.plan_day(db_path, "2026-10-16")
    assert len(res["placed"]) == 1, res
    assert res["placed"][0]["slot_pkt"].startswith("2026-10-16T")
    assert schedule.detect_clashes(db_path, "2026-10-16") == []
    print("6. scheduled at %s, no clashes" % res["placed"][0]["slot_pkt"])

    # 7. publish dry-run (no network)
    cfg = {"providers": [],
           "facebook_pages": [{"label": "deen-test", "page_id": "123",
                               "token": "TEST_XYZ"}]}
    pub = publish.FBPublisher(cfg, db_path, dry_run=True)
    r = pub.publish_photo("deen-test", final, cap)
    assert r.get("dry_run") is True, r
    print("7. publish dry-run OK (no network touched)")

    print("E2E ALL PASS")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
