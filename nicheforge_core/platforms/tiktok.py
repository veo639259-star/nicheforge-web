"""TikTok platform plug-in — honest stub (not connected yet)."""
from platforms import PlatformPlugin, register


class TikTokPlugin(PlatformPlugin):
    def name(self):
        return "TikTok"

    def slug(self):
        return "tiktok"

    def status(self, config):
        return {"connected": False, "detail": "not connected yet"}

    def publish(self, db_path, niche, image_path=None, caption="",
                scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "TikTok publishing is not connected yet — see setup_notes()."
        )

    def schedule(self, db_path, niche, image_path=None, caption="",
                 scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "TikTok scheduling is not connected yet — see setup_notes()."
        )

    def setup_notes(self):
        return (
            "To connect TikTok: (1) register an app on the TikTok Developers "
            "portal and apply for Content Posting API access — approval is "
            "manual and can take days; (2) complete the OAuth flow to obtain "
            "a long-lived access token for the account; (3) store the token "
            "in the encrypted config.json via setup_keys.py."
        )


register(TikTokPlugin)
