# NicheForge Web

Website-based NicheForge — the local Flask app (`nicheforge_core/`, v5.0.0)
repackaged for cloud hosting with a flagship admin panel, built-in AI chatbot,
image studio, AI browser-apps workspace, and full error visibility for Jarvis.

**Admin URL pattern:** `https://<your-app>.up.railway.app/admin`

## What's inside

| Path | What |
|---|---|
| `/admin/` | Dashboard — 14 niche cards (green/amber/red), stat tiles |
| `/admin/batches` | Idea approval: card grid, one-tap ✓/✗, bulk select |
| `/admin/generate` | **Image Studio** — niche → prompt → provider → generate → gallery / use in batch |
| `/admin/gallery` | Image gallery with lightbox preview |
| `/admin/schedule` | Posting timeline (PKT) calendar view |
| `/admin/browser` | **AI Browser Apps** — Flow / ChatGPT / Gemini tabs, connection status, job queue |
| `/admin/chat` | **Forge Chat** — built-in AI assistant (Gemini key ladder) |
| `/admin/errors` | Error panel — expandable cards, tracebacks, one-click retry |
| `/admin/keys` | API keys + FB page tokens (masked), add-key forms |
| `/admin/api/alerts?key=…` | Machine-readable alerts for Jarvis (see below) |

All existing features are kept: 14 niche DNAs, idea bank + dedup, Gemini key
ladder with failover, per-niche browser profiles, FB Graph API publishing,
reels, intel layer, comments guardian.

## Deploy on Railway (recommended, free tier)

1. Push this folder to a GitHub repo (secrets are git-ignored: `config.json`,
   `*.db`, `error_logs/`, `alerts.jsonl`).
2. Railway → **New Project → Deploy from GitHub** → select the repo.
   `railway.json` + `Procfile` are auto-detected. Health check: `/healthz`.
3. **Variables** (Railway → Variables):
   - `NICHEFORGE_ADMIN_PASSWORD` = your admin password (required for /admin)
   - `NICHEFORGE_PASSWORD` = master password for the encrypted `config.json`
     (same one used by local `setup_keys.py`)
   - `FLASK_SECRET_KEY` = any long random string (optional; auto-derived if empty)
   - `ALERT_WEBHOOK_URL` = optional HTTPS endpoint that receives every error alert as JSON POST
4. **Keys:** the encrypted `config.json` is git-ignored. After first deploy,
   either (a) upload it once via Railway shell:
   `python nicheforge_core/setup_keys.py`, or (b) add keys from the
   **/admin/keys** page (needs `NICHEFORGE_PASSWORD` set first).
5. Open `https://<app>.up.railway.app/admin` → log in.

**Render:** `render.yaml` is included — same env vars, or use the Render
dashboard with `gunicorn web_app:app` as the start command.

**Local:** `pip install -r requirements.txt && python web_app.py`
→ http://127.0.0.1:5057/admin (set `NICHEFORGE_ADMIN_PASSWORD` first).

## New modules (web layer)

- **`chatbot.py`** — Forge assistant. Live DB context (niche stats, today's
  schedule, open errors) is injected into the system prompt; calls
  `KeyLadder.chat()` with full provider failover. History per session.
- **`imagegen.py`** — image job queue (`nf_image_jobs` table).
  Providers: `instant` (free API, server-side, seconds), `chatgpt` / `gemini` /
  `flow` (routed through signed-in browser sessions — see below).
- **`browser_apps.py`** — service registry (`nf_browser_services`) +
  sentinel rate-limit overlay. Each tab: status pill (signed in / needs login /
  rate-limited + reset time), "Open ↗" in new tab, pending jobs with
  copy-prompt + upload-result. **Flow paste helper:** Flow's prompt box cannot
  be pasted into by automation — the page copies the prompt and Hmb pastes it
  manually once, then uploads the result.
- **`error_report.py`** — `log_error()` writes every exception to: the
  `nf_errors` DB table, `error_logs/<id>.log` (full traceback), and
  `hidden_files/alerts.jsonl` (one JSON line per error). A Flask
  `got_request_exception` hook in `web_app.py` captures unhandled errors
  automatically; pipeline code can also use the `@reported(db, niche, stage)`
  decorator.

## How Jarvis reads alerts

1. **Local runs:** tail `hidden_files/alerts.jsonl` — one JSON object per line:
   `{"ts","error_id","niche","stage","error_type","message"}`.
2. **Cloud runs:** poll `GET /admin/api/alerts?key=<NICHEFORGE_ADMIN_PASSWORD>&since=<iso-ts>`
   → `{"ok":true,"alerts":[...]}`. (`since` filters; omit for last 100.)
3. **Push:** set `ALERT_WEBHOOK_URL` and every alert is POSTed as JSON too.
4. Full tracebacks: `/admin/errors` → expand a card, or
   `GET /admin/api/errors/<id>/traceback` (admin session).

Note: on Railway/Render the local filesystem is ephemeral — treat the alerts
API / webhook as the source of truth in production, not the on-disk JSONL.

## Admin login setup

```bash
export NICHEFORGE_ADMIN_PASSWORD="choose-a-strong-password"
python web_app.py
```

On Railway: Variables → add `NICHEFORGE_ADMIN_PASSWORD`. The login page shows
a clear setup hint if it is missing.

## Repo layout

```
nicheforge-web/
├── web_app.py            # entry point (wraps core app + admin)
├── admin/                # admin blueprint + dark-theme templates
│   ├── admin_bp.py
│   └── templates/        # dashboard, batches, generate, gallery, schedule,
│                         # browser, chat, errors, keys, login
├── chatbot.py            # Forge AI assistant engine
├── imagegen.py           # image generation job queue
├── browser_apps.py       # Flow / ChatGPT / Gemini workspace
├── error_report.py       # central error logging + alerts
├── nicheforge_core/      # the full local NicheForge app (v5.0.0), reused as-is
├── hidden_files/alerts.jsonl   # Jarvis monitor feed (local runs)
├── error_logs/           # per-error tracebacks
├── Procfile  railway.json  render.yaml  runtime.txt  requirements.txt
└── README.md
```

## Verified

- App boots locally; `/healthz` 200; all 9 admin pages 200 after login.
- Simulated failure → DB row + `error_logs/<id>.log` + `alerts.jsonl` line +
  visible on `/admin/errors` + returned by `/admin/api/alerts?key=…`.
- Idea approve API round-trip works; instant image generation produces a real
  JPEG; chat degrades gracefully (Roman Urdu notice) when no API keys are set.
