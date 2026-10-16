# NicheForge

NicheForge is a **local desktop tool** that runs on your own PC and replicates the
niche content workflow end-to-end: ideas → details → captions → image prompts →
images → posting, across 14 content niches (Wicketverse, PakWire, Maloomat, Sukhan,
Paheli, Memeistan, Lafz, Deen, Parhai, Aangan, Angrezi, TechSathi, Imtihan, MarvelVerse).

It is a permanent replacement for ad-hoc manual/assistant-driven production: one
double-click starts a local web UI at `http://127.0.0.1:5057/` with an approval inbox,
a per-niche workspace, and an encrypted key ladder — no cloud account, no subscription.

## Setup (final — all 5 phases)

1. **Install Python 3.10+** from https://www.python.org/downloads/ (tick "Add python.exe to PATH" on Windows).
2. **Double-click `start.bat`** (Windows) or run `./start.sh` (Linux/macOS). The launcher installs dependencies, loads `.master-password` automatically, and opens the UI at http://127.0.0.1:5057/.
3. **Add your API keys** once, encrypted at rest:
   ```bash
   python setup_keys.py
   ```
   Guided entry for the Gemini free-key ladder (plus optional Groq / NVIDIA / OpenRouter / Pollinations / Z.ai), Facebook page tokens, and browser login emails. Merge-safe — re-running never wipes existing entries. Keys are stored encrypted in `config.json` (git-ignored, never committed, never logged).
4. **Facebook pages are pre-wired** — all 14 niche pages ship configured in the encrypted config; `/publish` works out of the box once `NICHEFORGE_PASSWORD` is set.
5. **For browser automation** (Phase 3): after pip install, run once `playwright install chromium`, then log each niche profile in via the `/browser` dashboard (one-tap re-login).
6. **For reels** (Phase 5): install ffmpeg and make sure it is on PATH.
7. **Open the inbox** at http://127.0.0.1:5057/ — generated ideas land here for your approve/reject picks, exactly like the current workflow.

Daily loop: **Inbox → Pipeline → Overlay Studio → Schedule → Publish** (top nav), with **Browser** for image generation, **Intel** for performance/trends, and **Expand** for platforms, reels, comments, remote control, credits, backups, launch checks and updates.

## Project layout

```
nicheforge/
├── start.bat / start.sh     # one-click launchers
├── app.py                   # Flask web UI (Phase 1: approval inbox, keys, status)
├── db.py                    # SQLite persistence (Phase 1: ideas, approvals, dedupe)
├── setup_keys.py            # encrypted key setup wizard (key ladder)
├── requirements.txt         # flask, requests, cryptography
├── config.json              # YOUR encrypted keys (git-ignored, created by setup_keys.py)
├── dna/                     # Niche DNA profiles - one strict rule file per niche
│   └── <niche>.json         #    (global rules + verbatim niche rules + system prompt)
├── providers/               # free-tier AI provider clients with auto-failover
├── templates/               # web UI templates
└── workspace/
    └── niches/
        └── <niche>/
            ├── assets/      # generated/downloaded images (git-ignored)
            └── output/      # final ready-to-post packages (git-ignored)
```

## Phase 5 scope (final build) — expansion layer

`/expand` dashboard + 24 API routes. All additive; Phases 1–4 re-verified green.

- ✅ **Platform plug-ins** (`platforms/`): register/status/publish/schedule interface.
  **Facebook is the working reference** (reuses `publish.FBPublisher`, dry-run default).
  Instagram, X, TikTok, YouTube, Website are honest stubs — "not connected yet" with
  per-platform setup notes in the UI. Nothing is faked.
- ✅ **Reel engine** (`reels.py`): 1080×1920 ffmpeg zoompan slideshow (≤60s) from local
  images; queue → build → ready flow. Needs ffmpeg on PATH.
- ✅ **Comment guardian** (`comments_guard.py`): fetches FB comments, spam/abuse filter,
  Key-Ladder-drafted replies for genuine questions. **Nothing auto-posts** — approval queue only.
- ✅ **WhatsApp remote** (`remote.py`): STATUS / PAUSE / RESUME / APPROVE / REJECT / QUEUE / HELP
  via inbox/outbox UI + documented `/api/remote/webhook` slot for later Twilio/Cloud-API wiring.
