# NicheForge — 5-Phase Plan

NicheForge is the local PC tool that replicates the niche content workflow
(ideas → details → captions → prompts → images → post) for 14 niches, built to be a
permanent, low-cost solution: free AI key ladder, per-niche Chrome profiles, human-mimic
sequential execution, and the approval-inbox workflow throughout.

---

## Phase 1 — Foundation ✅ DONE (this build)

The local tool is runnable and the strict per-niche rule layer exists.

- **Scaffold**: Flask app (`app.py`), SQLite persistence (`db.py`), one-click launchers
  (`start.bat` / `start.sh`), light dependency set (`flask`, `requests`, `cryptography`).
- **Niche DNA profiles** (`dna/<niche>.json`): 14 niches, each with the verbatim global
  rules, verbatim niche rules, and one strict system prompt that composes both — used as
  the injected guardrail for every AI call for that niche.
- **Key Ladder with auto-failover**: free-tier provider chain
  (Gemini → Groq → NVIDIA → OpenRouter → Pollinations → Z.ai); automatic failover to the
  next key/provider on errors, rate limits, or quota exhaustion.
- **Encrypted key config**: `setup_keys.py` wizard stores keys encrypted at rest in
  `config.json` (git-ignored; never committed, never logged).
- **Idea Bank + dedupe**: SQLite-backed idea store per niche; new ideas are checked
  against everything seen before so nothing repeats.
- **Approval Inbox web UI**: every generated batch lands in the inbox for
  approve / reject picks before anything moves downstream.
- **Per-niche workspace folders**: `workspace/niches/<niche>/assets/` and
  `workspace/niches/<niche>/output/` for the 14 niches.

---

## Phase 2 — Content Pipeline ✅ DONE

Turns approved ideas into finished, post-ready content packages.

- **Research dossier builder** (`research.py`) with a **per-niche grounding switch**
  (`grounding.json`: pakwire + maloomat grounded, creative niches skip grounding for
  speed). Dossiers saved as structured JSON (facts/angles/sources/avoid) per idea.
- **Caption generator** (`captions.py`): humanized captions via the Key Ladder using
  niche DNA — Roman Urdu/English per niche, en-GB spelling, full details + relevant,
  non-spammy hashtags. (Caption *style memory* learning is a Phase 4 upgrade.)
- **Image prompt forge** (`prompts.py`): deterministic composer producing detailed
  JSON image prompts following the universal 8-section structured prompt convention,
  with per-niche text rules baked in (deen/sukhan/lafz/wicketverse text-free for
  local overlay; memeistan/techsathi/paheli/pakwire/maloomat full-text cards;
  marvelverse backgrounds-only hard negative).
- **Urdu Nastaleeq overlay studio** (`overlay.py` + `/overlay` UI): crisp local text
  compositing (bundled Jameel Noori Nastaleeq, PIL raqm shaping) — Sukhan/Lafz/Deen
  cards get exact Urdu overlaid locally, never AI-generated Urdu text on images.
- **Smart slot planner + clash detector** (`schedule.py` + `/schedule` UI): approved
  ideas assigned to 09:00–21:00 PKT slots with ≥90-minute per-niche gaps and a global
  no-two-posts-within-30-minutes rule; clash detection across all niches.
- **FB publisher** (`publish.py` + `/publish` UI): photo posts + scheduled posts via
  the Facebook Graph API; page tokens collected by `setup_keys.py` into the
  encrypted config; dry-run mode is the default; every attempt logged to the DB.
- **Pipeline UI** (`/pipeline`): one click runs dossier → caption → prompt for an
  approved idea and links the artefacts.
- Deferred to a later phase (were in the original Phase 2 sketch, out of scope for
  this build): **real-photo fetcher**, **overnight batch runner**.

---

## Phase 3 — Browser Automation Track ✅ DONE

The no-API track: real Chrome browsers driven locally on his Windows PC,
strictly sequential and human-looking. Safety is the core feature.

- **Profile Vault** (`browser_track/profiles.py`): per-niche isolated Chrome
  user-data dirs under `workspace/browser_profiles/<niche>/`; encrypted
  registry of which email is logged into which profile for ChatGPT / Claude /
  Gemini (emails collected by `setup_keys.py` into the encrypted config);
  **Account Rotation Pool** — multiple emails per service, queue shifts to the
  next email's profile when one is parked/paused.
- **Human-Mimic Engine** (`browser_track/mimic.py`): strictly sequential 1-by-1
  `TaskQueue` (re-entrant runs raise instead of deadlocking), randomized
  action delays, human-like typing speed variation, jittered mouse moves —
  never parallel, the anti-ban core.
- **Stealth Scheduler** (`browser_track/stealth.py`): automation only during
  human hours (default 09:00–23:00 PKT), random 3–27 min start offsets, never
  on round hours, random off-days (default Friday).
- **Rate-Limit Sentinel** (`browser_track/sentinel.py`): watches page text /
  HTTP 429 for limit signals; parks the (service, email) with a cooldown and
  auto-resumes after; never hammers.
- **Captcha & Block Guard** (`browser_track/guard.py`): on captcha / login
  wall / unusual activity — immediately pauses the profile, logs, raises a UI
  alert. NEVER auto-retries; only an explicit human resume re-activates.
- **Session Health Monitor** (`browser_track/sessions.py`): login-state
  heuristics per service, expired-session flagging, one-tap re-login URLs.
- **Image Queue Manager** (`browser_track/images.py`): takes Prompt Forge
  JSONs, submits to the niche's ChatGPT profile, waits for 4 versions,
  downloads to dated asset folders with `manifest.json`; **Asset
  Auto-Organizer** (`organize_assets` / `verify_no_strays`); contact-sheet
  HTML for his one-tap pick.
