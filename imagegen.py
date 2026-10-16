"""NicheForge Web — image generator module.

Flow: pick niche -> write/select prompt (or pick from an idea) -> choose
provider -> generate -> preview in gallery -> one-tap "use in batch" or
download. Multiple generations can be queued.

Providers:
  * instant  — free API (Pollinations, no key needed). Runs server-side,
               image ready in seconds.
  * chatgpt  — routed through the signed-in ChatGPT browser session
               (see browser_apps). Job is queued; the prompt is copied from
               the Browser Apps page, generated in ChatGPT, and the result
               is uploaded back.
  * gemini   — routed through the signed-in Gemini browser session
               (same pattern as chatgpt).
  * flow     — routed through Google Flow (text-to-image). Same browser
               pattern + the manual-paste helper (Flow's prompt box cannot
               be pasted into by automation).

Browser-routed jobs NEVER fake a result: status stays queued until a real
image file is uploaded.
"""

import datetime
import os
import sqlite3
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(ROOT, "nicheforge_core")
WORKSPACE_DIR = os.path.join(CORE_DIR, "workspace")

PROVIDERS = [
    ("instant", "Instant (free, no key)"),
    ("chatgpt", "ChatGPT (browser session)"),
    ("gemini", "Gemini (browser session)"),
    ("flow", "Google Flow (browser session)"),
]
BROWSER_PROVIDERS = {"chatgpt", "gemini", "flow"}

SERVICE_URL = {
    "chatgpt": "https://chatgpt.com/",
    "gemini": "https://gemini.google.com/",
    "flow": "https://flow.google.com/",
}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def init_imagegen_tables(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nf_image_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                niche TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT 'instant',
                status TEXT NOT NULL DEFAULT 'queued',
                result_path TEXT DEFAULT '',
                idea_id INTEGER,
                error TEXT DEFAULT ''
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _result_dir(niche):
    d = os.path.join(WORKSPACE_DIR, "niches", niche or "general", "assets",
                     "imagegen")
    os.makedirs(d, exist_ok=True)
    return d


def create_job(db_path, niche, prompt, provider="instant", idea_id=None):
    """Create a job; instant jobs run immediately, browser jobs queue."""
    init_imagegen_tables(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO nf_image_jobs (ts, niche, prompt, provider, status,"
            " idea_id) VALUES (?, ?, ?, ?, 'queued', ?)",
            (utc_now(), niche or "", prompt or "", provider, idea_id),
        )
        job_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    if provider == "instant":
        _run_instant(db_path, job_id)
    return job_id


def _run_instant(db_path, job_id):
    """Generate via the free Pollinations image API (server-side)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        job = conn.execute("SELECT * FROM nf_image_jobs WHERE id = ?",
                           (job_id,)).fetchone()
        if not job:
            return
        niche, prompt = job["niche"], job["prompt"]
        conn.execute("UPDATE nf_image_jobs SET status='generating' WHERE id=?",
                     (job_id,))
        conn.commit()
        try:
            encoded = urllib.parse.quote(prompt[:1500])
            url = ("https://image.pollinations.ai/prompt/%s"
                   "?width=1080&height=1080&nologo=true&seed=%d"
                   % (encoded, job_id))
            req = urllib.request.Request(url, headers={"User-Agent": "NicheForge/1.0"})
            data = urllib.request.urlopen(req, timeout=120).read()
            if len(data) < 20000:  # suspiciously small = probably an error page
                raise RuntimeError("image API returned too little data")
            out = os.path.join(_result_dir(niche),
                               "imggen_%d.jpg" % job_id)
            with open(out, "wb") as fh:
                fh.write(data)
            rel = os.path.relpath(out, CORE_DIR)
            conn.execute(
                "UPDATE nf_image_jobs SET status='done', result_path=? WHERE id=?",
                (rel, job_id))
        except Exception as exc:  # noqa: BLE001
            conn.execute(
                "UPDATE nf_image_jobs SET status='failed', error=? WHERE id=?",
                (str(exc)[:500], job_id))
        conn.commit()
    finally:
        conn.close()


def attach_result(db_path, job_id, file_storage, filename_hint="upload"):
    """Attach a browser-generated image file to a queued job."""
    init_imagegen_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        job = conn.execute("SELECT * FROM nf_image_jobs WHERE id = ?",
                           (job_id,)).fetchone()
        if not job:
            raise ValueError("job not found")
        ext = os.path.splitext(filename_hint)[1].lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"
        out = os.path.join(_result_dir(job["niche"]),
                           "imggen_%d_browser%s" % (job_id, ext))
        file_storage.save(out)
        rel = os.path.relpath(out, CORE_DIR)
        conn.execute(
            "UPDATE nf_image_jobs SET status='done', result_path=?, error=''"
            " WHERE id=?", (rel, job_id))
        conn.commit()
        return rel
    finally:
        conn.close()


def list_jobs(db_path, status=None, limit=60):
    init_imagegen_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM nf_image_jobs"
        params = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_job(db_path, job_id):
    init_imagegen_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM nf_image_jobs WHERE id = ?",
                           (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def use_in_batch(db_path, job_id):
    """Copy the finished image into the niche output folder for posting."""
    job = get_job(db_path, job_id)
    if not job or job["status"] != "done" or not job["result_path"]:
        raise ValueError("job has no finished image yet")
    src = os.path.join(CORE_DIR, job["result_path"])
    if not os.path.isfile(src):
        raise ValueError("image file missing on disk")
    out_dir = os.path.join(WORKSPACE_DIR, "niches", job["niche"] or "general",
                           "output")
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(src)[1]
    dst = os.path.join(out_dir, "batch_img_%d%s" % (job_id, ext))
    with open(src, "rb") as fh_in, open(dst, "wb") as fh_out:
        fh_out.write(fh_in.read())
    return os.path.relpath(dst, CORE_DIR)
