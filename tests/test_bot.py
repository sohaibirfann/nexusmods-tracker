from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from bot.main import (
    AUTOCOMPLETE_TIMEOUT,
    _find_tracked,
    _has_channel,
    _resolve_mod,
    game_autocomplete,
    mod_autocomplete,
    parse_mod_url,
    parse_track_value,
    tracked_autocomplete,
)
from bot.scheduler import (
    _ping_kwargs,
    build_help_embed,
    build_list_embed,
    build_status_embed,
    build_track_embed,
    build_update_embed,
    paginate,
)


def _fake_response(payload, status=200):
    return type("R", (), {"status_code": status, "json": lambda self: payload})()


def _interaction(**namespace):
    return SimpleNamespace(namespace=SimpleNamespace(**namespace), guild_id=1)


def test_parse_track_value():
    assert parse_track_value("skyrimspecialedition:266") == ("skyrimspecialedition", 266)
    assert parse_track_value(" fallout4:12 ") == ("fallout4", 12)
    assert parse_track_value("SkyUI") is None  # free-typed name
    assert parse_track_value("skyrim:") is None
    assert parse_track_value("skyrim:12:3") is None


async def test_mod_autocomplete_guard_and_scoping():
    # under 3 chars: no backend call at all
    with patch("bot.main.api.get", new=AsyncMock()) as g:
        assert await mod_autocomplete(_interaction(game="skyrim"), "sk") == []
        g.assert_not_called()

    # 3+ chars: scopes to the picked game and maps to "game:modid" Choices
    resp = _fake_response([{"mod_id": 3863, "name": "SkyUI", "game_domain": "skyrim"}])
    with patch("bot.main.api.get", new=AsyncMock(return_value=resp)) as g:
        choices = await mod_autocomplete(_interaction(game="skyrim"), "skyui")
    g.assert_awaited_once_with(
        "/mods/search", params={"q": "skyui", "game": "skyrim"}, timeout=AUTOCOMPLETE_TIMEOUT
    )
    assert choices[0].value == "skyrim:3863"
    assert parse_track_value(choices[0].value) == ("skyrim", 3863)


async def test_tracked_autocomplete_filters_guild_mods():
    tracked = [
        {"mod_id": 266, "name": "USSEP", "game_domain": "skyrimspecialedition"},
        {"mod_id": 3863, "name": "SkyUI", "game_domain": "skyrim"},
    ]
    resp = _fake_response(tracked)
    with patch("bot.main.api.get", new=AsyncMock(return_value=resp)):
        choices = await tracked_autocomplete(_interaction(), "sky")
    assert [c.value for c in choices] == ["skyrim:3863"]
    assert parse_track_value(choices[0].value) == ("skyrim", 3863)


def test_find_tracked():
    tracked = [
        {"name": "USSEP", "game_domain": "skyrimspecialedition", "mod_id": 266},
        {"name": "SkyUI", "game_domain": "skyrim", "mod_id": 3863},
    ]
    # picked value matches on game + id
    assert _find_tracked(tracked, "skyrim:3863")["name"] == "SkyUI"
    # free text matches on name
    assert _find_tracked(tracked, "ussep")["name"] == "USSEP"
    # no match either way
    assert _find_tracked(tracked, "skyrim:9999") is None
    assert _find_tracked(tracked, "nope") is None


async def test_has_channel():
    def r(payload, status=200):
        return AsyncMock(return_value=_fake_response(payload, status))

    with patch("bot.main.api.get", new=r({"channel_id": 42})):
        assert await _has_channel(1) is True
    with patch("bot.main.api.get", new=r({"channel_id": None})):
        assert await _has_channel(1) is False
    with patch("bot.main.api.get", new=r({}, 500)):
        assert await _has_channel(1) is True
    with patch("bot.main.api.get", new=AsyncMock(side_effect=httpx.ConnectError("down"))):
        assert await _has_channel(1) is True


