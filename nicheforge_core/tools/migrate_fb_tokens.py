#!/usr/bin/env python3
"""One-time migration: wire Hmb's Facebook Page tokens into NicheForge.

Reads page tokens from the pakwire-automation config.yaml (or --source),
maps each of the 14 niches to its Page ID, and merges them into NicheForge's
ENCRYPTED config.json as config["facebook_pages"] = [{label, page_id, token}].

Token values are NEVER printed -- only masked (last 4 chars) + counts.

Usage:
    python tools/migrate_fb_tokens.py                      # prompts for password
    NICHEFORGE_PASSWORD=... python tools/migrate_fb_tokens.py
    python tools/migrate_fb_tokens.py --source /path/to/config.yaml

On a fresh config.json the script also writes the master password to
.master-password (chmod 600) so start.bat/start.sh can load it automatically.
"""

import argparse
import getpass
import os
import secrets
import stat
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from providers import decrypt_config, encrypt_config  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, "config.json")
PW_FILE = os.path.join(ROOT, ".master-password")
DEFAULT_SOURCE = os.path.expanduser("~/workspace/pakwire-automation/config.yaml")

# niche -> Facebook Page ID (verified 2026-10-15)
NICHE_PAGES = {
    "wicketverse": "1393939310461438",
    "pakwire": "1277639115440417",
    "maloomat": "1256014214272998",
    "sukhan": "1401002836423214",
    "paheli": "665093340027314",
    "memeistan": "1393556600496928",
    "lafz": "1402344029620035",
    "deen": "1386735381183555",
    "parhai": "1339231275942959",
    "aangan": "1301382046399565",
    "angrezi": "1371657899362002",
    "techsathi": "1427670527077729",
    "imtihan": "1322974327571754",
    "marvelverse": "1387200894469635",
}


def masked(token):
    return "***" + token[-4:] if len(token) > 4 else "****"


def load_source_tokens(path):
    """Return {page_id: token} from the source yaml. Never logs values."""
    try:
        import yaml
    except ImportError:
        print("PyYAML not installed; run: pip install pyyaml")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    pages = (data.get("facebook") or {}).get("pages") or []
    out = {}
    for p in pages:
        pid = str(p.get("id") or p.get("page_id") or "").strip()
        tok = (p.get("token") or "").strip()
        if pid and tok:
            out[pid] = tok
    return out


def get_password():
    pw = os.environ.get("NICHEFORGE_PASSWORD")
    if pw:
        return pw
    return getpass.getpass("Master password for NicheForge config: ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    args = ap.parse_args()

    tokens = load_source_tokens(args.source)
    print(f"Source: {len(tokens)} page tokens found.")

    entries, missing = [], []
    for niche, pid in NICHE_PAGES.items():
        tok = tokens.get(pid)
        if tok:
            entries.append({"label": niche, "page_id": pid, "token": tok})
        else:
            missing.append(niche)
    for e in entries:
        print(f"  + {e['label']:12s} page {e['page_id']} token {masked(e['token'])}")
    if missing:
        print(f"  ! missing tokens for: {', '.join(missing)}")

    pw = get_password()
    fresh = not os.path.exists(CONFIG_PATH)
    if fresh:
        config = {"providers": [], "facebook_pages": [], "browser_accounts": {}}
    else:
        with open(CONFIG_PATH, "rb") as fh:
            config = decrypt_config(fh.read(), pw)

    # merge: replace same-label entries, keep everything else
    existing = [p for p in config.get("facebook_pages", [])
                if p.get("label") not in NICHE_PAGES]
    config["facebook_pages"] = existing + entries

    blob = encrypt_config(config, pw)
    with open(CONFIG_PATH, "wb") as fh:
        fh.write(blob)
    os.chmod(CONFIG_PATH, 0o600)
    print(f"\nWrote {CONFIG_PATH} ({len(blob)} bytes, encrypted). "
          f"{len(entries)} niche pages ready.")

    if fresh and not os.path.exists(PW_FILE):
        with open(PW_FILE, "w", encoding="utf-8") as fh:
            fh.write(pw)
        os.chmod(PW_FILE, 0o600)
        print("Master password saved to .master-password (chmod 600) "
              "so start.bat/start.sh can load it automatically.")

    # verify round-trip
    check = decrypt_config(blob, pw)
    got = {p["label"] for p in check.get("facebook_pages", [])}
    assert set(NICHE_PAGES) - set(missing) <= got, "round-trip mismatch"
    print("Round-trip decrypt verified.")


if __name__ == "__main__":
    main()
