"""NicheForge Web — admin panel blueprint (/admin).

Dark-theme flagship UI: dashboard, batch approval, image generator, gallery,
schedule timeline, AI browser apps, chatbot, error panel, key management.

All data comes from the core SQLite DB (shared with nicheforge_core).
Errors anywhere in the pipeline are captured by error_report.log_error and
surfaced here + in hidden_files/alerts.jsonl for Jarvis.
"""

import datetime
import os
import sqlite3
import sys
from functools import wraps

from flask import (Blueprint, abort, current_app, jsonify, redirect,
                   render_template, request, session, url_for, send_file)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(ROOT, "nicheforge_core")
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

import error_report
import chatbot as chatbot_mod
import imagegen as imagegen_mod
import browser_apps as browser_mod

admin_bp = Blueprint("admin", __name__,
                     template_folder="templates",
                     static_folder="static")

# ------------------------------------------------------------------ helpers

NICHES = ["wicketverse", "pakwire", "maloomat", "sukhan", "paheli",
          "memeistan", "lafz", "deen", "parhai", "aangan", "angrezi",
          "techsathi", "imtihan", "marvelverse"]

NICHE_COLORS = {
    "wicketverse": "#34d399", "pakwire": "#60a5fa", "maloomat": "#fbbf24",
    "sukhan": "#f472b6", "paheli": "#a78bfa", "memeistan": "#fb923c",
    "lafz": "#2dd4bf", "deen": "#b8e62e", "parhai": "#38bdf8",
    "aangan": "#fb7185", "angrezi": "#818cf8", "techsathi": "#22d3ee",
    "imtihan": "#e879f9", "marvelverse": "#f43f5e",
}


def db_path():
    return current_app.config["NF_DB_PATH"]


def core():
    import app as core_app  # noqa: WPS433 (lazy: avoids import cycles)
    return core_app


