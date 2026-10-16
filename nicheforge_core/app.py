"""NicheForge — local Flask web app.

Phase 1: Idea Bank approval inbox.
Phase 2: content pipeline (research dossiers, captions, prompt forge,
Urdu overlay studio, slot planner + clash detector, FB publisher).

Runs on 127.0.0.1:5057. Plain HTML/JS, no npm.
"""
import os
import sqlite3
from flask import Flask, jsonify, request, send_from_directory, send_file

import db as idea_db
import research as research_mod
import captions as captions_mod
import prompts as prompts_mod
import overlay as overlay_mod
import schedule as schedule_mod
import publish as publish_mod
from providers import load_config, KeyLadder

# Phase 3 — browser automation track (no-API: real Chrome on his PC).
from browser_track import profiles as profiles_mod
from browser_track import sessions as sessions_mod
from browser_track import mimic as mimic_mod
from browser_track import sentinel as sentinel_mod
from browser_track import guard as guard_mod
from browser_track import stealth as stealth_mod
from browser_track import images as images_mod
from browser_track import paste_points as paste_mod
from browser_track import harvest as harvest_mod
from browser_track import comments as comments_mod

# Phase 4 — intelligence layer.
from intel import init_intel_tables as init_intel_tables_mod
from intel import pulse as pulse_mod
from intel import feedback as feedback_mod
from intel import health as health_mod
from intel import shadow as shadow_mod
from intel import trends as trends_mod
from intel import newsjack as newsjack_mod
from intel import crisis as crisis_mod
from intel import festivals as festivals_mod
from intel import weaver as weaver_mod
from intel import recycle as recycle_mod
from intel import autopsy as autopsy_mod

# Phase 5 — expansion layer.
from platforms import list_plugins as platforms_list_mod
from platforms import get_plugin as platforms_get_mod
import reels as reels_mod
import comments_guard as comments_guard_mod
import remote as remote_mod
import credits as credits_mod
import offline as offline_mod
import backup as backup_mod
import launch as launch_mod
import update as update_mod

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "nicheforge.db")
DNA_DIR = os.path.join(ROOT, "dna")
CONFIG_PATH = os.path.join(ROOT, "config.json")
WORKSPACE_DIR = os.path.join(ROOT, "workspace")

app = Flask(__name__)
idea_db.init_db(DB_PATH)
schedule_mod.init_schedule_tables(DB_PATH)
publish_mod.init_publish_tables(DB_PATH)
# Phase 3 tables (idempotent; safe to call every boot).
profiles_mod.init_profile_tables(DB_PATH)
images_mod.init_image_tables(DB_PATH)
paste_mod.init_paste_tables(DB_PATH)
harvest_mod.init_harvest_tables(DB_PATH)
mimic_mod.init_mimic_tables(DB_PATH)
sentinel_mod.RateLimitTracker(DB_PATH)  # creates browser_parks on construct
init_intel_tables_mod(DB_PATH)  # Phase-4 tables; idempotent, safe every boot
# Phase 5 tables (idempotent; safe to call every boot).
reels_mod.init_reel_tables(DB_PATH)
comments_guard_mod.init_comment_tables(DB_PATH)
remote_mod.init_remote_tables(DB_PATH)
credits_mod.init_credit_tables(DB_PATH)
offline_mod.init_offline_tables(DB_PATH)

_ladder_cache = {"ladder": None, "config": None}


def _load_ladder():
    """Build (and cache) a KeyLadder from the encrypted config.

    Needs NICHEFORGE_PASSWORD env var + config.json from setup_keys.py.
    Returns None when keys are not configured — routes must handle that.
    """
    if _ladder_cache["ladder"] is not None:
        return _ladder_cache["ladder"]
    pw = os.environ.get("NICHEFORGE_PASSWORD")
    if not pw or not os.path.isfile(CONFIG_PATH):
        return None
    try:
        config = load_config(CONFIG_PATH, pw)
    except Exception:
        return None
    _ladder_cache["config"] = config
    _ladder_cache["ladder"] = KeyLadder(config, DB_PATH)
    return _ladder_cache["ladder"]


def _load_fb_config():
    """Return decrypted config dict for FBPublisher, or None."""
    _load_ladder()  # populates the cache as a side effect
    return _ladder_cache["config"]