- ✅ **Credit guard** (`credits.py`): per-provider free-quota tracking from the ladder's usage
  table; warns at 80%, auto-pauses AI at 100% (manual resume).
- ✅ **Offline queue** (`offline.py`): durable SQLite queue with FIFO replay; approved items never lost.
- ✅ **Backup vault** (`backup.py`): one-click timestamped zips (DB, config, workspace, DNA),
  keeps last 7, safety backup before every restore/update.
- ✅ **Launch checklist** (`launch.py`): 10 pre-flight checks with pass/warn/fail.
- ✅ **Self-updater** (`update.py`, `VERSION` 5.0.0): local `dist/` bundle check, backup-first apply.

See `PHASES.md` for the "What's next / known limits" list.

## Phase 4 scope (this build) — intelligence layer

`intel/` package (11 modules) + `/intel` dashboard. Everything degrades gracefully:
no data → clear "no data" states, never crashes; no network → cached/degraded paths.

- ✅ **Performance Pulse** (`intel/pulse.py`): per-post metrics table (manual entry UI,
  CSV import, best-effort FB Graph insights fetch); per-niche best/worst + plain-language
  insights ("posts at 18:00 get ~2x reach").
- ✅ **Viral Feedback Loop** (`intel/feedback.py`): predicted-performance ★ badges in the
  Approval Inbox (heuristic cold-start, data-driven once metrics accumulate).
- ✅ **Niche Health Score** (`intel/health.py`): 0–100 per niche (consistency 40 /
  engagement trend 35 / freshness 25) with "needs attention" flags.
- ✅ **Shadow Ban Detector** (`intel/shadow.py`): >50% reach drop vs 7-day median →
  early-warning alert (never a diagnosis).
- ✅ **Trend Radar** (`intel/trends.py`): Google Trends PK + news RSS (≥15 min between
  polls), niche-matched alerts; X trends marked degraded (needs auth).
- ✅ **Newsjacking Autopilot** (`intel/newsjack.py`): breaking-news briefs into the
  Inbox within the run, with niche DNA rules attached.
- ✅ **Story Weaver** (`intel/weaver.py`): one event → 14 niche angle-matched briefs
  (each respecting its DNA).
- ✅ **Crisis Shield** (`intel/crisis.py`): serious-news trigger auto-pauses today's
  cheerful scheduled posts (UPDATE, never DELETE); human resumes from the UI.
- ✅ **Evergreen Recycler** (`intel/recycle.py`): 90-day+ top-engagement posts →
  refresh briefs (new caption angle + image tweak).
- ✅ **Festival Auto-Calendar** (`intel/festivals.py`): Pakistani occasions (lunar dates
  marked approximate), content packs generated 7 days ahead.
- ✅ **Viral Autopsy** (`intel/autopsy.py`): structured teardown (hook/format/CTA/timing)
  + "make our version" brief.

Everything beyond that — platform expansion (IG/X/TikTok/YouTube/website) — is Phase 5.
See `PHASES.md` for the full plan.

## Phase 3 scope (earlier build) — browser automation track

No-API track: real Chrome browsers driven locally on his Windows PC, strictly
sequential and human-looking. Safety is the core feature.

- ✅ **Profile Vault** (`browser_track/profiles.py`): per-niche isolated Chrome
  user-data dirs (`workspace/browser_profiles/<niche>/`); encrypted registry of
  login emails per service (ChatGPT/Claude/Gemini) via `setup_keys.py`;
  **Account Rotation Pool** — queue shifts to the next email's profile on park/pause
- ✅ **Human-Mimic Engine** (`browser_track/mimic.py`): 1-by-1 `TaskQueue`
  (never parallel), randomized delays, human typing-speed variation, mouse jitter
- ✅ **Stealth Scheduler** (`browser_track/stealth.py`): human hours 09:00–23:00 PKT,
  random 3–27 min start offsets, never round hours, Friday off-day
- ✅ **Rate-Limit Sentinel** (`browser_track/sentinel.py`): parks (service, email)
  on limit signals incl. HTTP 429, auto-resumes after cooldown, never hammers