async def test_resolve_mod():
    # a picked suggestion parses directly, no search call
    with patch("bot.main.api.get", new=AsyncMock()) as g:
        assert await _resolve_mod("skyrim", "skyrim:3863") == ("skyrim", 3863)
        g.assert_not_called()

    # free text searches within the game and takes the top hit
    resp = _fake_response([{"mod_id": 3863, "name": "SkyUI", "game_domain": "skyrim"}])
    with patch("bot.main.api.get", new=AsyncMock(return_value=resp)) as g:
        assert await _resolve_mod("skyrim", "skyui") == ("skyrim", 3863)
    g.assert_awaited_once_with("/mods/search", params={"q": "skyui", "game": "skyrim"})

    # no results -> None
    with patch("bot.main.api.get", new=AsyncMock(return_value=_fake_response([]))):
        assert await _resolve_mod("skyrim", "nope") is None


async def test_game_autocomplete():
    with patch("bot.main.api.get", new=AsyncMock()) as g:
        assert await game_autocomplete(_interaction(), "s") == []  # under 2 chars, no call
        g.assert_not_called()

    resp = _fake_response([{"name": "Skyrim Special Edition", "domain": "skyrimspecialedition"}])
    with patch("bot.main.api.get", new=AsyncMock(return_value=resp)):
        choices = await game_autocomplete(_interaction(), "skyrim")
    assert choices[0].name == "Skyrim Special Edition"
    assert choices[0].value == "skyrimspecialedition"


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


def test_build_track_embed():
    mod = {
        "name": "SkyUI",
        "version": "5.2",
        "author": "Team",
        "summary": "Elegant UI mod",
        "picture_url": "http://x/p.jpg",
        "game_domain": "skyrimspecialedition",
        "game_name": "Skyrim Special Edition",
        "game_image_url": "http://x/tile.jpg",
        "endorsements": 471129,
        "downloads": 26773368,
        "nexus_updated_at": 1700000000,
        "mod_id": 12604,
    }
    e = build_track_embed(mod)
    assert e.title == "SkyUI"
    assert e.author.name == "Skyrim Special Edition"  # game name up top
    assert e.author.icon_url == "http://x/tile.jpg"  # game tile shrunk to author icon
    assert e.thumbnail.url == "http://x/p.jpg"  # mod image, top-right
    assert e.image.url is None  # big bottom image dropped
    assert "Elegant UI mod" in e.description
    assert e.url == "https://www.nexusmods.com/skyrimspecialedition/mods/12604"
    fields = {f.name: f.value for f in e.fields}
    assert fields["Version"] == "v5.2"
    assert fields["Author"] == "Team"
    assert fields["Endorsements"] == "471.1K"
    assert fields["Downloads"] == "26.8M"
    assert fields["Updated"] == "<t:1700000000:R>"
    assert "Links" not in fields  # replaced by link buttons


def test_ping_kwargs():
    assert _ping_kwargs(None) == {}
    assert _ping_kwargs(0) == {}  # no role -> no ping, no mention scoping
    k = _ping_kwargs(555)
    assert k["content"] == "<@&555>"
    am = k["allowed_mentions"]
    assert am.everyone is False and am.users is False
    assert [r.id for r in am.roles] == [555]  # only this role may be pinged


def test_build_status_embed():
    e = build_status_embed("My Server", "http://x/icon.png", 12345, 999, 7, 180)
    assert e.author.name == "My Server"
    assert e.thumbnail.url == "http://x/icon.png"
    fields = {f.name: f.value for f in e.fields}
    assert fields["Update channel"] == "<#12345>"
    assert fields["Ping role"] == "<@&999>"
    assert fields["Tracked mods"] == "7"
    assert "180" in fields["Check interval"]
    # nothing set, no icon -> /setchannel hint, "Not set" ping, no thumbnail
    bare = build_status_embed("S", None, None, None, 0, 60)
    assert bare.thumbnail.url is None
    bare_fields = {f.name: f.value for f in bare.fields}
    assert "setchannel" in bare_fields["Update channel"]
    assert bare_fields["Ping role"] == "Not set"