def _get_idea(idea_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, niche, title, detail, status FROM ideas WHERE id = ?",
            (idea_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _safe_workspace_path(rel):
    """Resolve a workspace-relative path, rejecting traversal outside it."""
    abs_path = os.path.abspath(os.path.join(WORKSPACE_DIR, rel))
    if not abs_path.startswith(os.path.abspath(WORKSPACE_DIR) + os.sep):
        raise ValueError("path escapes workspace")
    return abs_path


@app.route("/")
def inbox():
    return send_from_directory(os.path.join(ROOT, "templates"), "inbox.html")


@app.route("/api/niches")
def api_niches():
    return jsonify({"niches": idea_db.NICHE_IDS})


@app.route("/api/ideas", methods=["GET"])
def api_list_ideas():
    status = request.args.get("status") or None
    niche = request.args.get("niche") or None
    if status and status not in idea_db.VALID_STATUSES:
        return jsonify({"error": "invalid status"}), 400
    try:
        ideas = idea_db.list_ideas(DB_PATH, status=status, niche=niche)
    except Exception as e:  # missing DB etc. — never 500 on reads
        return jsonify({"error": str(e), "ideas": []}), 200
    return jsonify({"ideas": ideas})


@app.route("/api/ideas", methods=["POST"])
def api_add_idea():
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    title = (data.get("title") or "").strip()
    detail = (data.get("detail") or "").strip()
    if niche not in idea_db.NICHE_IDS:
        return jsonify({"ok": False, "reason": "unknown niche: {}".format(niche)}), 200
    ok, info = idea_db.add_idea(DB_PATH, niche, title, detail)
    if ok:
        try:
            idea_id = int(info.split("#", 1)[1].split()[0])
        except (IndexError, ValueError):
            idea_id = None
        return jsonify({"ok": True, "id": idea_id, "info": info}), 200
    return jsonify({"ok": False, "reason": info}), 200  # duplicates never 500


def _decide(idea_id, status):
    try:
        changed = idea_db.set_status(DB_PATH, idea_id, status)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "reason": str(e)}), 200
    if not changed:
        return jsonify({"ok": False, "reason": "idea #{} not found".format(idea_id)}), 200
    return jsonify({"ok": True, "id": idea_id, "status": status}), 200


@app.route("/api/ideas/<int:idea_id>/approve", methods=["POST"])
def api_approve(idea_id):
    return _decide(idea_id, "approved")


@app.route("/api/ideas/<int:idea_id>/reject", methods=["POST"])
def api_reject(idea_id):
    return _decide(idea_id, "rejected")


@app.route("/api/dna/<niche>")
def api_dna(niche):
    # Whitelist to NICHE_IDS to avoid path traversal; file owned by other agents.
    if niche not in idea_db.NICHE_IDS:
        return jsonify({"error": "unknown niche"}), 404
    path = os.path.join(DNA_DIR, niche + ".json")
    if not os.path.isfile(path):
        return jsonify({"error": "dna not found"}), 404
    return send_from_directory(DNA_DIR, niche + ".json", mimetype="application/json")


# ------------------------------------------------------------------
# Phase 2 — content pipeline pages
# ------------------------------------------------------------------

@app.route("/pipeline")
def page_pipeline():
    return send_from_directory(os.path.join(ROOT, "templates"), "pipeline.html")


@app.route("/overlay")
def page_overlay():
    return send_from_directory(os.path.join(ROOT, "templates"), "overlay.html")


@app.route("/schedule")
def page_schedule():
    return send_from_directory(os.path.join(ROOT, "templates"), "schedule.html")


@app.route("/publish")
def page_publish():
    return send_from_directory(os.path.join(ROOT, "templates"), "publish.html")


