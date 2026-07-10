from bot.main import parse_mod_url
from bot.scheduler import build_update_embed


def test_parse_mod_url():
    assert parse_mod_url("https://www.nexusmods.com/skyrimspecialedition/mods/266") == (
        "skyrimspecialedition",
        266,
    )
    assert parse_mod_url("nexusmods.com/fallout4/mods/12?tab=files#comments") == ("fallout4", 12)
    assert parse_mod_url("nexusmods.com/skyrimspecialedition/mods/266/") == (
        "skyrimspecialedition",
        266,
    )
    assert parse_mod_url("not a url") is None
    assert parse_mod_url("nexusmods.com/skyrimspecialedition/mods/abc") is None
    assert parse_mod_url("nexusmods.com/mods/266") is None  # no game slug


def test_build_update_embed():
    mod = {
        "name": "SkyUI",
        "version": "5.2",
        "author": "Team",
        "picture_url": "http://x/p.jpg",
        "game_domain": "sse",
        "mod_id": 12,
    }
    e = build_update_embed(mod)
    assert e.title == "SkyUI updated!"
    assert "5.2" in e.description
    assert e.url == "https://www.nexusmods.com/sse/mods/12"
    assert e.thumbnail.url == "http://x/p.jpg"

    bare = {"name": "X", "version": "1", "author": "", "picture_url": "", "game_domain": "g", "mod_id": 1}  # noqa: E501
    e = build_update_embed(bare)
    assert e.thumbnail.url is None
    assert not e.fields