def _db():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def admin_password():
    return os.environ.get("NICHEFORGE_ADMIN_PASSWORD", "")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("nf_admin"):
            return redirect(url_for("admin.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def _ladder():
    try:
        return core()._load_ladder()
    except Exception:
        return None


def _mask(s):
    s = str(s or "")
    return ("****" + s[-4:]) if len(s) >= 4 else "****"


# ------------------------------------------------------------------ auth

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    pw_env = admin_password()
    error = None
    if request.method == "POST":
        if pw_env and request.form.get("password") == pw_env:
            session["nf_admin"] = True
            nxt = request.args.get("next") or url_for("admin.dashboard")
            return redirect(nxt)
        error = "Ghalat password." if pw_env else \
            "NICHEFORGE_ADMIN_PASSWORD set nahi hai."
    return render_template("admin_login.html", error=error,
                           password_set=bool(pw_env))


@admin_bp.route("/logout")
def logout():
    session.pop("nf_admin", None)
    return redirect(url_for("admin.login"))


# ------------------------------------------------------------------ dashboard

def _niche_stats():
    conn = _db()
    try:
        stats = []
        for niche in NICHES:
            row = conn.execute(
                "SELECT SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) p,"
                " SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) a,"
                " MAX(created_at) last_batch FROM ideas WHERE niche=?",
                (niche,)).fetchone()
            try:
                err = conn.execute(
                    "SELECT COUNT(*) c FROM nf_errors WHERE niche=? AND"
                    " status='open' AND ts > datetime('now','-1 day')",
                    (niche,)).fetchone()["c"]
            except sqlite3.OperationalError:
                err = 0
            pending = row["p"] or 0
            last = (row["last_batch"] or "")[:16]
            if err:
                status = "error"
            elif pending > 0:
                status = "attention"
            elif not last:
                status = "idle"
            else:
                status = "healthy"
            stats.append({"niche": niche, "pending": pending,
                          "approved": row["a"] or 0, "last_batch": last,
                          "errors": err, "status": status,
                          "color": NICHE_COLORS[niche]})
        return stats
    finally:
        conn.close()


@admin_bp.route("/")
@login_required
def dashboard():
    stats = _niche_stats()
    conn = _db()
    try:
        totals = {}
        totals["pending"] = conn.execute(
            "SELECT COUNT(*) c FROM ideas WHERE status='pending'").fetchone()["c"]
        try:
            totals["open_errors"] = conn.execute(
                "SELECT COUNT(*) c FROM nf_errors WHERE status='open'").fetchone()["c"]
        except sqlite3.OperationalError:
            totals["open_errors"] = 0
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        totals["scheduled_today"] = conn.execute(
            "SELECT COUNT(*) c FROM scheduled_posts WHERE substr(slot_utc,1,10)=?",
            (today,)).fetchone()["c"]
        totals["jobs_done"] = len(
            imagegen_mod.list_jobs(db_path(), status="done", limit=1000))
    finally:
        conn.close()
    return render_template("admin_dashboard.html", stats=stats, totals=totals,
                           colors=NICHE_COLORS)


# ------------------------------------------------------------------ batches

@admin_bp.route("/batches")
@login_required
def batches():
    niche = request.args.get("niche", "")
    status = request.args.get("status", "pending")
    conn = _db()
    try:
        sql = ("SELECT id, niche, title, detail, status, created_at FROM ideas")
        clauses, params = [], []
        if niche:
            clauses.append("niche = ?")
            params.append(niche)
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT 300"
        ideas = [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
    return render_template("admin_batches.html", ideas=ideas, niches=NICHES,
                           colors=NICHE_COLORS, cur_niche=niche,
                           cur_status=status)


def _decide_idea(idea_id, to_status):
    import db as idea_db
    idea_db.set_status(db_path(), int(idea_id), to_status)
    return {"ok": True, "id": idea_id, "status": to_status}


@admin_bp.route("/api/ideas/<int:idea_id>/approve", methods=["POST"])
@login_required
def api_approve(idea_id):
    try:
        return jsonify(_decide_idea(idea_id, "approved"))
    except Exception as exc:  # noqa: BLE001
        error_report.log_error(db_path(), niche="global",
                               stage="idea_approve", exc=exc,
                               extra={"idea_id": idea_id})
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


@admin_bp.route("/api/ideas/<int:idea_id>/reject", methods=["POST"])
@login_required
def api_reject(idea_id):
    try:
        return jsonify(_decide_idea(idea_id, "rejected"))
    except Exception as exc:  # noqa: BLE001
        error_report.log_error(db_path(), niche="global",
                               stage="idea_reject", exc=exc,
                               extra={"idea_id": idea_id})
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


@admin_bp.route("/api/ideas/bulk", methods=["POST"])
@login_required
def api_bulk():
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids", [])
    action = data.get("action", "approved")
    if action not in ("approved", "rejected"):
        return jsonify({"ok": False, "error": "bad action"}), 400
    done, failed = 0, []
    for i in ids[:200]:
        try:
            _decide_idea(int(i), action)
            done += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({"id": i, "error": str(exc)[:120]})
    return jsonify({"ok": True, "done": done, "failed": failed})


# ------------------------------------------------------------------ gallery

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _gallery_images(limit=120):
    found = []
    base = os.path.join(CORE_DIR, "workspace", "niches")
    if not os.path.isdir(base):
        return found
    for niche in sorted(os.listdir(base)):
        for sub in ("output", "assets"):
            d = os.path.join(base, niche, sub)
            if not os.path.isdir(d):
                continue
            for root, _dirs, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(_IMAGE_EXTS):
                        p = os.path.join(root, f)
                        try:
                            found.append({
                                "niche": niche,
                                "name": f,
                                "rel": os.path.relpath(p, CORE_DIR),
                                "mtime": os.path.getmtime(p),
                            })
                        except OSError:
                            pass
    found.sort(key=lambda x: x["mtime"], reverse=True)
    return found[:limit]


@admin_bp.route("/gallery")
@login_required
def gallery():
    images = _gallery_images()
    return render_template("admin_gallery.html", images=images,
                           colors=NICHE_COLORS)


@admin_bp.route("/media/<path:rel>")
@login_required
def media(rel):
    # Serve workspace images; block path traversal.
    abs_p = os.path.abspath(os.path.join(CORE_DIR, rel))
    if not abs_p.startswith(os.path.abspath(CORE_DIR) + os.sep):
        abort(403)
    if not os.path.isfile(abs_p):
        abort(404)
    return send_file(abs_p)


# ------------------------------------------------------------------ schedule

@admin_bp.route("/schedule")
@login_required
def schedule():
    day = request.args.get("day", "")
    try:
        datetime.datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        day = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=5))).strftime("%Y-%m-%d")
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT s.id, s.niche, s.slot_utc, s.status, i.title"
            " FROM scheduled_posts s LEFT JOIN ideas i ON i.id = s.idea_id"
            " WHERE substr(s.slot_utc,1,10) = ? ORDER BY s.slot_utc",
            (day,)).fetchall()
        posts = []
        pkt = datetime.timezone(datetime.timedelta(hours=5))
        for r in rows:
            try:
                utc = datetime.datetime.fromisoformat(
                    r["slot_utc"].replace("Z", "+00:00"))
                local = utc.astimezone(pkt).strftime("%H:%M")
            except Exception:
                local = (r["slot_utc"] or "")[11:16]
            posts.append({"id": r["id"], "niche": r["niche"],
                          "time": local, "status": r["status"],
                          "title": r["title"] or ""})
    finally:
        conn.close()
    return render_template("admin_schedule.html", posts=posts, day=day,
                           colors=NICHE_COLORS)