@app.route("/api/pipeline/run", methods=["POST"])
def api_pipeline_run():
    """Run dossier -> caption -> prompt for one approved idea.

    Body: {"idea_id": <int>}. Needs API keys (NICHEFORGE_PASSWORD + config.json).
    """
    data = request.get_json(silent=True) or {}
    try:
        idea_id = int(data.get("idea_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "reason": "idea_id is required"}), 400
    idea = _get_idea(idea_id)
    if not idea:
        return jsonify({"ok": False, "reason": "idea not found"}), 404
    ladder = _load_ladder()
    if ladder is None:
        return jsonify({"ok": False,
                        "reason": "API keys not configured — run setup_keys.py, "
                                  "then set NICHEFORGE_PASSWORD and restart."}), 400
    niche = idea["niche"]
    try:
        dossier = research_mod.build_dossier(
            niche, str(idea_id), idea["title"], idea.get("detail") or "", ladder)
        caption = captions_mod.make_caption(niche, str(idea_id), dossier, ladder)
        prompt = prompts_mod.forge_prompt(niche, str(idea_id), dossier)
    except Exception as e:  # noqa: BLE001 — surface module errors cleanly
        return jsonify({"ok": False, "reason": str(e)[:300]}), 200
    return jsonify({
        "ok": True,
        "idea_id": idea_id,
        "niche": niche,
        "dossier_path": "niches/{}/output/dossier_{}.json".format(niche, idea_id),
        "caption_path": "niches/{}/output/caption_{}.txt".format(niche, idea_id),
        "prompt_path": "niches/{}/output/prompt_{}.json".format(niche, idea_id),
        "provider": dossier.get("_provider") or prompt.get("provider") or "",
    })


@app.route("/api/pipeline/status")
def api_pipeline_status():
    """Which pipeline artefacts exist for an idea."""
    idea_id = request.args.get("idea_id", "")
    idea = None
    try:
        idea = _get_idea(int(idea_id))
    except (TypeError, ValueError):
        pass
    if not idea:
        return jsonify({"ok": False, "reason": "idea not found"}), 404
    niche = idea["niche"]
    outdir = os.path.join(WORKSPACE_DIR, "niches", niche, "output")
    found = {}
    for key, name in (("dossier", "dossier_{}.json"),
                      ("caption", "caption_{}.txt"),
                      ("prompt", "prompt_{}.json")):
        found[key] = os.path.isfile(os.path.join(outdir, name.format(idea_id)))
    return jsonify({"ok": True, "idea_id": idea["id"], "niche": niche,
                    "artefacts": found})


# ------------------------------------------------------------------
# Phase 2 — overlay studio
# ------------------------------------------------------------------

@app.route("/api/overlay/niches")
def api_overlay_niches():
    return jsonify({"niches": overlay_mod.OVERLAY_NICHES})


@app.route("/api/overlay/upload", methods=["POST"])
def api_overlay_upload():
    """Multipart upload of a base image -> workspace assets. Returns rel path."""
    niche = (request.form.get("niche") or "").strip()
    if niche not in overlay_mod.OVERLAY_NICHES:
        return jsonify({"ok": False, "reason": "overlay not allowed for niche"}), 400
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify({"ok": False, "reason": "no image uploaded"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return jsonify({"ok": False, "reason": "unsupported image type"}), 400
    updir = os.path.join(WORKSPACE_DIR, "niches", niche, "assets", "uploads")
    os.makedirs(updir, exist_ok=True)
    safe = "".join(c for c in os.path.basename(f.filename) if c.isalnum() or c in "._-")
    dest = os.path.join(updir, safe or "base.png")
    f.save(dest)
    rel = os.path.relpath(dest, WORKSPACE_DIR)
    return jsonify({"ok": True, "path": rel})


@app.route("/api/overlay/render", methods=["POST"])
def api_overlay_render():
    """Render Urdu overlay. Body: {base_path, niche, lines[], attribution?}."""
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    base_rel = (data.get("base_path") or "").strip()
    lines = data.get("lines") or []
    attribution = (data.get("attribution") or "").strip() or None
    if not base_rel or not lines:
        return jsonify({"ok": False, "reason": "base_path and lines required"}), 400
    try:
        base_abs = _safe_workspace_path(base_rel)
        out_abs = overlay_mod.overlay_urdu(base_abs, niche, lines,
                                           attribution=attribution)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        return jsonify({"ok": False, "reason": str(e)[:300]}), 200
    rel = os.path.relpath(out_abs, WORKSPACE_DIR)
    return jsonify({"ok": True, "path": rel})


@app.route("/api/overlay/list")
def api_overlay_list():
    niche = (request.args.get("niche") or "").strip()
    try:
        files = overlay_mod.list_overlays(niche)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    rels = [os.path.relpath(f, WORKSPACE_DIR) for f in files]
    return jsonify({"ok": True, "files": rels})


@app.route("/api/files")
def api_files():
    """Serve a workspace file (previews). Path must stay inside workspace/."""
    rel = request.args.get("path", "")
    try:
        abs_path = _safe_workspace_path(rel)
    except ValueError:
        return jsonify({"error": "bad path"}), 400
    if not os.path.isfile(abs_path):
        return jsonify({"error": "not found"}), 404
    return send_file(abs_path)


# ------------------------------------------------------------------
# Phase 2 — schedule
# ------------------------------------------------------------------

@app.route("/api/schedule", methods=["GET"])
def api_schedule_list():
    date_str = (request.args.get("date") or "").strip()
    if not date_str:
        return jsonify({"ok": False, "reason": "date=YYYY-MM-DD required"}), 400
    try:
        rows = schedule_mod.list_schedule(DB_PATH, date_str)
        clashes = schedule_mod.detect_clashes(DB_PATH, date_str)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 400
    return jsonify({"ok": True, "date": date_str, "rows": rows,
                    "clashes": clashes})


@app.route("/api/schedule/plan", methods=["POST"])
def api_schedule_plan():
    data = request.get_json(silent=True) or {}
    date_str = (data.get("date") or "").strip()
    niche = (data.get("niche") or "").strip() or None
    if niche and niche not in idea_db.NICHE_IDS:
        return jsonify({"ok": False, "reason": "unknown niche"}), 400
    try:
        result = schedule_mod.plan_day(DB_PATH, date_str, niche=niche)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 400
    return jsonify({"ok": True, "date": date_str, **result})


@app.route("/api/schedule/clear", methods=["POST"])
def api_schedule_clear():
    data = request.get_json(silent=True) or {}
    date_str = (data.get("date") or "").strip()
    try:
        n = schedule_mod.clear_day(DB_PATH, date_str)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 400
    return jsonify({"ok": True, "cleared": n})


# ------------------------------------------------------------------
# Phase 2 — publish
# ------------------------------------------------------------------

@app.route("/api/publish/pages")
def api_publish_pages():
    config = _load_fb_config()
    pages = (config or {}).get("facebook_pages") or []
    return jsonify({"ok": True,
                    "pages": [{"label": p.get("label")} for p in pages],
                    "configured": bool(pages)})


@app.route("/api/publish", methods=["POST"])
def api_publish():
    """Publish a photo. Body: {label, image_path, caption, scheduled_utc?,
    dry_run=true}. dry_run defaults true — no network unless explicitly false."""
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    image_rel = (data.get("image_path") or "").strip()
    caption = data.get("caption") or ""
    scheduled_utc = (data.get("scheduled_utc") or "").strip() or None
    dry_run = bool(data.get("dry_run", True))
    if not label or not image_rel:
        return jsonify({"ok": False, "reason": "label and image_path required"}), 400
    config = _load_fb_config()
    if config is None:
        return jsonify({"ok": False,
                        "reason": "Facebook pages not configured — run setup_keys.py."}), 400
    try:
        image_abs = _safe_workspace_path(image_rel)
    except ValueError:
        return jsonify({"ok": False, "reason": "bad image path"}), 400
    try:
        pub = publish_mod.FBPublisher(config, DB_PATH, dry_run=dry_run)
        result = pub.publish_photo(label, image_abs, caption,
                                   scheduled_utc=scheduled_utc)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)[:200]}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Phase 3 — browser automation track (no-API: real Chrome on his PC).
# Everything degrades gracefully: missing config/profiles/keys -> clear
# 200-status messages, never silent failures, never 500s on reads.
# ---------------------------------------------------------------------------

@app.route("/browser")
def browser_page():
    return send_from_directory(os.path.join(ROOT, "templates"), "browser.html")


def _browser_status():
    """Aggregate dashboard state for the /browser UI."""
    try:
        profiles = profiles_mod.list_profiles(DB_PATH)
    except Exception as e:  # noqa: BLE001
        profiles = []
        profiles_error = str(e)
    else:
        profiles_error = ""
    try:
        tracker = sentinel_mod.RateLimitTracker(DB_PATH)
        parks = tracker.list_parks()
    except Exception:  # noqa: BLE001
        parks = []
    try:
        paste_pending = paste_mod.pending_count(DB_PATH)
    except Exception:  # noqa: BLE001
        paste_pending = 0
    try:
        jobs = images_mod.list_jobs(DB_PATH)
    except Exception:  # noqa: BLE001
        jobs = []
    queue = {"queued": 0, "downloading": 0, "done": 0, "failed": 0}
    for j in jobs:
        s = (j.get("status") or "")
        if s in queue:
            queue[s] += 1
    try:
        login_report = sessions_mod.login_status_report(DB_PATH)
    except Exception:  # noqa: BLE001
        login_report = []
    window_ok = stealth_mod.within_window()
    return {
        "profiles": profiles,
        "profiles_error": profiles_error,
        "parks": parks,
        "paste_pending": paste_pending,
        "image_queue": queue,
        "login_report": login_report,
        "stealth": {
            "within_window": window_ok,
            "policy": stealth_mod.describe_policy(),
            "next_start": stealth_mod.next_allowed_start().isoformat(),
        },
    }


@app.route("/api/browser/status")
def api_browser_status():
    return jsonify(_browser_status())


@app.route("/api/browser/profiles")
def api_browser_profiles():
    niche = request.args.get("niche") or None
    try:
        return jsonify({"profiles": profiles_mod.list_profiles(DB_PATH, niche=niche)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"profiles": [], "error": str(e)}), 200


@app.route("/api/browser/profiles/sync", methods=["POST"])
def api_browser_profiles_sync():
    """Register one profile per (niche x service x email) from the encrypted
    config's browser_accounts. Needs NICHEFORGE_PASSWORD + config.json."""
    config = _load_fb_config()
    if config is None:
        return jsonify({"ok": False,
                        "reason": "config.json missing — run setup_keys.py first."}), 400
    accounts = config.get("browser_accounts") or {}
    if not accounts:
        return jsonify({"ok": False,
                        "reason": "no browser_accounts in config — add emails via setup_keys.py."}), 400
    try:
        count = 0
        for niche in idea_db.NICHE_IDS:
            rows = profiles_mod.sync_accounts_from_config(DB_PATH, config, niche)
            count += len(rows or [])
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "registered": count})


