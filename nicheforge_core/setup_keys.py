#!/usr/bin/env python3
"""NicheForge key setup -- interactive CLI, run from the repo root.

    python setup_keys.py          # enter keys, writes ENCRYPTED config.json
    python setup_keys.py --check  # verify the master password decrypts config.json

Keys are collected per provider (comma-separated; Enter = skip).
pollinations needs no key. The result is stored ENCRYPTED with your master
password -- the file on disk contains no readable secrets.
"""

import getpass
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from providers import decrypt_config, encrypt_config  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, "config.json")

PROMPT_ORDER = [
    ("gemini", "Gemini (Google AI Studio)"),
    ("groq", "Groq (console.groq.com)"),
    ("nvidia", "NVIDIA NIM (build.nvidia.com)"),
    ("openrouter", "OpenRouter (openrouter.ai, :free models)"),
    ("zai", "Z.ai GLM Flash (z.ai)"),
]

BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "pollinations": "https://text.pollinations.ai/openai",
    "zai": "https://api.z.ai/api/paas/v4",
}

MODELS = {
    "gemini": ["gemini-2.5-flash"],
    "groq": ["llama-3.3-70b-versatile"],
    "nvidia": ["meta/llama-3.3-70b-instruct"],
    "openrouter": ["meta-llama/llama-3.3-70b-instruct:free"],
    "pollinations": ["openai"],
    "zai": ["glm-4.5-flash"],
}


def ask_password(confirm: bool = False) -> str:
    pw = getpass.getpass("Master password: ")
    if confirm:
        pw2 = getpass.getpass("Confirm master password: ")
        if pw != pw2:
            print("Passwords do not match. Aborting.")
            sys.exit(1)
    if not pw:
        print("Password must not be empty. Aborting.")
        sys.exit(1)
    return pw


def do_check() -> None:
    if not os.path.exists(CONFIG_PATH):
        print(f"No {CONFIG_PATH} found. Run `python setup_keys.py` first.")
        sys.exit(1)
    pw = ask_password()
    try:
        with open(CONFIG_PATH, "rb") as fh:
            config = decrypt_config(fh.read(), pw)
    except ValueError as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)
    names = [p.get("name") for p in config.get("providers", [])]
    with_keys = sum(1 for p in config.get("providers", []) if p.get("keys"))
    print(f"OK: config.json decrypted. Providers: {', '.join(names)}.")
    print(f"Providers with keys configured: {with_keys}.")
    fb_pages = config.get("facebook_pages", [])
    labels = [p.get("label") for p in fb_pages if p.get("label")]
    print(f"Facebook pages: {len(fb_pages)} configured"
          + (f" ({', '.join(labels)})" if labels else "") + ".")
    browser_accounts = config.get("browser_accounts", {}) or {}
    n_emails = sum(len(v) for v in browser_accounts.values() if isinstance(v, list))
    print(f"Browser-track accounts: {n_emails} email(s) across "
          f"{len(browser_accounts)} service(s).")


def ask_facebook_pages() -> list:
    """Interactively collect Facebook Page credentials.

    Returns a list of {"label", "page_id", "token"} dicts. Tokens are never
    printed back; only the last 4 characters are echoed for confirmation.
    """
    pages = []
    add = input("\nAdd Facebook Pages? (y/N): ").strip().lower()
    while add in ("y", "yes"):
        label = input("Page label (e.g. wicketverse): ").strip()
        if not label:
            print("Label is required; skipping this page.")
        else:
            page_id = input(f"Page ID for '{label}': ").strip()
            token = getpass.getpass(f"Page access token for '{label}': ").strip()
            if not page_id or not token:
                print("Page ID and token are both required; skipping this page.")
            else:
                pages.append({"label": label, "page_id": page_id, "token": token})
                masked = "***" + token[-4:] if len(token) > 4 else "****"
                print(f"Added page '{label}' (token ending {masked}).")
        add = input("Add another Facebook Page? (y/N): ").strip().lower()
    return pages


def ask_browser_accounts() -> dict:
    """Collect login emails per AI service for the Phase-3 browser track.

    Returns {"chatgpt": [...], "claude": [...], "gemini": [...]}. Emails are
    not secrets, but they live in the encrypted config alongside the keys.
    """
    accounts = {}
    add = input("\nAdd browser-track login emails? (y/N): ").strip().lower()
    if add not in ("y", "yes"):
        return accounts
    for service in ("chatgpt", "claude", "gemini"):
        raw = input(f"{service} login email(s), comma-separated (Enter to skip): ").strip()
        emails = [e.strip() for e in raw.split(",") if e.strip()]
        if emails:
            accounts[service] = emails
    return accounts


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        do_check()
        return

    print("NicheForge key setup")
    print("====================")
    print("Enter API keys for each provider (comma-separated for multiple).")
    print("Press Enter to skip a provider. Pollinations needs no key.\n")

    providers = []
    for name, label in PROMPT_ORDER:
        raw = input(f"{label} API key(s): ").strip()
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        providers.append({
            "name": name,
            "base_url": BASE_URLS[name],
            "models": MODELS[name],
            "keys": keys,
        })
    providers.append({
        "name": "pollinations",
        "base_url": BASE_URLS["pollinations"],
        "models": MODELS["pollinations"],
        "keys": [],
    })

    pw = ask_password(confirm=True)
    # MERGE-SAFE: never wipe existing config. Load it first (if present and
    # the password decrypts it), then only update what the user re-entered.
    existing = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "rb") as fh:
                existing = decrypt_config(fh.read(), pw)
            print("(existing config loaded -- your pages/accounts are kept)")
        except Exception:
            print("(existing config.json could not be decrypted; starting fresh)")
            existing = {}

    config = {"providers": providers}
    # facebook_pages: keep existing unless the user adds new ones now
    new_pages = ask_facebook_pages()
    old_pages = existing.get("facebook_pages", []) or []
    labels_new = {p.get("label") for p in new_pages}
    config["facebook_pages"] = ([p for p in old_pages if p.get("label") not in labels_new]
                                + new_pages)
    # browser_accounts: merge per service
    new_accounts = ask_browser_accounts()
    merged_accounts = dict(existing.get("browser_accounts", {}) or {})
    for svc, emails in new_accounts.items():
        merged = list(dict.fromkeys((merged_accounts.get(svc) or []) + emails))
        merged_accounts[svc] = merged
    config["browser_accounts"] = merged_accounts
    # preserve any other keys the config may carry
    for k, v in existing.items():
        if k not in config:
            config[k] = v
    blob = encrypt_config(config, pw)
    with open(CONFIG_PATH, "wb") as fh:
        fh.write(blob)
    os.chmod(CONFIG_PATH, 0o600)

    total_keys = sum(len(p["keys"]) for p in providers)
    print(f"\nDone: {CONFIG_PATH} written (encrypted, {len(blob)} bytes).")
    print(f"{total_keys} key(s) stored across {len(providers)} providers.")
    print("Verify anytime with: python setup_keys.py --check")
    print("Keep your master password safe -- it cannot be recovered.")


if __name__ == "__main__":
    main()
