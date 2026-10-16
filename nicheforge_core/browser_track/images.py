"""NicheForge Phase 3 — Image Queue Manager + Asset Auto-Organizer.

Queue image-generation jobs from Phase 2 prompt JSONs, run them one at a
time through a duck-typed browser driver (ChatGPT lane), download all 4
versions per prompt into the asset tree, and build a contact-sheet picker
so Hmb can pick the best version per job.

Asset layout (under nicheforge/workspace):
    niches/<niche>/assets/<YYYY-MM-DD>/img_<jobid>_<n>.png
    niches/<niche>/assets/<YYYY-MM-DD>/manifest.json   (per job)
    niches/<niche>/assets/<YYYY-MM-DD>/contact_sheet_<date>.html

DRY-RUN is the default: with MockDriver nothing touches the network.
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.normpath(os.path.join(PACKAGE_DIR, "..", "workspace"))

STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
VALID_STATUSES = {STATUS_QUEUED, STATUS_DOWNLOADING, STATUS_DONE, STATUS_FAILED}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_image_tables(db_path):
    """Create image_jobs and image_picks tables if they don't exist."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS image_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                niche TEXT NOT NULL,
                idea_id TEXT NOT NULL,
                prompt_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS image_picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                niche TEXT NOT NULL,
                date TEXT NOT NULL,
                image_path TEXT NOT NULL,
                picked_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def list_jobs(db_path, niche=None, status=None):
    """Newest-first image jobs as dicts, optionally filtered."""
    init_image_tables(db_path)
    sql = ("SELECT id, niche, idea_id, prompt_path, status, created_at,"
           " finished_at, error FROM image_jobs")
    clauses, params = [], []
    if niche:
        clauses.append("niche = ?")
        params.append(niche)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC"
    conn = _connect(db_path)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def queue_from_prompts(db_path, niche, prompt_paths):
    """Insert one queued image job per prompt JSON path. Returns list of ids."""
    init_image_tables(db_path)
    ids = []
    conn = _connect(db_path)
    try:
        for p in prompt_paths:
            idea_id = os.path.splitext(os.path.basename(p))[0]
            idea_id = re.sub(r"^prompt_", "", idea_id)
            cur = conn.execute(
                "INSERT INTO image_jobs (niche, idea_id, prompt_path, status,"
                " created_at) VALUES (?, ?, ?, 'queued', ?)",
                (niche, idea_id, p, _utc_now()),
            )
            ids.append(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return ids


def _job(db_path, job_id):
    conn = _connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM image_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    finally:
        conn.close()


def _set_status(db_path, job_id, status, error=None, finished=False):
    conn = _connect(db_path)
    try:
        if finished:
            conn.execute(
                "UPDATE image_jobs SET status = ?, error = ?, finished_at = ?"
                " WHERE id = ?",
                (status, error, _utc_now(), job_id),
            )
        else:
            conn.execute(
                "UPDATE image_jobs SET status = ?, error = ? WHERE id = ?",
                (status, error, job_id),
            )
        conn.commit()
    finally:
        conn.close()


def _assets_dir(niche, date=None, root=None):
    base = os.path.join(root or DEFAULT_ROOT, "niches", niche, "assets")
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = os.path.join(base, date)
    os.makedirs(d, exist_ok=True)
    return d


def _read_prompt_text(prompt_path):
    with open(prompt_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    text = data.get("prompt_text") or ""
    if not isinstance(text, str):
        text = json.dumps(data, ensure_ascii=False)[:4000]
    return text


class ImageJobRunner:
    """Runs image_jobs sequentially through a browser driver.

    Duck-typed driver must provide:
        goto(url) -> None
        submit_prompt(text) -> None
        wait_for_images(timeout) -> list of bytes-or-paths
        download_image(i) -> bytes (or a path to an image file)

    guards: optional list of callables f(text) -> signal | None. Each is
    fed driver-visible text (prompt echoes, status strings). On the first
    non-None signal the job is marked failed and the run STOPS immediately
    — never hammer a site that is asking you to slow down.

    dry_run=True (default): still runs the full pipeline, but MockDriver
    only produces canned PNGs, so nothing touches the network.
    """

    def __init__(self, db_path, driver, mimic_cfg=None, dry_run=True,
                 assets_root=None, guards=None):
        self.db_path = db_path
        self.driver = driver
        self.mimic_cfg = dict(mimic_cfg or {})
        self.dry_run = dry_run
        self.assets_root = assets_root
        self.guards = list(guards or [])
        self.chatgpt_url = self.mimic_cfg.get(
            "chatgpt_url", "https://chatgpt.com/")

    def _check_guards(self, text):
        for guard in self.guards:
            signal = guard(text)
            if signal:
                return signal
        return None

    def run_job(self, job_id):
        """Run one job end to end. Returns (ok, info) dict-ish tuple."""
        init_image_tables(self.db_path)
        job = _job(self.db_path, job_id)
        if job is None:
            return (False, "job #%s not found" % job_id)
        if job["status"] != STATUS_QUEUED:
            return (False, "job #%s not queued (status=%s)"
                    % (job_id, job["status"]))
        try:
            prompt_text = _read_prompt_text(job["prompt_path"])
        except Exception as exc:  # unreadable prompt JSON
            _set_status(self.db_path, job_id, STATUS_FAILED,
                        error="prompt read failed: %s" % exc, finished=True)
            return (False, "prompt read failed: %s" % exc)

        _set_status(self.db_path, job_id, STATUS_DOWNLOADING)
        try:
            self.driver.goto(self.chatgpt_url)
            self.driver.submit_prompt(prompt_text)
            signal = self._check_guards("submitted prompt")
            if signal:
                _set_status(self.db_path, job_id, STATUS_FAILED,
                            error="guard signal: %s" % signal, finished=True)
                return (False, "stopped by guard: %s" % signal)

            previews = self.driver.wait_for_images(
                self.mimic_cfg.get("image_wait_timeout", 300))
            signal = self._check_guards("received %d previews" % len(previews))
            if signal:
                _set_status(self.db_path, job_id, STATUS_FAILED,
                            error="guard signal: %s" % signal, finished=True)
                return (False, "stopped by guard: %s" % signal)

            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            day_dir = _assets_dir(job["niche"], date, root=self.assets_root)
            written = []
            for i in range(len(previews)):
                payload = self.driver.download_image(i)
                if isinstance(payload, (bytes, bytearray)):
                    data = bytes(payload)
                else:  # a path — read the file
                    with open(payload, "rb") as fh:
                        data = fh.read()
                name = "img_%d_%d.png" % (job_id, i)
                path = os.path.join(day_dir, name)
                with open(path, "wb") as fh:
                    fh.write(data)
                written.append(path)

            manifest = {
                "job_id": job_id,
                "idea_id": job["idea_id"],
                "prompt_text": prompt_text[:500],
                "source": "mock" if self.dry_run else "chatgpt",
                "downloaded_at": _utc_now(),
                "files": [os.path.basename(p) for p in written],
            }
            with open(os.path.join(day_dir,
                                   "manifest_%d.json" % job_id), "w",
                      encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            _set_status(self.db_path, job_id, STATUS_FAILED,
                        error=str(exc), finished=True)
            return (False, "job #%d failed: %s" % (job_id, exc))

        _set_status(self.db_path, job_id, STATUS_DONE, finished=True)
        return (True, "job #%d done, %d images" % (job_id, len(written)))


class MockDriver:
    """Duck-typed stand-in for the ChatGPT browser driver.

    Produces 4 canned PNGs (generated with PIL, or minimal valid PNG
    bytes if PIL is missing) and records every call in `log` for test
    assertions. Never touches the network.
    """

    def __init__(self):
        self.log = []
        self._pngs = [_canned_png(i) for i in range(4)]

    def goto(self, url):
        self.log.append(("goto", url))

    def submit_prompt(self, text):
        self.log.append(("submit_prompt", text[:80]))

    def wait_for_images(self, timeout=300):
        self.log.append(("wait_for_images", timeout))
        return list(self._pngs)

    def download_image(self, i):
        self.log.append(("download_image", i))
        return self._pngs[i]


def _canned_png(i):
    try:
        from PIL import Image
        import io
        img = Image.new("RGB", (128, 128),
                        [(200, 60, 60), (60, 160, 60),
                         (60, 90, 200), (150, 120, 40)][i % 4])
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # Minimal valid 1x1 PNG (RGBA), little-endian CRC placeholders are
        # real — this is a valid transparent pixel PNG.
        return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
                b"\x0d\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def record_pick(db_path, niche, date, image_path):
    """Record Hmb's pick of one image. Returns the pick id."""
    init_image_tables(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO image_picks (niche, date, image_path, picked_at)"
            " VALUES (?, ?, ?, ?)",
            (niche, date, image_path, _utc_now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _picked_set(db_path, niche, date):
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT image_path FROM image_picks WHERE niche = ? AND date = ?",
            (niche, date),
        ).fetchall()
        return {r["image_path"] for r in rows}
    finally:
        conn.close()


def build_contact_sheet(db_path, niche, date, root=None):
    """Write contact_sheet_<date>.html with 4-up grids per job.

    Each image gets a <button>Pick</button> with a data-image-path
    attribute — the Flask UI wires clicks to record_pick().
    """
    init_image_tables(db_path)
    day_dir = _assets_dir(niche, date, root=root)
    picked = _picked_set(db_path, niche, date)

    jobs = {}
    for name in sorted(os.listdir(day_dir)):
        m = re.match(r"^img_(\d+)_(\d+)\.png$", name)
        if m:
            jobs.setdefault(int(m.group(1)), []).append(name)

    cards = []
    for job_id in sorted(jobs):
        imgs = []
        for name in sorted(jobs[job_id]):
            cls = "picked" if os.path.join(day_dir, name) in picked else ""
            imgs.append(
                '<div class="shot %s">'
                '<img src="%s" alt="%s">'
                '<button data-image-path="%s" data-job="%d">Pick</button>'
                "</div>" % (cls, name, name,
                            os.path.join(day_dir, name), job_id))
        cards.append(
            '<section class="job"><h2>Job #%d</h2>'
            '<div class="grid">%s</div></section>'
            % (job_id, "".join(imgs)))

    html = """<!DOCTYPE html>
<html lang="en-GB">
<head><meta charset="utf-8">
<title>Contact sheet %s — %s</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:24px}
h1{font-size:1.3rem} .job{margin-bottom:32px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.shot{background:#1c1c1c;border-radius:8px;padding:8px;text-align:center}
.shot img{width:100%%;border-radius:4px;display:block}
.shot.picked{outline:2px solid #d4af37}
button{margin-top:8px;padding:6px 18px;cursor:pointer}
</style></head>
<body>
<h1>Contact sheet — %s (%s)</h1>
%s
<p>Pick buttons call record_pick() via the Flask UI.</p>
<script>
document.querySelectorAll("button[data-image-path]").forEach(function(btn){
  btn.addEventListener("click", function(){
    var p = btn.getAttribute("data-image-path");
    fetch("http://127.0.0.1:5057/api/browser/images/pick", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({niche: %s, date: %s, image_path: p})
    }).then(function(r){ return r.json(); }).then(function(j){
      if (j.ok) { btn.closest(".shot").classList.add("picked"); btn.textContent = "Picked ✓"; }
      else { alert("Pick failed: " + (j.reason || "unknown")); }
    }).catch(function(){ alert("Pick failed: is NicheForge running?"); });
  });
});
</script>
</body></html>""" % (date, niche, niche, date, "".join(cards) or "<p>No images yet.</p>",
                      json.dumps(niche), json.dumps(date))

    out = os.path.join(day_dir, "contact_sheet_%s.html" % date)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out


def organize_assets(niche, root=None):
    """Ensure dated dirs exist and every PNG has a manifest.

    Creates a stub manifest_<jobid>.json for any PNG whose job manifest
    is missing. Returns list of manifest paths created.
    """
    base = os.path.join(root or DEFAULT_ROOT, "niches", niche, "assets")
    os.makedirs(base, exist_ok=True)
    created = []
    for date in sorted(os.listdir(base)):
        day_dir = os.path.join(base, date)
        if not os.path.isdir(day_dir):
            continue
        for name in sorted(os.listdir(day_dir)):
            m = re.match(r"^img_(\d+)_(\d+)\.png$", name)
            if not m:
                continue
            job_id = int(m.group(1))
            mpath = os.path.join(day_dir, "manifest_%d.json" % job_id)
            if not os.path.exists(mpath):
                stub = {
                    "job_id": job_id,
                    "prompt_text": "",
                    "source": "unknown",
                    "downloaded_at": _utc_now(),
                    "files": [name],
                    "note": "stub created by organize_assets",
                }
                with open(mpath, "w", encoding="utf-8") as fh:
                    json.dump(stub, fh, ensure_ascii=False, indent=2)
                created.append(mpath)
    return created


def verify_no_strays(niche, root=None):
    """Return PNGs under the asset tree whose job manifest is missing."""
    base = os.path.join(root or DEFAULT_ROOT, "niches", niche, "assets")
    strays = []
    if not os.path.isdir(base):
        return strays
    for date in sorted(os.listdir(base)):
        day_dir = os.path.join(base, date)
        if not os.path.isdir(day_dir):
            continue
        for name in sorted(os.listdir(day_dir)):
            m = re.match(r"^img_(\d+)_(\d+)\.png$", name)
            if not m:
                continue
            job_id = int(m.group(1))
            if not os.path.exists(
                    os.path.join(day_dir, "manifest_%d.json" % job_id)):
                strays.append(os.path.join(day_dir, name))
    return strays
