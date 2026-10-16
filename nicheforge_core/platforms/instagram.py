"""Instagram platform plug-in — honest stub (not connected yet)."""
from platforms import PlatformPlugin, register


class InstagramPlugin(PlatformPlugin):
    def name(self):
        return "Instagram"

    def slug(self):
        return "instagram"

    def status(self, config):
        return {"connected": False, "detail": "not connected yet"}

    def publish(self, db_path, niche, image_path=None, caption="",
                scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "Instagram publishing is not connected yet — see setup_notes()."
        )

    def schedule(self, db_path, niche, image_path=None, caption="",
                 scheduled_for=None, dry_run=True):
        raise NotImplementedError(
            "Instagram scheduling is not connected yet — see setup_notes()."
        )

    def setup_notes(self):
        return (
            "To connect Instagram: (1) link an Instagram business or creator "
            "account to the matching Facebook Page in Page settings; "
            "(2) in the Meta app 'The Bilalify', request the "
            "instagram_content_publish permission and get it approved; "
            "(3) mint a long-lived token for the linked account and store it "
            "in the encrypted config.json via setup_keys.py."
        )


register(InstagramPlugin)
