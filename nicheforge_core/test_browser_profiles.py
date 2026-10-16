"""NicheForge Phase 3 — Profile Vault + Session Monitor tests (plain asserts)."""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "browser_track"))

import profiles  # noqa: E402
import sessions  # noqa: E402

PASS = []


def check(name, cond):
    assert cond, "FAILED: %s" % name
    PASS.append(name)


def make_env():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "t.db")
    profiles_root = os.path.join(tmp, "profiles")
    profiles.init_profile_tables(db)
    return tmp, db, profiles_root


def redirect_profiles_root(monkey):
    old = profiles.PROFILES_ROOT
    profiles.PROFILES_ROOT = monkey
    return old


# ---- profiles.py ----

tmp, db, profiles_root = make_env()
old_root = redirect_profiles_root(profiles_root)

# register idempotent + dir created
r1 = profiles.register_profile(db, "pakwire", "chatgpt", "a@x.com")
r2 = profiles.register_profile(db, "pakwire", "chatgpt", "a@x.com")
check("register returns dict with email", r1["email"] == "a@x.com")
check("register idempotent -> same id", r1["id"] == r2["id"])
check("profile dir created", os.path.isdir(r1["profile_dir"]))
n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM browser_profiles").fetchone()[0]
check("register twice -> one row", n == 1)

# get_profile returns active; paused -> None
g = profiles.get_profile(db, "pakwire", "chatgpt")
check("get_profile returns active row", g is not None and g["email"] == "a@x.com")
profiles.set_status(db, "pakwire", "chatgpt", "a@x.com", "paused")
check("paused -> get_profile None", profiles.get_profile(db, "pakwire", "chatgpt") is None)
check("paused -> get_profile with email None", profiles.get_profile(db, "pakwire", "chatgpt", "a@x.com") is None)
profiles.set_status(db, "pakwire", "chatgpt", "a@x.com", "active")
check("back to active -> found", profiles.get_profile(db, "pakwire", "chatgpt")["email"] == "a@x.com")

# rotation: parked_checker parks email[0]
profiles.register_profile(db, "pakwire", "chatgpt", "b@y.com")
parked = {("chatgpt", "a@x.com")}
nxt = profiles.next_available_profile(db, "pakwire", "chatgpt", lambda s, e: (s, e) in parked)
check("rotation skips parked -> returns b@y.com", nxt is not None and nxt["email"] == "b@y.com")
nxt_none = profiles.next_available_profile(db, "pakwire", "chatgpt", lambda s, e: True)
check("rotation all parked -> None", nxt_none is None)

# sync_accounts_from_config
cfg = {"browser_accounts": {"chatgpt": ["c1@x.com", "c2@x.com"], "claude": ["d@x.com"]}}
synced = profiles.sync_accounts_from_config(db, cfg, "memeistan")
check("sync registers N profiles", len(synced) == 3)
emails = sorted(p["email"] for p in profiles.list_profiles(db, niche="memeistan"))
check("sync emails correct", emails == ["c1@x.com", "c2@x.com", "d@x.com"])
synced2 = profiles.sync_accounts_from_config(db, cfg, "memeistan")
check("sync idempotent", len(synced2) == 3 and all(synced[i]["id"] == synced2[i]["id"] for i in range(3)))
allp = profiles.list_profiles(db)
check("list_profiles unfiltered count", len(allp) == 2 + 3)
check("list_profiles service filter", len(profiles.list_profiles(db, service="claude")) == 1)

# launch_kwargs: no playwright import at top (use real PROFILES_ROOT)
profiles.PROFILES_ROOT = old_root
kw = profiles.launch_kwargs("pakwire")
check("launch_kwargs user_data_dir", kw["user_data_dir"].endswith(os.path.join("workspace", "browser_profiles", "pakwire")))
check("launch_kwargs viewport", kw["viewport"] == {"width": 1366, "height": 900})
check("launch_kwargs locale en-GB", kw["locale"] == "en-GB")
check("launch_kwargs headless False", kw["headless"] is False)
check("no playwright in module attrs", "playwright" not in sys.modules)

profiles.PROFILES_ROOT = old_root

# ---- sessions.py ----

tmp2, db2, root2 = make_env()
old2 = redirect_profiles_root(root2)
profiles.register_profile(db2, "deen", "chatgpt", "s@x.com")
profiles.register_profile(db2, "deen", "claude", "t@x.com")

check("check_login logged-out chatgpt", sessions.check_login("<h1>Log in</h1><a>Sign up</a>", "chatgpt") is False)
check("check_login logged-out claude", sessions.check_login("Welcome back. Log in to continue", "claude") is False)
check("check_login logged-out gemini", sessions.check_login("Sign in to use Gemini", "gemini") is False)
check("check_login logged-in chatgpt", sessions.check_login("New chat | GPT-4 | Search the web", "chatgpt") is True)
check("check_login logged-in claude", sessions.check_login("Welcome to Claude. Start a new conversation.", "claude") is True)
check("check_login logged-in gemini", sessions.check_login("Hello, start chatting with Gemini", "gemini") is True)
check("check_login empty page -> logged in", sessions.check_login("", "chatgpt") is True)

sessions.mark_expired(db2, "deen", "chatgpt", "s@x.com")
p = profiles.get_profile(db2, "deen", "chatgpt")
check("mark_expired flips to expired", p is None)
rows = profiles.list_profiles(db2, niche="deen", service="chatgpt")
check("status is expired", rows[0]["status"] == "expired")
ev = sqlite3.connect(db2).execute(
    "SELECT kind, detail FROM browser_events WHERE kind='session_expired'"
).fetchone()
check("session_expired event logged", ev is not None and ev[1] == "s@x.com")

check("relogin chatgpt", sessions.relogin_url("chatgpt") == "https://chatgpt.com/auth/login")
check("relogin claude", sessions.relogin_url("claude") == "https://claude.ai/login")
check("relogin gemini", sessions.relogin_url("gemini") == "https://gemini.google.com")

rep = sessions.login_status_report(db2)
check("login_status_report shape", len(rep) == 2 and all(
    set(e) == {"niche", "service", "email", "status"} for e in rep))
check("login_status_report values", {e["email"]: e["status"] for e in rep} == {"s@x.com": "expired", "t@x.com": "active"})

profiles.PROFILES_ROOT = old2  # (restored earlier before launch_kwargs tests)

print("ALL %d CHECKS PASSED" % len(PASS))