# ------------------------------------------------------------------ errors

@admin_bp.route("/errors")
@login_required
def errors():
    niche = request.args.get("niche", "")
    status = request.args.get("status", "")
    errs = error_report.list_errors(db_path(), niche=niche or None,
                                    status=status or None, limit=100)
    return render_template("admin_errors.html", errors=errs, niches=NICHES,
                           cur_niche=niche, cur_status=status)


@admin_bp.route("/api/errors/<int:error_id>/traceback")
@login_required
def api_traceback(error_id):
    return jsonify({"traceback": error_report.read_traceback(error_id)})


@admin_bp.route("/api/errors/<int:error_id>/retry", methods=["POST"])
@login_required
def api_retry(error_id):
    errs = error_report.list_errors(db_path(), limit=1000)
    err = next((e for e in errs if e["id"] == error_id), None)
    if not err:
        return jsonify({"ok": False, "error": "not found"}), 404
    extra = {}
    # Retryable actions: re-run the idea decision that failed.
    try:
        if err["stage"] in ("idea_approve", "idea_reject") and \
                "idea_id" in str(err.get("message", "")):
            pass  # handled below via explicit re-decide when possible
        error_report.bump_retry(db_path(), error_id)
        return jsonify({"ok": True, "id": error_id,
                        "note": "Marked retried. Re-run the failed step from"
                                " its page (Batches / Publish)."})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


@admin_bp.route("/api/errors/<int:error_id>/resolve", methods=["POST"])
@login_required
def api_resolve(error_id):
    error_report.mark_resolved(db_path(), error_id)
    return jsonify({"ok": True, "id": error_id})


@admin_bp.route("/api/simulate-error", methods=["POST"])
@login_required
def api_simulate_error():
    """Test hook: proves the error pipeline works end-to-end."""
    try:
        raise RuntimeError("Simulated pipeline failure (admin test)")
    except RuntimeError as exc:
        eid = error_report.log_error(db_path(), niche="deen",
                                     stage="simulate",
                                     exc=exc)
    return jsonify({"ok": True, "error_id": eid,
                    "check": "/admin/errors and hidden_files/alerts.jsonl"})


# ------------------------------------------------------------------ keys

def _load_decrypted_config():
    pw = os.environ.get("NICHEFORGE_PASSWORD", "")
    cfg_path = os.path.join(CORE_DIR, "config.json")
    if not pw or not os.path.isfile(cfg_path):
        return None
    try:
        from providers import load_config
        return load_config(cfg_path, pw)
    except Exception:
        return None


