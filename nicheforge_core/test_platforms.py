"""Tests for platforms/ plug-in interface (Phase 5).

No real credentials and no real network. Fake values used here must never
leave the test process.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import platforms  # noqa: E402
from platforms import get_plugin, list_plugins, register  # noqa: E402

PASSED = 0


def check(name, fn):
    global PASSED
    try:
        fn()
    except Exception as exc:
        print("FAIL - {}: {!r}".format(name, exc))
        sys.exit(1)
    PASSED += 1
    print("ok - {}".format(name))


FAKE_TOKEN = "TEST_PLATFORM_TOKEN_9999"
DICT_CONFIG = {"facebook_pages": {"wicketverse": {"page_id": "111222333",
                                                  "token": FAKE_TOKEN}}}
LIST_CONFIG = {"facebook_pages": [{"label": "pakwire", "page_id": "444555666",
                                   "token": FAKE_TOKEN}]}


def _make_image():
    fh = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    fh.write(b"\xff\xd8\xff\xe0fakejpeg")
    fh.close()
    return fh.name


def t_registry_lists_all_six():
    slugs = set(list_plugins().keys())
    assert slugs == {"facebook", "instagram", "x", "tiktok", "youtube",
                     "website"}, slugs


def t_get_plugin_and_unknown_slug():
    assert get_plugin("facebook").name() == "Facebook"
    try:
        get_plugin("nope")
    except KeyError:
        return
    raise AssertionError("KeyError not raised for unknown slug")


def t_base_class_methods_raise():
    base = platforms.PlatformPlugin()
    for meth, args in [("name", ()), ("slug", ()), ("status", ({"x": 1})),
                       ("publish", ("d", "n")), ("schedule", ("d", "n")),
                       ("setup_notes", ())]:
        try:
            getattr(base, meth)(*args)
        except NotImplementedError:
            continue
        raise AssertionError("NotImplementedError not raised: " + meth)


def t_facebook_status_connected_dict_shape():
    plug = get_plugin("facebook")
    st = plug.status(DICT_CONFIG)
    assert st["connected"] is True, st
    assert "wicketverse" in st["detail"], st
    assert FAKE_TOKEN not in st["detail"], "token leaked in detail"


def t_facebook_status_connected_list_shape():
    plug = get_plugin("facebook")
    st = plug.status(LIST_CONFIG)
    assert st["connected"] is True, st
    assert "pakwire" in st["detail"], st
    assert FAKE_TOKEN not in st["detail"], "token leaked in detail"


def t_facebook_status_not_connected():
    plug = get_plugin("facebook")
    st = plug.status({})
    assert st == {"connected": False,
                  "detail": "no Facebook pages configured"}, st


def t_facebook_never_loads_config_from_disk():
    src = open(os.path.join(ROOT, "platforms", "facebook.py")).read()
    assert "config.json" not in src, "must never reference config.json"
    assert "load_config" not in src, "must never load the encrypted config"


def t_facebook_publish_dry_run_delegates():
    plug = get_plugin("facebook")
    plug.status(DICT_CONFIG)  # supply the config (app layer hands it over)
    db = tempfile.mktemp(suffix=".db")
    img = _make_image()
    try:
        res = plug.publish(db, "wicketverse", img, "Hello caption",
                           dry_run=True)
    finally:
        os.unlink(img)
    assert res.get("dry_run") is True, res
    assert res.get("page_id") == "111222333", res
    if os.path.exists(db):
        os.unlink(db)


def t_facebook_publish_without_config_raises():
    plug = get_plugin("facebook")
    plug._config = {}
    db = tempfile.mktemp(suffix=".db")
    try:
        plug.publish(db, "wicketverse", "/tmp/x.jpg", "cap", dry_run=True)
    except ValueError:
        return
    finally:
        if os.path.exists(db):
            os.unlink(db)
    raise AssertionError("ValueError not raised without config")


def t_stubs_status_not_connected():
    for slug in ("instagram", "x", "tiktok", "youtube", "website"):
        st = get_plugin(slug).status({"anything": True})
        assert st == {"connected": False,
                      "detail": "not connected yet"}, (slug, st)


def t_stubs_publish_schedule_raise():
    for slug in ("instagram", "x", "tiktok", "youtube", "website"):
        plug = get_plugin(slug)
        for meth in ("publish", "schedule"):
            try:
                getattr(plug, meth)("d", "n")
            except NotImplementedError as exc:
                assert "not connected yet" in str(exc), (slug, meth, exc)
                assert "setup_notes" in str(exc), (slug, meth, exc)
            else:
                raise AssertionError(
                    "NotImplementedError not raised: {}.{}".format(slug, meth))


def t_stub_setup_notes_specific():
    notes = {
        "instagram": ["instagram", "business", "instagram_content_publish"],
        "x": ["developer", "free tier"],
        "tiktok": ["Content Posting API", "approval"],
        "youtube": ["OAuth", "youtube.upload"],
        "website": ["WordPress", "webhook"],
    }
    for slug, keywords in notes.items():
        text = get_plugin(slug).setup_notes()
        assert isinstance(text, str) and len(text) > 40, slug
        for kw in keywords:
            assert kw.lower() in text.lower(), (slug, kw)


def t_stub_signatures_match_base():
    import inspect
    base_params = list(inspect.signature(
        platforms.PlatformPlugin.publish).parameters)[1:]  # drop self
    for slug in ("instagram", "x", "tiktok", "youtube", "website", "facebook"):
        sig = inspect.signature(get_plugin(slug).publish)
        assert list(sig.parameters) == base_params, (slug, sig)


def t_register_duplicate_slug_raises():
    class Dup(platforms.PlatformPlugin):
        def slug(self):
            return "facebook"

        def name(self):
            return "Dup"

    try:
        register(Dup)
    except ValueError:
        return
    raise AssertionError("ValueError not raised for duplicate slug")


if __name__ == "__main__":
    check("registry lists all six platforms", t_registry_lists_all_six)
    check("get_plugin resolves, unknown slug raises KeyError",
          t_get_plugin_and_unknown_slug)
    check("base class methods raise NotImplementedError",
          t_base_class_methods_raise)
    check("facebook status connected (dict config shape)",
          t_facebook_status_connected_dict_shape)
    check("facebook status connected (list config shape)",
          t_facebook_status_connected_list_shape)
    check("facebook status not connected on empty config",
          t_facebook_status_not_connected)
    check("facebook module never loads config from disk",
          t_facebook_never_loads_config_from_disk)
    check("facebook publish dry_run delegates to FBPublisher",
          t_facebook_publish_dry_run_delegates)
    check("facebook publish without config raises ValueError",
          t_facebook_publish_without_config_raises)
    check("stub statuses report not connected", t_stubs_status_not_connected)
    check("stub publish/schedule raise NotImplementedError",
          t_stubs_publish_schedule_raise)
    check("stub setup_notes are platform-specific",
          t_stub_setup_notes_specific)
    check("plug-in signatures match base", t_stub_signatures_match_base)
    check("duplicate slug registration raises",
          t_register_duplicate_slug_raises)
    print("ALL {} CHECKS PASSED".format(PASSED))