- ✅ **Captcha & Block Guard** (`browser_track/guard.py`): pauses profile + UI alert
  on captcha/login wall/unusual activity; NEVER auto-retries (human resume only)
- ✅ **Session Health Monitor** (`browser_track/sessions.py`): login-state checks,
  expired flagging, one-tap re-login URLs
- ✅ **Image Queue Manager** (`browser_track/images.py`): Prompt Forge JSONs →
  niche ChatGPT profile → 4 versions → dated asset folders + `manifest.json`;
  contact-sheet HTML for one-tap picks; **Asset Auto-Organizer** + stray check
- ✅ **Paste-Safe Handoff** (`browser_track/paste_points.py`): KNOWN LIMITATION —
  automation cannot paste into some editors (e.g. Google Flow); UI banner
  ("Paste karo"), human pastes + Done, automation resumes; queueable for mornings
- ✅ **Competitor Harvest** (`browser_track/harvest.py`): nightly, sequential,
  ≥30s gaps, observation only; stops instantly on block signals
- ✅ **Comment Mining** (`browser_track/comments.py`): frequent questions/requests →
  idea seeds into the Idea Bank with source links
- ✅ **Browser dashboard** (`/browser` UI): stealth status, profiles + sync/resume,
  paste banner (10s poll), image queue + MockDriver dry-run, harvest targets +
  dry-run, login report
- ✅ DRY-RUN/simulation mode on every automation (default); `playwright` in
  requirements — run `playwright install chromium` once on his PC

Needs browser login emails for the profile vault: run `setup_keys.py` (it now asks
for them). Without them, everything degrades to clear status messages; dry-runs
work fully offline.

Everything beyond that — intelligence layer, platform expansion — is Phase 4+.
See `PHASES.md` for the full plan.

## Phase 2 scope (earlier build) — content pipeline

- ✅ **Research dossiers** (`research.py`): per approved idea, Key Ladder + niche DNA →
  structured JSON (facts/angles/sources/avoid); per-niche grounding switch
  (`grounding.json`: pakwire + maloomat grounded, creative niches fast)
- ✅ **Captions** (`captions.py`): humanized, niche-lane (Roman Urdu/English, en-GB),
  full details + non-spammy hashtags
- ✅ **Prompt Forge** (`prompts.py`): deterministic 8-section structured image prompts
  per niche (text-free bases for deen/sukhan/lafz/wicketverse; full-text cards for
  memeistan/techsathi/paheli/pakwire/maloomat; marvelverse backgrounds-only)
- ✅ **Urdu Overlay Studio** (`overlay.py` + `/overlay` UI): local Nastaleeq overlay
  (bundled Jameel Noori Nastaleeq, PIL raqm) for deen/sukhan/lafz
- ✅ **Slot Planner + Clash Detector** (`schedule.py` + `/schedule` UI): 09:00–21:00 PKT
  slots, ≥90 min per niche, no two posts within 30 min globally
- ✅ **FB Publisher** (`publish.py` + `/publish` UI): Graph API photo posts + scheduled
  posts; page tokens via `setup_keys.py` (encrypted); **dry-run default**
- ✅ Web UI: `/pipeline`, `/overlay`, `/schedule`, `/publish` (nav on every page)

Needs API keys for the AI steps: run `setup_keys.py`, then restart with the
`NICHEFORGE_PASSWORD` environment variable set. Without keys, the pipeline routes
explain what to do; overlay/schedule/publish-dry-run work keyless.

Everything beyond that — browser automation, intelligence layers, platform expansion —
is Phase 3+. See `PHASES.md` for the full plan.

## Phase 1 scope (earlier build)

- ✅ Local Flask scaffold with an **Approval Inbox** web UI
- ✅ **Niche DNA profiles** — verbatim per-niche rules + one strict system prompt each (see `dna/`)
- ✅ **Key Ladder** with automatic provider failover on errors/rate limits
- ✅ **Encrypted key config** via `setup_keys.py` (`cryptography`, git-ignored `config.json`)
- ✅ **Idea Bank + dedupe** — SQLite-backed, no repeats
- ✅ Per-niche **workspace folders** (`assets/`, `output/`)

Everything beyond that — research dossiers, caption/image pipelines, browser automation,
publishing, and intelligence layers — is Phase 2+. See `PHASES.md` for the full plan.
