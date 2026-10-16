"""NicheForge Facebook publisher (Phase 2).

Posts photos to Facebook Pages via the Graph API. All FB credentials come
ONLY from the user's encrypted nicheforge config.json (config["facebook_pages"]),
collected via setup_keys.py. Nothing is read from any other file or location.

Token hygiene: page tokens are NEVER logged, stored, or shown. The fb_posts
table only stores the page_id; errors are scrubbed so at most the last 4
characters of a token may appear.
"""
import os
import sqlite3
from datetime import datetime, timezone

from db import _connect, init_publish_tables, utc_now

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = "https://graph.facebook.com/{}".format(GRAPH_API_VERSION)


def mask_token(token):
    """Return a masked form of a token: only the last 4 chars are visible."""
    s = str(token or "")
    if len(s) <= 4:
        return "****"
    return "***" + s[-4:]


def scrub_token(text, token):
    """Replace every occurrence of token in text with its masked form."""
    s = str(text or "")
    t = str(token or "")
    if t and t in s:
        s = s.replace(t, mask_token(t))
    return s


class FBPublisher:
    """Facebook Page photo publisher.

    config: dict from the decrypted config.json (must contain
            config["facebook_pages"] = [{"label", "page_id", "token"}, ...]).
    db_path: SQLite file; every attempt is logged to fb_posts.
    dry_run: True (default) = validate only, no network calls.
    """

    def __init__(self, config, db_path, dry_run=True):
        self.config = config or {}
        self.db_path = db_path
        self.dry_run = dry_run
        init_publish_tables(db_path)

    # ------------------------------------------------------------- pages

    def get_page(self, label):
        """Resolve a page label -> (page_id, token). Unknown label -> ValueError."""
        for page in self.config.get("facebook_pages", []):
            if page.get("label") == label:
                return page.get("page_id"), page.get("token")
        known = [p.get("label") for p in self.config.get("facebook_pages", [])]
        raise ValueError(
            "Unknown Facebook page label {!r}. Configured labels: {}".format(
                label, ", ".join(known) or "none"
            )
        )

    # --------------------------------------------------------------- log

    def _log(self, niche, page_id, image_path, caption, scheduled_utc,
             status, post_id=None, error=""):
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO fb_posts (ts, niche, page_id, post_id, image_path,"
                " caption_head, scheduled_utc, status, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    utc_now(),
                    niche or "",
                    page_id or "",
                    post_id,
                    image_path or "",
                    (caption or "")[:120],
                    scheduled_utc,
                    status,
                    error or "",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ----------------------------------------------------------- publish

    def publish_photo(self, label, image_path, caption, scheduled_utc=None):
        """Publish a photo post to the page identified by label.

        niche is derived from the label. scheduled_utc: 'YYYY-MM-DDTHH:MM:SS'
        UTC ISO; when given the post is scheduled (published=false).

        Returns a dict; on failure ok=False with the error scrubbed.
        """
        page_id, token = self.get_page(label)

        if not image_path or not os.path.isfile(image_path):
            err = "Image not found: {}".format(image_path)
            self._log(label, page_id, image_path, caption, scheduled_utc,
                      "failed", error=scrub_token(err, token))
            return {"ok": False, "error": err}

        if self.dry_run:
            self._log(label, page_id, image_path, caption, scheduled_utc,
                      "dry_run")
            return {
                "dry_run": True,
                "page_id": page_id,
                "image": image_path,
                "caption_len": len(caption or ""),
                "scheduled_utc": scheduled_utc,
            }

        # Live publish via Graph API.
        try:
            import requests
        except ImportError:
            err = "requests library is not installed; cannot publish"
            self._log(label, page_id, image_path, caption, scheduled_utc,
                      "failed", error=err)
            return {"ok": False, "error": err}

        data = {"caption": caption or "", "access_token": token}
        if scheduled_utc:
            dt = datetime.fromisoformat(scheduled_utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            data["scheduled_publish_time"] = int(dt.timestamp())
            data["published"] = "false"

        try:
            with open(image_path, "rb") as fh:
                files = {"source": (os.path.basename(image_path), fh)}
                resp = requests.post(
                    "{}/{}/photos".format(GRAPH_BASE, page_id),
                    data=data,
                    files=files,
                    timeout=60,
                )
            payload = resp.json() if resp.content else {}
        except Exception as exc:  # network/JSON failures, no token in message
            err = scrub_token("publish failed: {}".format(exc), token)
            self._log(label, page_id, image_path, caption, scheduled_utc,
                      "failed", error=err)
            return {"ok": False, "error": err}

        fb_error = (payload or {}).get("error", {}).get("message", "")
        post_id = (payload or {}).get("post_id") or (payload or {}).get("id")
        if resp.status_code == 200 and post_id:
            self._log(label, page_id, image_path, caption, scheduled_utc,
                      "published", post_id=post_id)
            return {"ok": True, "post_id": post_id}

        err = scrub_token(
            "Graph API error ({}): {}".format(resp.status_code, fb_error or resp.text[:200]),
            token,
        )
        self._log(label, page_id, image_path, caption, scheduled_utc,
                  "failed", error=err)
        return {"ok": False, "error": err}