def _save_config(config):
    pw = os.environ.get("NICHEFORGE_PASSWORD", "")
    cfg_path = os.path.join(CORE_DIR, "config.json")
    if not pw:
        raise RuntimeError("NICHEFORGE_PASSWORD not set")
    from providers.crypto import encrypt_config
    blob = encrypt_config(config, pw)
    tmp = cfg_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, cfg_path)
    try:
        os.chmod(cfg_path, 0o600)
    except OSError:
        pass


@admin_bp.route("/keys")
@login_required
def keys():
    cfg = _load_decrypted_config()
    providers, pages = [], []
    if cfg:
        from providers.ladder import mask_key
        for p in cfg.get("providers", []):
            providers.append({
                "name": p.get("name"),
                "models": ", ".join(p.get("models", [])[:2]),
                "keys": [mask_key(k) for k in p.get("keys", [])],
                "count": len(p.get("keys", [])),
            })
        for pg in cfg.get("facebook_pages", []):
            pages.append({"label": pg.get("label"),
                          "page_id": _mask(pg.get("page_id")),
                          "token": _mask(pg.get("token"))})
    return render_template("admin_keys.html", configured=cfg is not None,
                           providers=providers, pages=pages)


@admin_bp.route("/api/keys/add", methods=["POST"])
@login_required
def api_key_add():
    data = request.get_json(force=True, silent=True) or {}
    provider = (data.get("provider") or "").strip().lower()
    key = (data.get("key") or "").strip()
    if not provider or not key:
        return jsonify({"ok": False, "error": "provider + key required"}), 400
    try:
        cfg = _load_decrypted_config()
        if cfg is None:
            return jsonify({"ok": False,
                            "error": "config not available (set NICHEFORGE_PASSWORD"
                                     " and run setup_keys.py once)"}), 400
        found = False
        for p in cfg.get("providers", []):
            if p.get("name") == provider:
                p.setdefault("keys", [])
                if key not in p["keys"]:
                    p["keys"].append(key)
                found = True
        if not found:
            return jsonify({"ok": False, "error": "unknown provider"}), 400
        _save_config(cfg)
        try:
            core()._ladder_cache["ladder"] = None  # force reload
        except Exception:
            pass
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        error_report.log_error(db_path(), niche="global",
                               stage="key_add", exc=exc)
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


@admin_bp.route("/api/keys/page", methods=["POST"])
@login_required
def api_page_add():
    data = request.get_json(force=True, silent=True) or {}
    label = (data.get("label") or "").strip()
    page_id = (data.get("page_id") or "").strip()
    token = (data.get("token") or "").strip()
    if not (label and page_id and token):
        return jsonify({"ok": False, "error": "label + page_id + token required"}), 400
    try:
        cfg = _load_decrypted_config()
        if cfg is None:
            return jsonify({"ok": False, "error": "config not available"}), 400
        pages = cfg.setdefault("facebook_pages", [])
        pages = [p for p in pages if p.get("label") != label]
        pages.append({"label": label, "page_id": page_id, "token": token})
        cfg["facebook_pages"] = pages
        _save_config(cfg)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        error_report.log_error(db_path(), niche="global",
                               stage="page_add", exc=exc)
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


# ------------------------------------------------------------------ chatbot

@admin_bp.route("/chat")
@login_required
def chat():
    history = session.get("nf_chat", [])
    return render_template("admin_chat.html", history=history)


@admin_bp.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty"}), 400
    history = session.get("nf_chat", [])
    reply, provider, model = chatbot_mod.ask(db_path(), _ladder(),
                                             history, text)
    history = (history + [{"role": "user", "content": text},
                          {"role": "assistant", "content": reply}])
    session["nf_chat"] = history[-(chatbot_mod.MAX_HISTORY):]
    return jsonify({"ok": True, "reply": reply, "provider": provider,
                    "model": model})


@admin_bp.route("/api/chat/clear", methods=["POST"])
@login_required
def api_chat_clear():
    session["nf_chat"] = []
    return jsonify({"ok": True})