@app.route("/api/browser/profiles/resume", methods=["POST"])
def api_browser_profile_resume():
    """Human-only resume of a paused profile (BlockGuard never auto-resumes)."""
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    service = (data.get("service") or "").strip()
    email = (data.get("email") or "").strip()
    if not (niche and service and email):
        return jsonify({"ok": False, "reason": "niche, service, email required"}), 400
    try:
        guard = guard_mod.BlockGuard(DB_PATH)
        guard.human_resume(niche, service, email)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True})


@app.route("/api/browser/login-status")
def api_browser_login_status():
    try:
        return jsonify({"report": sessions_mod.login_status_report(DB_PATH)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"report": [], "error": str(e)}), 200


# --- paste points -----------------------------------------------------------

@app.route("/api/browser/paste/pending")
def api_browser_paste_pending():
    try:
        return jsonify({"pending": paste_mod.list_pending(DB_PATH),
                        "count": paste_mod.pending_count(DB_PATH)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"pending": [], "count": 0, "error": str(e)}), 200


@app.route("/api/browser/paste/next")
def api_browser_paste_next():
    try:
        nxt = paste_mod.next_pending(DB_PATH)
    except Exception as e:  # noqa: BLE001
        return jsonify({"paste": None, "error": str(e)}), 200
    return jsonify({"paste": nxt})


@app.route("/api/browser/paste/<int:paste_id>/done", methods=["POST"])
def api_browser_paste_done(paste_id):
    try:
        paste_mod.complete(DB_PATH, paste_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True})


@app.route("/api/browser/paste/<int:paste_id>/skip", methods=["POST"])
def api_browser_paste_skip(paste_id):
    try:
        paste_mod.skip(DB_PATH, paste_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True})


@app.route("/api/browser/paste", methods=["POST"])
def api_browser_paste_request():
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    url = (data.get("url") or "").strip()
    context = (data.get("context") or "").strip()
    if not label:
        return jsonify({"ok": False, "reason": "label required"}), 400
    try:
        pid = paste_mod.request(DB_PATH, label, url, context)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "id": pid})