- **Paste-Safe Handoff** (`browser_track/paste_points.py`): KNOWN LIMITATION —
  automation cannot paste into some editors (e.g. Google Flow's prompt box).
  Human paste points: tool navigates to the exact page, shows a UI banner
  ("Paste karo"), waits for his paste + Done click, then resumes. Queueable
  for morning batching.
- **Competitor Harvest** (`browser_track/harvest.py`): nightly, sequential,
  slow (≥30s gaps), observation only — post snippets, like/comment counts,
  posting times into SQLite; stops instantly on any block signal.
- **Comment Mining** (`browser_track/comments.py`): scrapes comments, extracts
  frequent questions/requests → idea seeds into the Idea Bank with source
  links (dedup rejections reported honestly).
- **Browser dashboard** (`/browser` UI): stealth status, profile table with
  sync/resume, paste banner (polls every 10s), image queue + MockDriver
  dry-run, harvest targets + dry-run, login-session report.
- Every automation ships with a **DRY-RUN / simulation mode** (default) —
  MockDriver-based, zero network — so he can test without touching real
  accounts. `playwright` added to requirements (`playwright install chromium`
  runs once on his PC); all modules import it lazily so tests run without it.

---

## Phase 4 — Intelligence Layer ✅ DONE

Gets approved content out to every platform.

- **Facebook Graph publisher**: posts to the connected Pages with scheduling, using the
  approved long-lived tokens.
- **Cross-platform adaptor** with a plug-in bay: Instagram, X, TikTok, YouTube, and a
  website posting plug-in bay for future platforms.
- **Reel script generator**: short-form scripts (hooks-first) for the 1 reel/niche/day
  rhythm.
- **First-comment engine**: auto-posts the first comment (hashtags/CTA) right after
  publishing.
- **Paheli answer engine**: scheduled answer reveals for riddle posts (answers are never
  on the image).
- **Asset auto-organizer**: published assets get filed, renamed, and archived per niche
  automatically.

---

## Phase 5 — Expansion Layer ✅ DONE (final build)

Everything a growing operation needs beyond the core pipeline. All additive;
Phases 1–4 untouched and re-verified.

- **Platform plug-in slots** ✅ DONE (`platforms/` + `/api/platforms`): clean
  register/status/publish/schedule interface. **Facebook is the working reference**
  implementation (reuses `publish.FBPublisher`, dry-run default). Instagram, X,
  TikTok, YouTube, Website are honest stubs — status "not connected yet" with
  per-platform setup notes in the UI (what the user must connect/provide). No
  fake "working" claims anywhere.
- **Reel engine** ✅ DONE (`reels.py`): assembles vertical 1080×1920 reels from
  local images via ffmpeg (zoompan Ken Burns slideshow, ≤60s); queue → build →
  ready flow in `/expand`; slot-note field for the slot planner.
- **Comment guardian** ✅ DONE (`comments_guard.py`): fetches recent FB post
  comments, spam/abuse filter with blocklist, Key-Ladder-drafted replies for
  genuine questions. **NOTHING auto-posts** — every reply waits in the `/expand`
  approval queue.
- **WhatsApp remote** ✅ DONE (`remote.py`): command protocol — STATUS, PAUSE /
  RESUME niche, APPROVE / REJECT idea, QUEUE, HELP — via a polling inbox/outbox
  in the UI plus a documented `/api/remote/webhook` slot for later
  Twilio/Cloud-API wiring. No real WhatsApp connection in v1.
- **Credit guard** ✅ DONE (`credits.py`): reads the ladder's usage table,
  per-provider free-quota estimates (configurable via config.json "quotas");
  UI warnings at 80%, auto-pause of AI features at 100% (manual resume only).
- **Offline queue** ✅ DONE (`offline.py`): failed network work stored durably in
  SQLite with retry state; "replay queue" button replays FIFO when back online.
  Approved items are never lost.
- **Auto backup vault** ✅ DONE (`backup.py`): one-click timestamped zip of DB,
  config.json, workspace, DNA (safety backup before every restore/update);
  keeps last 7 automatically.
- **Launch checklist** ✅ DONE (`launch.py` + `/expand`): 10 pre-flight checks
  (config, password env, 14 pages, DB, disk, ffmpeg, playwright, fonts,
  workspace dirs, VERSION) with pass/warn/fail each.
- **Self-updater** ✅ DONE (`update.py`, `VERSION` = 5.0.0): checks a local
  `dist/` folder for a newer bundle, applies backup-first. No network.

---

## What's next / known limits

Built deliberately as v1 limits — each is a clean extension point, not a bug:

1. **Platform stubs** (Instagram, X, TikTok, YouTube, Website): follow each
   `setup_notes()` in `/expand`, then implement the API calls inside the stub
   (same `PlatformPlugin` interface — no app changes needed).
2. **WhatsApp remote**: needs a Twilio or WhatsApp Cloud API number wired to
   `POST /api/remote/webhook`; the outbox sender loop is the remaining piece.
3. **Reel captions** are stored as video metadata, not burned in — add a
   drawtext/overlay step in `reels.build_reel` when wanted.
4. **Trend radar X coverage** needs X API auth (stubbed degraded); Google
   Trends PK + news RSS work now.
5. **Credit quotas** are documented estimates — tune them in config.json
   `"quotas"` once real free-tier numbers are observed.
6. **Newsjacking / weaver / autopsy / recycle** use template briefs in v1;
   they accept the Key Ladder for AI-drafted versions when keys are configured.
7. **Browser track** runs real Chrome only on his PC (`playwright install
   chromium` once); all automation is dry-run-testable here.
8. **Crisis scan** is manual-trigger via `/intel` in v1 — wire a scheduler
   (Windows Task Scheduler) for automatic scans.