def test_build_help_embed():
    e = build_help_embed()
    assert len(e.fields) == 3  # Setup / Tracking / Browse
    body = "\n".join(f.value for f in e.fields)
    for cmd in ("/setchannel", "/track", "/trackurl", "/untrack", "/list", "/info", "/check"):
        assert cmd in body


def test_paginate():
    items = list(range(25))
    assert paginate(items, 0, 10) == (items[0:10], 0, 3)
    assert paginate(items, 2, 10) == (items[20:25], 2, 3)
    assert paginate(items, 99, 10) == (items[20:25], 2, 3)  # clamped up
    assert paginate(items, -5, 10) == (items[0:10], 0, 3)  # clamped down
    assert paginate([], 0, 10) == ([], 0, 1)


def test_build_list_embed():
    assert "Not tracking" in build_list_embed([]).description

    one = [{
        "name": "SkyUI", "version": "5.2", "game_domain": "skyrim", "mod_id": 3863,
        "nexus_updated_at": 1700000000,
    }]
    e = build_list_embed(one)
    assert "[SkyUI](https://www.nexusmods.com/skyrim/mods/3863) — v5.2" in e.description
    assert "updated <t:1700000000:R>" in e.description  # relative time per line
    assert e.footer.text == "1 mod tracked"  # singular, no page prefix

    many = [{"name": f"M{i}", "version": "1", "game_domain": "g", "mod_id": i} for i in range(15)]
    p0 = build_list_embed(many, 0)
    assert p0.footer.text == "Page 1/2 · 15 mods tracked"
    assert "M0" in p0.description and "M10" not in p0.description
    assert "M10" in build_list_embed(many, 1).description


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
    assert e.title == "SkyUI"
    assert "updated to v5.2" in e.description.lower()  # version in the status line
    assert e.url == "https://www.nexusmods.com/sse/mods/12"
    assert e.thumbnail.url == "http://x/p.jpg"  # mod image as thumbnail
    assert e.image.url is None  # no big bottom image
    assert "Author" not in {f.name for f in e.fields}  # author dropped on update posts

    # missing optional fields shouldn't crash; no version -> generic status, no fields
    bare = {"name": "X", "version": "", "author": "", "picture_url": "", "game_domain": "g", "mod_id": 1}  # noqa: E501
    e = build_update_embed(bare)
    assert "new version available" in e.description.lower()
    assert e.image.url is None
    assert e.fields == []


def test_build_update_embed_diff():
    mod = {
        "name": "SkyUI", "version": "5.3", "game_domain": "sse", "mod_id": 12,
        "endorsements": 471629, "downloads": 26858368,
    }
    e = build_update_embed(mod, previous_version="5.2", endorsement_delta=500, download_delta=85000)
    assert "v5.2 → v5.3" in e.description  # version diff in the status line
    fields = {f.name: f.value for f in e.fields}
    assert "(+500)" in fields["Endorsements"]
    assert "(+85K)" in fields["Downloads"]


def test_build_update_embed_changelog():
    mod = {"name": "SkyUI", "version": "5.3", "game_domain": "sse", "mod_id": 12}
    e = build_update_embed(mod, changelog=["Fixed a crash", "Added FOMOD installer"])
    whats_new = {f.name: f.value for f in e.fields}["What's new"]
    assert "• Fixed a crash" in whats_new
    assert "• Added FOMOD installer" in whats_new

    # more than 5 lines -> truncated with a full-changelog link
    e = build_update_embed(mod, changelog=[f"change {i}" for i in range(8)])
    whats_new = {f.name: f.value for f in e.fields}["What's new"]
    assert "…full changelog" in whats_new
    assert "change 5" not in whats_new  # only first 5 shown
