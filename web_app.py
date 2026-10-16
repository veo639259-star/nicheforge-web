"""NicheForge Web — deploy-ready entry point.

Wraps the local NicheForge Flask app (nicheforge_core/) and adds:
  * /admin — flagship admin panel (dashboard, batches, image studio,
    gallery, schedule, browser apps, chatbot, errors, keys)
  * global error hook: any unhandled pipeline exception is logged to the
    DB + error_logs/ + hidden_files/alerts.jsonl (Jarvis's monitor)

Run locally:  python web_app.py   ->  http://127.0.0.1:5057/
Deploy:       gunicorn web_app:app  (see Procfile / railway.json)
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(ROOT, "nicheforge_core")
sys.path.insert(0, CORE_DIR)   # core modules: db, research, captions, ...
sys.path.insert(0, ROOT)       # web modules: error_report, chatbot, ...

import error_report
import imagegen as imagegen_mod
import browser_apps as browser_mod

import app as core_app_mod  # noqa: E402  (needs sys.path first)

app = core_app_mod.app
DB_PATH = core_app_mod.DB_PATH
app.config["NF_DB_PATH"] = DB_PATH

# Sessions (admin login + chat history) need a secret key. The local core app
# never set one; derive a stable default so sessions survive restarts.
import hashlib  # noqa: E402
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or hashlib.sha256(
    ("nicheforge-web|" + os.environ.get("NICHEFORGE_ADMIN_PASSWORD",
                                        "local-dev")).encode()).hexdigest()

# --- admin tables (idempotent) -------------------------------------------
error_report.init_error_tables(DB_PATH)
imagegen_mod.init_imagegen_tables(DB_PATH)
browser_mod.init_browser_tables(DB_PATH)

# --- workspace skeleton (fresh deploys) -----------------------------------
for niche in ["wicketverse", "pakwire", "maloomat", "sukhan", "paheli",
              "memeistan", "lafz", "deen", "parhai", "aangan", "angrezi",
              "techsathi", "imtihan", "marvelverse"]:
    for sub in ("assets", "output"):
        os.makedirs(os.path.join(CORE_DIR, "workspace", "niches", niche, sub),
                    exist_ok=True)

# --- admin blueprint -------------------------------------------------------
from admin.admin_bp import admin_bp  # noqa: E402
app.register_blueprint(admin_bp, url_prefix="/admin")


@app.context_processor
def _inject_admin_badges():
    try:
        errs = error_report.list_errors(DB_PATH, status="open", limit=1)
        # cheap count without fetching all
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM nf_errors WHERE status='open'").fetchone()[0]
        finally:
            conn.close()
        return {"open_errors": n}
    except Exception:
        return {"open_errors": 0}


# --- global error hook: every unhandled exception -> alerts ---------------
from flask import got_request_exception, request  # noqa: E402


def _on_request_exception(sender, exception, **extra):
    try:
        niche = request.values.get("niche") or "global"
        try:
            j = request.get_json(silent=True) or {}
            niche = j.get("niche") or niche
        except Exception:
            pass
        stage = (request.endpoint or request.path or "unknown")[:120]
        error_report.log_error(DB_PATH, niche=niche, stage=stage,
                               exc=exception)
    except Exception:
        pass  # the hook itself must never break the response


got_request_exception.connect(_on_request_exception, app)


@app.route("/healthz")
def healthz():
    return {"ok": True, "app": "nicheforge-web"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5057"))
    app.run(host="0.0.0.0", port=port, debug=False)
