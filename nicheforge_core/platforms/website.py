"""Website platform plug-in — honest stub (not connected yet)."""
from platforms import PlatformPlugin, register


class WebsitePlugin(PlatformPlugin):
    def name(self):
        return "Website"

    def slug(self):
        return "website"

    def status(self, config):
        return {"connected": False, "detail": "not connected yet"}

    def publish(self, db_path, niche, image_path=None, caption="",
                scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "Website publishing is not connected yet — see setup_notes()."
        )

    def schedule(self, db_path, niche, image_path=None, caption="",
                 scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "Website scheduling is not connected yet — see setup_notes()."
        )

    def setup_notes(self):
        return (
            "To connect a website: either (a) provide WordPress REST API "
            "credentials (site URL, username and an application password) so "
            "posts can be created via the WP REST API, or (b) provide a "
            "webhook URL that accepts the image and caption payload. Store "
            "whichever you choose in the encrypted config.json via "
            "setup_keys.py."
        )


register(WebsitePlugin)
