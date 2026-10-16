"""NicheForge reel builder (Phase 5).

Turns a set of post images into a vertical 1080x1920 MP4 slideshow with a
slow Ken Burns (zoompan) effect, ready for reels/shorts distribution.

ffmpeg is an OPTIONAL heavy dependency: it is never imported, only detected
via shutil.which(). build_reel() raises RuntimeError with a clear message
when ffmpeg is missing.

Queue table:
    reel_queue(id, niche, image_paths_json, caption, status, out_path,
               slot_note, created_at)
status is one of: queued, building, ready, failed.
slot_note is a plain string; slot-planner integration happens in the app
layer, which sets the note through schedule_reel().
"""
import json
import os
import shutil
import sqlite3
import subprocess

from db import _connect, utc_now

REEL_W, REEL_H = 1080, 1920
REEL_FPS = 30
VALID_REEL_STATUSES = {"queued", "building", "ready", "failed"}


def check_ffmpeg():
    """Return True when an ffmpeg binary is on PATH."""
    return shutil.which("ffmpeg") is not None


def init_reel_tables(db_path):
    """Create the reel_queue table if it doesn't exist (idempotent)."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reel_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                niche TEXT NOT NULL,
                image_paths_json TEXT NOT NULL DEFAULT '[]',
                caption TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                out_path TEXT DEFAULT '',
                slot_note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def queue_reel(db_path, niche, image_paths, caption=""):
    """Add a reel build job; returns the new row id."""
    init_reel_tables(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO reel_queue (niche, image_paths_json, caption, status,"
            " out_path, slot_note, created_at) VALUES (?, ?, ?, 'queued', '', '', ?)",
            (niche, json.dumps(list(image_paths or [])), caption or "",
             utc_now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_reels(db_path, niche=None, status=None):
    """List reel jobs, optionally filtered by niche and/or status."""
    init_reel_tables(db_path)
    query = "SELECT * FROM reel_queue WHERE 1=1"
    params = []
    if niche:
        query += " AND niche = ?"
        params.append(niche)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id ASC"
    conn = _connect(db_path)
    try:
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def mark_reel(db_path, reel_id, status, out_path=None):
    """Update a reel job's status (and optionally its output path)."""
    if status not in VALID_REEL_STATUSES:
        raise ValueError(
            "Invalid reel status {!r}; valid: {}".format(
                status, ", ".join(sorted(VALID_REEL_STATUSES))
            )
        )
    init_reel_tables(db_path)
    conn = _connect(db_path)
    try:
        if out_path is None:
            conn.execute(
                "UPDATE reel_queue SET status = ? WHERE id = ?",
                (status, reel_id),
            )
        else:
            conn.execute(
                "UPDATE reel_queue SET status = ?, out_path = ? WHERE id = ?",
                (status, out_path, reel_id),
            )
        conn.commit()
    finally:
        conn.close()


def schedule_reel(db_path, reel_id, slot_note):
    """Record an optional slot note on a reel job (plain string field)."""
    init_reel_tables(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE reel_queue SET slot_note = ? WHERE id = ?",
            (slot_note or "", reel_id),
        )
        conn.commit()
    finally:
        conn.close()


def build_reel(image_paths, caption_text, out_path, per_image_secs=3,
               max_total_secs=55):
    """Build a 1080x1920 vertical MP4 slideshow with a Ken Burns effect.

    Each image is scaled to fill 1080x1920 (cropped), then slowly zoomed via
    zoompan. The per-image duration is reduced evenly if the total would
    exceed max_total_secs. caption_text is stored as the video title metadata;
    text burn-in is left to the app layer.

    Raises RuntimeError if ffmpeg is not installed; ValueError if no usable
    images are given. Returns out_path.
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "ffmpeg is not installed or not on PATH (checked with "
            "shutil.which). Install ffmpeg to build reels."
        )
    images = [p for p in (image_paths or []) if p and os.path.isfile(p)]
    if not images:
        raise ValueError("build_reel needs at least one existing image file")

    n = len(images)
    seg = float(per_image_secs or 3)
    if seg * n > max_total_secs:
        seg = float(max_total_secs) / n
    frames = max(1, int(round(seg * REEL_FPS)))

    cmd = ["ffmpeg", "-y"]
    for img in images:
        cmd += ["-i", img]

    chain = []
    for i in range(n):
        chain.append(
            "[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            "crop={w}:{h},setsar=1,"
            "zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}[v{i}]".format(
                i=i, w=REEL_W, h=REEL_H, d=frames, fps=REEL_FPS
            )
        )
    chain.append(
        "".join("[v{}]".format(i) for i in range(n))
        + "concat=n={}:v=1:a=0,format=yuv420p[vout]".format(n)
    )
    cmd += [
        "-filter_complex", ";".join(chain),
        "-map", "[vout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(REEL_FPS),
        "-metadata", "title={}".format((caption_text or "")[:200]),
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed (exit {}): {}".format(
                proc.returncode, (proc.stderr or "")[-500:]
            )
        )
    return out_path