# --- image queue ------------------------------------------------------------

@app.route("/api/browser/images/queue", methods=["POST"])
def api_browser_images_queue():
    """Queue Prompt Forge JSONs for image generation. Body: {niche, prompt_paths[]}.
    Nothing runs yet — the runner (Phase 3 worker) picks jobs up sequentially."""
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    paths = data.get("prompt_paths") or []
    if niche not in idea_db.NICHE_IDS:
        return jsonify({"ok": False, "reason": "unknown niche"}), 400
    if not paths:
        return jsonify({"ok": False, "reason": "prompt_paths required"}), 400
    try:
        ids = images_mod.queue_from_prompts(DB_PATH, niche, paths)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "job_ids": ids})


@app.route("/api/browser/images/jobs")
def api_browser_images_jobs():
    niche = request.args.get("niche") or None
    try:
        jobs = images_mod.list_jobs(DB_PATH, niche=niche)
    except Exception as e:  # noqa: BLE001
        return jsonify({"jobs": [], "error": str(e)}), 200
    return jsonify({"jobs": jobs})


@app.route("/api/browser/images/dryrun", methods=["POST"])
def api_browser_images_dryrun():
    """End-to-end dry-run of ONE queued image job with the MockDriver.
    No network, no real browser — verifies the whole chain works."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    try:
        jobs = images_mod.list_jobs(DB_PATH)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    target = None
    for j in jobs:
        if (job_id is None and j.get("status") == "queued") or \
           (job_id is not None and j.get("id") == job_id):
            target = j
            break
    if target is None:
        return jsonify({"ok": False, "reason": "no queued job found"}), 200
    try:
        runner = images_mod.ImageJobRunner(DB_PATH, images_mod.MockDriver(),
                                           dry_run=True)
        result = runner.run_job(target["id"])
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "result": result})


@app.route("/api/browser/images/pick", methods=["POST"])
def api_browser_images_pick():
    """Record Hmb's one-tap pick from a contact sheet."""
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    date = (data.get("date") or "").strip()
    image_path = (data.get("image_path") or "").strip()
    if not (niche and date and image_path):
        return jsonify({"ok": False, "reason": "niche, date, image_path required"}), 400
    try:
        pick_id = images_mod.record_pick(DB_PATH, niche, date, image_path)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "pick_id": pick_id})


# --- harvest ----------------------------------------------------------------

@app.route("/api/browser/harvest/targets", methods=["GET"])
def api_browser_harvest_targets():
    niche = request.args.get("niche") or None
    try:
        return jsonify({"targets": harvest_mod.list_targets(DB_PATH, niche=niche)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"targets": [], "error": str(e)}), 200


@app.route("/api/browser/harvest/targets", methods=["POST"])
def api_browser_harvest_add_target():
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    url = (data.get("url") or "").strip()
    label = (data.get("label") or "").strip()
    if niche not in idea_db.NICHE_IDS or not url:
        return jsonify({"ok": False, "reason": "niche and url required"}), 400
    try:
        tid = harvest_mod.add_target(DB_PATH, niche, url, label)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "id": tid})


@app.route("/api/browser/harvest/run", methods=["POST"])
def api_browser_harvest_run():
    """Run the competitor harvest. dry_run defaults TRUE — no network unless
    explicitly disabled. Sequential, respectful gaps, stops on block signals."""
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip() or None
    dry_run = bool(data.get("dry_run", True))
    if niche is not None and niche not in idea_db.NICHE_IDS:
        return jsonify({"ok": False, "reason": "unknown niche"}), 400
    if not dry_run:
        return jsonify({"ok": False,
                        "reason": "live harvest runs from the Phase-3 worker, not the web UI."}), 400

    class _DryRunHarvestDriver:
        """Canned driver for the UI dry-run: no network, two fake posts."""
        def __init__(self):
            self.log = []

        def goto(self, url):
            self.log.append(("goto", url))

        def extract_posts(self):
            return [
                {"snippet": "Dry-run sample post one", "likes": 12,
                 "comments_count": 3, "posted_at_text": "2h"},
                {"snippet": "Dry-run sample post two", "likes": 40,
                 "comments_count": 9, "posted_at_text": "5h"},
            ]

    try:
        result = harvest_mod.run_harvest(DB_PATH, _DryRunHarvestDriver(),
                                        niche=niche, dry_run=True,
                                        min_gap_secs=0)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "result": result})


# --- Phase 4: intelligence layer ----------------------------------------------

@app.route("/intel")
def intel_page():
    return send_from_directory(os.path.join(ROOT, "templates"), "intel.html")


@app.route("/api/intel/pulse/summary")
def api_intel_pulse_summary():
    niche = request.args.get("niche") or None
    try:
        return jsonify(pulse_mod.summary(DB_PATH, niche=niche))
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 200


@app.route("/api/intel/pulse/metric", methods=["POST"])
def api_intel_pulse_metric():
    data = request.get_json(silent=True) or {}
    try:
        pid = pulse_mod.record_metric(
            DB_PATH,
            data.get("niche") or "", data.get("post_id") or "",
            data.get("posted_at") or "",
            int(data.get("likes") or 0), int(data.get("shares") or 0),
            int(data.get("comments") or 0), int(data.get("reach") or 0),
            data.get("source") or "manual",
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "id": pid})