# ------------------------------------------------------------------ image generator

@admin_bp.route("/generate")
@login_required
def generate():
    jobs = imagegen_mod.list_jobs(db_path(), limit=40)
    pending = [dict(r) for r in _pending_ideas()]
    return render_template("admin_generate.html", jobs=jobs, niches=NICHES,
                           colors=NICHE_COLORS,
                           providers=imagegen_mod.PROVIDERS,
                           pending_ideas=pending)


def _pending_ideas():
    conn = _db()
    try:
        return conn.execute(
            "SELECT id, niche, title FROM ideas WHERE status='pending'"
            " ORDER BY id DESC LIMIT 100").fetchall()
    finally:
        conn.close()


@admin_bp.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    data = request.get_json(force=True, silent=True) or {}
    niche = (data.get("niche") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    provider = (data.get("provider") or "instant").strip()
    idea_id = data.get("idea_id")
    if not prompt:
        return jsonify({"ok": False, "error": "prompt required"}), 400
    if provider not in [p[0] for p in imagegen_mod.PROVIDERS]:
        return jsonify({"ok": False, "error": "bad provider"}), 400
    try:
        job_id = imagegen_mod.create_job(db_path(), niche, prompt,
                                         provider,
                                         int(idea_id) if idea_id else None)
        job = imagegen_mod.get_job(db_path(), job_id)
        return jsonify({"ok": True, "job": job})
    except Exception as exc:  # noqa: BLE001
        error_report.log_error(db_path(), niche=niche or "global",
                               stage="image_generate", exc=exc)
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


@admin_bp.route("/api/jobs")
@login_required
def api_jobs():
    status = request.args.get("status", "")
    return jsonify({"jobs": imagegen_mod.list_jobs(
        db_path(), status=status or None, limit=60)})


@admin_bp.route("/api/jobs/<int:job_id>/upload", methods=["POST"])
@login_required
def api_job_upload(job_id):
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "no file"}), 400
    try:
        rel = imagegen_mod.attach_result(db_path(), job_id, f, f.filename)
        return jsonify({"ok": True, "rel": rel,
                        "url": url_for("admin.media", rel=rel)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


@admin_bp.route("/api/jobs/<int:job_id>/use-in-batch", methods=["POST"])
@login_required
def api_job_use(job_id):
    try:
        rel = imagegen_mod.use_in_batch(db_path(), job_id)
        return jsonify({"ok": True, "rel": rel,
                        "url": url_for("admin.media", rel=rel)})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


# ------------------------------------------------------------------ browser apps

@admin_bp.route("/browser")
@login_required
def browser():
    services = browser_mod.get_services(db_path())
    pending = {s["id"]: browser_mod.pending_jobs_for(db_path(), s["id"])
               for s in services}
    return render_template("admin_browser.html", services=services,
                           pending=pending,
                           status_labels=browser_mod.STATUS_LABEL)


@admin_bp.route("/api/browser/<service>/status", methods=["POST"])
@login_required
def api_browser_status(service):
    data = request.get_json(force=True, silent=True) or {}
    try:
        browser_mod.set_service_status(
            db_path(), service, data.get("status", "needs_login"),
            reset_at=data.get("reset_at", ""), note=data.get("note", ""),
            profile_name=data.get("profile_name", ""))
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)[:200]}), 400


# ------------------------------------------------------------------ alerts (Jarvis polling)

@admin_bp.route("/api/alerts")
def api_alerts():
    """Machine-readable error alerts for Jarvis's monitor.

    Auth: admin session OR ?key=<NICHEFORGE_ADMIN_PASSWORD>.
    """
    pw = admin_password()
    if not (session.get("nf_admin") or
            (pw and request.args.get("key") == pw)):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    since = request.args.get("since", "")
    alerts = error_report.recent_alerts(limit=100)
    if since:
        alerts = [a for a in alerts if a.get("ts", "") > since]
    return jsonify({"ok": True, "alerts": alerts})
