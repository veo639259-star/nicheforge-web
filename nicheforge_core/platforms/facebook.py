"""Facebook platform plug-in — the WORKING reference implementation.

Wraps the existing Phase-2 publish.FBPublisher. This module NEVER loads
the encrypted config file from disk: the app layer hands it an already-loaded config dict
via configure() (or status()), and publish()/schedule() pass that config
straight through to FBPublisher, which owns all token hygiene (masking in
logs, scrubbing in errors). No token values are read or returned here.

Expected config shape (already-loaded dict; shown with placeholder values —
no real credentials here):
    {"facebook_pages": {"<niche>": {"page_id": "<page id>", "token": "<page token>"}}}
The list shape used by publish.py / setup_keys.py is also accepted for
compatibility:
    {"facebook_pages": [{"label": "<niche>", "page_id": "<page id>",
                         "token": "<page token>"}]}
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platforms import PlatformPlugin, register  # noqa: E402
from publish import FBPublisher  # noqa: E402


def _normalise_pages(config):
    """Return configured pages as a list of dicts, accepting both shapes.

    Accepts:
      {"facebook_pages": {"niche": {"page_id": ..., "token": ...}}}
      {"facebook_pages": [{"label": ..., "page_id": ..., "token": ...}]}
    """
    raw = (config or {}).get("facebook_pages") or []
    if isinstance(raw, dict):
        return [
            {"label": label, "page_id": info.get("page_id"),
             "token": info.get("token")}
            for label, info in raw.items()
            if isinstance(info, dict)
        ]
    return [p for p in raw if isinstance(p, dict)]


class FacebookPlugin(PlatformPlugin):
    """Working Facebook plug-in backed by publish.FBPublisher."""

    def __init__(self):
        self._config = {}

    def name(self):
        return "Facebook"

    def slug(self):
        return "facebook"

    def configure(self, config):
        """Store an already-loaded config dict for later publish calls."""
        self._config = config or {}
        return self

    def status(self, config):
        """Report whether any Facebook pages are configured.

        Only the presence of page_id/token entries is checked; no token
        values are read into output or logs. Also remembers the config for
        subsequent publish()/schedule() calls (same as configure()).
        """
        self.configure(config)
        pages = _normalise_pages(config)
        ready = [
            str(p.get("label") or "?")
            for p in pages
            if p.get("page_id") and bool(p.get("token"))
        ]
        if ready:
            return {
                "connected": True,
                "detail": "{} page(s) configured: {}".format(
                    len(ready), ", ".join(ready)
                ),
            }
        return {"connected": False, "detail": "no Facebook pages configured"}

    def _publisher(self, db_path, dry_run):
        if not self._config.get("facebook_pages"):
            raise ValueError(
                "Facebook plug-in has no config: call status(config) or "
                "configure(config) with the loaded config dict first."
            )
        return FBPublisher(
            {"facebook_pages": _normalise_pages(self._config)},
            db_path,
            dry_run=dry_run,
        )

    def publish(self, db_path, niche, image_path=None, caption="",
                scheduled_for=None, dry_run=True):
        """Publish a photo via FBPublisher. dry_run defaults to True."""
        return self._publisher(db_path, dry_run).publish_photo(
            niche, image_path, caption, scheduled_utc=None
        )

    def schedule(self, db_path, niche, image_path=None, caption="",
                 scheduled_for=None, dry_run=True):
        """Schedule a photo; scheduled_for is a UTC ISO string."""
        return self._publisher(db_path, dry_run).publish_photo(
            niche, image_path, caption, scheduled_utc=scheduled_for
        )

    def setup_notes(self):
        return (
            "Facebook Pages are already wired: run setup_keys.py and choose "
            "the Facebook Pages option to store each page's page_id and token "
            "in the encrypted config file. Long-lived page tokens never "
            "expire once minted. No further setup needed."
        )


register(FacebookPlugin)