@app.route("/api/intel/pulse/import", methods=["POST"])
def api_intel_pulse_import():
    data = request.get_json(silent=True) or {}
    try:
        count = pulse_mod.import_csv(DB_PATH, data.get("csv") or "")
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "count": count})


@app.route("/api/intel/ideas/scores")
def api_intel_idea_scores():
    try:
        feedback_mod.refresh_scores(DB_PATH)
        return jsonify({"scores": feedback_mod.score_map(DB_PATH)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"scores": {}, "error": str(e)[:200]}), 200


@app.route("/api/intel/health")
def api_intel_health():
    try:
        return jsonify({"health": health_mod.health_map(DB_PATH)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"health": {}, "error": str(e)[:200]}), 200


@app.route("/api/intel/health/refresh", methods=["POST"])
def api_intel_health_refresh():
    try:
        result = health_mod.refresh_all(DB_PATH)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "health": result})


@app.route("/api/intel/shadow")
def api_intel_shadow():
    alerts = []
    try:
        for niche in idea_db.NICHE_IDS:
            r = shadow_mod.check(DB_PATH, niche)
            if r.get("alert"):
                alerts.append(r)
    except Exception as e:  # noqa: BLE001
        return jsonify({"alerts": [], "error": str(e)[:200]}), 200
    return jsonify({"alerts": alerts})


@app.route("/api/intel/trends")
def api_intel_trends():
    try:
        return jsonify({"alerts": trends_mod.list_alerts(DB_PATH)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"alerts": [], "error": str(e)[:200]}), 200


@app.route("/api/intel/trends/poll", methods=["POST"])
def api_intel_trends_poll():
    try:
        result = trends_mod.poll(DB_PATH)
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "reason": str(e)[:200]}), 200
    return jsonify(result)


@app.route("/api/intel/newsjack", methods=["POST"])
def api_intel_newsjack():
    data = request.get_json(silent=True) or {}
    headline = (data.get("headline") or "").strip()
    if not headline:
        return jsonify({"ok": False, "reason": "headline is required"}), 400
    facts = (data.get("facts") or "").strip()
    niches = data.get("niches") or None
    try:
        result = newsjack_mod.on_spike(DB_PATH, headline, facts, niches)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, **result})


@app.route("/api/intel/weave", methods=["POST"])
def api_intel_weave():
    data = request.get_json(silent=True) or {}
    headline = (data.get("headline") or "").strip()
    if not headline:
        return jsonify({"ok": False, "reason": "headline is required"}), 400
    try:
        result = weaver_mod.weave(DB_PATH, headline, (data.get("facts") or "").strip())
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, **result})


@app.route("/api/intel/crisis")
def api_intel_crisis():
    try:
        return jsonify({"events": crisis_mod.list_events(DB_PATH)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"events": [], "error": str(e)[:200]}), 200


@app.route("/api/intel/crisis/scan", methods=["POST"])
def api_intel_crisis_scan():
    try:
        result = crisis_mod.scan(DB_PATH)
    except Exception as e:  # noqa: BLE001
        return jsonify({"triggered": False, "reason": str(e)[:200]}), 200
    return jsonify(result)


@app.route("/api/intel/crisis/resume", methods=["POST"])
def api_intel_crisis_resume():
    data = request.get_json(silent=True) or {}
    try:
        result = crisis_mod.resume(DB_PATH, int(data.get("event_id")))
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, **result})


@app.route("/api/intel/recycle", methods=["POST"])
def api_intel_recycle():
    try:
        result = recycle_mod.make_briefs(DB_PATH)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, **result})


@app.route("/api/intel/festivals")
def api_intel_festivals():
    try:
        return jsonify({"packs": festivals_mod.list_packs(DB_PATH)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"packs": [], "error": str(e)[:200]}), 200


@app.route("/api/intel/festivals/generate", methods=["POST"])
def api_intel_festivals_generate():
    try:
        result = festivals_mod.generate_packs(DB_PATH)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, **result})


@app.route("/api/intel/autopsy", methods=["POST"])
def api_intel_autopsy():
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    if not niche:
        return jsonify({"ok": False, "reason": "niche is required"}), 400
    try:
        result = autopsy_mod.analyze(
            DB_PATH, niche, data.get("source_url") or "",
            data.get("text") or "", data.get("metrics") or {},
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Phase 5 — expansion layer (platforms, reels, comment guardian, WhatsApp
# remote, credit guard, offline queue, backup vault, launch checklist,
# self-updater). Additive only.
# ---------------------------------------------------------------------------

@app.route("/expand")
def expand_page():
    return send_from_directory(os.path.join(ROOT, "templates"), "expand.html")


# --- platforms ---------------------------------------------------------------

@app.route("/api/platforms")
def api_platforms():
    """List all platform plug-ins with live status. Tokens are never exposed."""
    config = _load_fb_config()
    out = []
    plugins = platforms_list_mod()
    plugin_objs = plugins.values() if isinstance(plugins, dict) else plugins
    for plugin in plugin_objs:
        try:
            st = plugin.status(config or {})
            # Belt-and-braces: never leak anything token-shaped.
            detail = str(st.get("detail", ""))[:200]
            if len(detail) > 60 and any(k in detail.lower() for k in ("token", "secret", "key=")):
                detail = detail[:60] + "…"
            out.append({"slug": plugin.slug(), "name": plugin.name(),
                        "connected": bool(st.get("connected")),
                        "detail": detail,
                        "setup_notes": plugin.setup_notes()})
        except Exception as e:  # noqa: BLE001
            out.append({"slug": plugin.slug(), "name": plugin.name(),
                        "connected": False, "detail": str(e)[:200],
                        "setup_notes": plugin.setup_notes()})
    return jsonify({"platforms": out})


# --- reels -------------------------------------------------------------------

@app.route("/api/reels/queue", methods=["POST"])
def api_reels_queue():
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    images = data.get("images") or []
    if not niche or not images:
        return jsonify({"ok": False, "reason": "niche and images required"}), 400
    try:
        rid = reels_mod.queue_reel(DB_PATH, niche, images, data.get("caption") or "")
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "reel_id": rid})


