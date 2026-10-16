"""YouTube platform plug-in — honest stub (not connected yet)."""
from platforms import PlatformPlugin, register


class YouTubePlugin(PlatformPlugin):
    def name(self):
        return "YouTube"

    def slug(self):
        return "youtube"

    def status(self, config):
        return {"connected": False, "detail": "not connected yet"}

    def publish(self, db_path, niche, image_path=None, caption="",
                scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "YouTube publishing is not connected yet — see setup_notes()."
        )

    def schedule(self, db_path, niche, image_path=None, caption="",
                 scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "YouTube scheduling is not connected yet — see setup_notes()."
        )

    def setup_notes(self):
        return (
            "To connect YouTube: (1) create an OAuth client in Google Cloud "
            "Console for the channel's Google account; (2) authorise the "
            "youtube.upload scope and store the refresh token; (3) save the "
            "client id, client secret and refresh token in the encrypted "
            "config.json via setup_keys.py."
        )


register(YouTubePlugin)
