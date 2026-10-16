"""NicheForge platform plug-ins (Phase 5).

A platform plug-in wraps one publishing destination (Facebook, Instagram, X,
TikTok, YouTube, a website) behind a common interface so the app layer can
list destinations, check connection status and publish without knowing the
details of each API.

Plug-in contract (see PlatformPlugin):
    name()           human-readable name, e.g. "Facebook"
    slug()           short id, e.g. "facebook"
    status(config)   -> {"connected": bool, "detail": str}; config is an
                       already-loaded config dict. A plug-in must NEVER load
                       config.json from disk or touch raw token values here.
    publish(...)     -> dict result of a publish attempt
    schedule(...)    -> dict result of a scheduled-post attempt
    setup_notes()    -> str with the steps the user must take to connect

Registry: register() / get_plugin() / list_plugins().
"""
_REGISTRY = {}


class PlatformPlugin:
    """Base class for platform plug-ins."""

    def name(self):
        raise NotImplementedError("subclass must implement name()")

    def slug(self):
        raise NotImplementedError("subclass must implement slug()")

    def status(self, config):
        """Return {"connected": bool, "detail": str} for an already-loaded config dict."""
        raise NotImplementedError("subclass must implement status()")

    def publish(self, db_path, niche, image_path=None, caption="",
                scheduled_for=None, dry_run=True):
        """Publish now (or immediately). Returns a result dict."""
        raise NotImplementedError("subclass must implement publish()")

    def schedule(self, db_path, niche, image_path=None, caption="",
                 scheduled_for=None, dry_run=True):
        """Schedule a post for a later slot. Returns a result dict."""
        raise NotImplementedError("subclass must implement schedule()")

    def setup_notes(self):
        """Return the user-facing steps needed to connect this platform."""
        raise NotImplementedError("subclass must implement setup_notes()")


def register(plugin_cls):
    """Register a PlatformPlugin subclass under its slug."""
    plugin = plugin_cls()
    slug = plugin.slug()
    if slug in _REGISTRY:
        raise ValueError("duplicate platform slug: {!r}".format(slug))
    _REGISTRY[slug] = plugin
    return plugin_cls


def get_plugin(slug):
    """Return the registered plug-in for slug, or raise KeyError."""
    try:
        return _REGISTRY[slug]
    except KeyError:
        raise KeyError(
            "Unknown platform {!r}. Registered: {}".format(
                slug, ", ".join(sorted(_REGISTRY)) or "none"
            )
        )


def list_plugins():
    """Return {slug: plug-in} for every registered platform."""
    return dict(_REGISTRY)


# Built-in plug-ins register themselves on import. This sits at the bottom so
# the submodules can `from platforms import register, PlatformPlugin`.
from . import facebook, instagram, x, tiktok, youtube, website  # noqa: F401, E402