@app.route("/api/reels")
def api_reels_list():
    try:
        return jsonify({"reels": reels_mod.list_reels(
            DB_PATH, niche=request.args.get("niche") or None,
            status=request.args.get("status") or None)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"reels": [], "error": str(e)}), 200


@app.route("/api/reels/build", methods=["POST"])
def api_reels_build():
    """Build one queued reel with ffmpeg (local, no network)."""
    data = request.get_json(silent=True) or {}
    reel_id = data.get("reel_id")
    if reel_id is None:
        return jsonify({"ok": False, "reason": "reel_id required"}), 400
    try:
        reels = reels_mod.list_reels(DB_PATH)
        reel = next((r for r in reels if r["id"] == int(reel_id)), None)
        if not reel:
            return jsonify({"ok": False, "reason": "reel not found"}), 200
        if not reels_mod.check_ffmpeg():
            return jsonify({"ok": False,
                            "reason": "ffmpeg not installed — reels need it."}), 200
        import json as _json
        imgs = _json.loads(reel["image_paths_json"])
        out_dir = os.path.join(WORKSPACE_DIR, "niches", reel["niche"], "output")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "reel_%d.mp4" % reel["id"])
        reels_mod.mark_reel(DB_PATH, reel["id"], "building")
        reels_mod.build_reel(imgs, reel.get("caption") or "", out_path)
        reels_mod.mark_reel(DB_PATH, reel["id"], "ready", out_path=out_path)
    except Exception as e:  # noqa: BLE001
        try:
            reels_mod.mark_reel(DB_PATH, int(reel_id), "failed")
        except Exception:  # noqa: BLE001
            pass
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "out_path": out_path})


# --- comment guardian ----------------------------------------------------------

@app.route("/api/comments/fetch", methods=["POST"])
def api_comments_fetch():
    """Pull recent comments for a post and queue suggested replies for review.
    Nothing is ever auto-posted."""
    data = request.get_json(silent=True) or {}
    niche = (data.get("niche") or "").strip()
    post_id = (data.get("post_id") or "").strip()
    if not (niche and post_id):
        return jsonify({"ok": False, "reason": "niche and post_id required"}), 400
    config = _load_fb_config()
    pages = (config or {}).get("facebook_pages") or {}
    page = pages.get(niche)
    if not page:
        return jsonify({"ok": False,
                        "reason": "no Facebook page configured for this niche"}), 200
    try:
        comments = comments_guard_mod.fetch_comments(
            page.get("page_id"), page.get("token"), post_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    ladder = _load_ladder()
    queued = 0
    for c in comments:
        verdict = comments_guard_mod.classify_comment(c.get("text", ""))
        if verdict != "genuine":
            continue  # spam/abuse never even get a draft
        try:
            reply = comments_guard_mod.suggest_reply(
                niche, c.get("text", ""), ladder=ladder)
            comments_guard_mod.queue_reply(
                DB_PATH, niche, post_id, c.get("id", ""), c.get("from", {}).get("name", ""),
                c.get("text", ""), verdict, reply)
            queued += 1
        except Exception:  # noqa: BLE001
            continue
    return jsonify({"ok": True, "fetched": len(comments), "queued": queued})


@app.route("/api/comments/replies")
def api_comments_replies():
    try:
        return jsonify({"replies": comments_guard_mod.list_replies(
            DB_PATH, niche=request.args.get("niche") or None,
            status=request.args.get("status") or None)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"replies": [], "error": str(e)}), 200


@app.route("/api/comments/replies/<int:reply_id>/approve", methods=["POST"])
def api_comments_approve(reply_id):
    try:
        comments_guard_mod.approve_reply(DB_PATH, reply_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True})


@app.route("/api/comments/replies/<int:reply_id>/reject", methods=["POST"])
def api_comments_reject(reply_id):
    try:
        comments_guard_mod.reject_reply(DB_PATH, reply_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True})


# --- WhatsApp remote -----------------------------------------------------------

@app.route("/api/remote/inbox")
def api_remote_inbox():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, sender, body, received_at, processed FROM wa_inbox"
            " ORDER BY id DESC LIMIT 50").fetchall()
        conn.close()
        return jsonify({"inbox": [dict(r) for r in rows]})
    except Exception as e:  # noqa: BLE001
        return jsonify({"inbox": [], "error": str(e)}), 200


