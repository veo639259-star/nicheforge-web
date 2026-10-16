"""X (Twitter) platform plug-in — honest stub (not connected yet)."""
from platforms import PlatformPlugin, register


class XPlugin(PlatformPlugin):
    def name(self):
        return "X"

    def slug(self):
        return "x"

    def status(self, config):
        return {"connected": False, "detail": "not connected yet"}

    def publish(self, db_path, niche, image_path=None, caption="",
                scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "X publishing is not connected yet — see setup_notes()."
        )

    def schedule(self, db_path, niche, image_path=None, caption="",
                 scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "X scheduling is not connected yet — see setup_notes()."
        )

    def setup_notes(self):
        return (
            "To connect X: (1) create a project in the X developer portal "
            "(developer.x.com) and generate an API key + API secret plus "
            "user access tokens; (2) note the free tier has strict monthly "
            "post and read limits — check current limits before enabling; "
            "(3) store the keys in the encrypted config.json via "
            "setup_keys.py."
        )


register(XPlugin)