@app.route("/api/remote/outbox")
def api_remote_outbox():
    try:
        return jsonify({"outbox": remote_mod.get_outbox_pending(DB_PATH)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"outbox": [], "error": str(e)}), 200


@app.route("/api/remote/process", methods=["POST"])
def api_remote_process():
    """Run the command protocol over unprocessed inbox messages."""
    try:
        processed = remote_mod.process_inbox(DB_PATH, remote_mod.default_handlers())
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "processed": processed})


@app.route("/api/remote/webhook", methods=["POST"])
def api_remote_webhook():
    """Documented webhook slot for future Twilio/Cloud-API wiring.
    Accepts {sender, body}; stores into the inbox for process_inbox()."""
    data = request.get_json(silent=True) or {}
    sender = (data.get("sender") or "").strip()
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"ok": False, "reason": "body required"}), 400
    try:
        remote_mod.webhook_ingest(DB_PATH, sender or "webhook", body)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "note": "queued — run /api/remote/process"})


# --- credit guard ---------------------------------------------------------------

@app.route("/api/credits")
def api_credits():
    config = _load_fb_config()
    try:
        status = credits_mod.check_and_enforce(DB_PATH, config or {})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 200
    return jsonify(status)


@app.route("/api/credits/resume", methods=["POST"])
def api_credits_resume():
    """Manual resume after an auto-pause (human decision only)."""
    try:
        credits_mod.clear_ai_pause(DB_PATH)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True})


# --- offline queue ---------------------------------------------------------------

@app.route("/api/offline")
def api_offline_list():
    try:
        return jsonify({"queue": offline_mod.list_queue(
            DB_PATH, status=request.args.get("status") or None)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"queue": [], "error": str(e)}), 200


@app.route("/api/offline/replay", methods=["POST"])
def api_offline_replay():
    """Replay queued work in FIFO order. Failed items stay visible."""
    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or "").strip()

    def _requeue_publish(payload):
        # Re-attempt an FB publish recorded while offline.
        config = _load_fb_config()
        if not config:
            raise RuntimeError("config not loaded — cannot replay publish")
        pub = publish_mod.FBPublisher(config, DB_PATH, dry_run=False)
        return pub.publish_photo(payload.get("label", "offline-replay"),
                                 payload["image_path"], payload.get("caption", ""),
                                 scheduled_utc=payload.get("scheduled_utc"))

    handlers = {"fb_publish": _requeue_publish}
    if kind and kind not in handlers:
        return jsonify({"ok": False,
                        "reason": "no handler for kind %r" % kind}), 400
    try:
        # FIFO replay of everything queued; unknown kinds are left untouched
        # by only registering known handlers.
        result = offline_mod.replay_queue(DB_PATH, handlers)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, **result})


# --- backup vault ------------------------------------------------------------------

@app.route("/api/backup/list")
def api_backup_list():
    try:
        return jsonify({"backups": backup_mod.list_backups(ROOT)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"backups": [], "error": str(e)}), 200


@app.route("/api/backup/create", methods=["POST"])
def api_backup_create():
    try:
        path = backup_mod.create_backup(ROOT)
        deleted = backup_mod.prune_backups(ROOT, keep=7)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:200]}), 200
    return jsonify({"ok": True, "path": os.path.basename(path),
                    "pruned": deleted})


@app.route("/api/backup/restore", methods=["POST"])
def api_backup_restore():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name or ".." in name or "/" in name or "\\" in name:
        return jsonify({"ok": False, "reason": "valid backup name required"}), 400
    zip_path = os.path.join(ROOT, "workspace", "backups", name)
    if not os.path.isfile(zip_path):
        return jsonify({"ok": False, "reason": "backup not found"}), 404
    try:
        result = backup_mod.restore_backup(zip_path, ROOT)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:300]}), 200
    return jsonify({"ok": True,
                    "pre_restore_backup": os.path.basename(result["pre_restore_backup"])})


# --- launch checklist ----------------------------------------------------------------

@app.route("/api/launch")
def api_launch():
    config = _load_fb_config()
    try:
        checks = launch_mod.run_checks(ROOT, db_path=DB_PATH, config=config)
    except Exception as e:  # noqa: BLE001
        return jsonify({"checks": [], "error": str(e)[:200]}), 200
    return jsonify({"checks": checks, "summary": launch_mod.summary(checks),
                    "all_pass": launch_mod.all_pass(checks)})


# --- self-updater ----------------------------------------------------------------------

@app.route("/api/update/check")
def api_update_check():
    dist = os.path.join(ROOT, "dist")
    try:
        result = update_mod.check_update(ROOT, dist)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 200
    return jsonify(result)


@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name or ".." in name or "/" in name or "\\" in name:
        return jsonify({"ok": False, "reason": "valid bundle name required"}), 400
    zip_path = os.path.join(ROOT, "dist", name)
    if not os.path.isfile(zip_path):
        return jsonify({"ok": False, "reason": "bundle not found"}), 404
    try:
        result = update_mod.apply_update(ROOT, zip_path)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "reason": str(e)[:300]}), 200
    return jsonify({"ok": True, "updated_to": result["updated_to"],
                    "backup": os.path.basename(result["backup"])})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057)
