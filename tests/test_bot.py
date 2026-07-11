from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.main import (
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
    build_help_embed,
    build_list_embed,
    build_track_embed,
    build_update_embed,
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
    g.assert_awaited_once_with("/mods/search", params={"q": "skyui", "game": "skyrim"})
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
        assert await _has_channel(1) is False


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
        "picture_url": "http://x/p.jpg",
        "game_domain": "skyrimspecialedition",
        "mod_id": 12604,
    }
    e = build_track_embed(mod)
    assert e.title == "SkyUI"
    assert e.url == "https://www.nexusmods.com/skyrimspecialedition/mods/12604"
    assert e.image.url == "http://x/p.jpg"  # large image, not a thumbnail
    fields = {f.name: f.value for f in e.fields}
    assert fields["Version"] == "v5.2"
    assert fields["Author"] == "Team"
    assert "?tab=logs" in fields["Links"] and "?tab=files" in fields["Links"]


def test_build_help_embed():
    e = build_help_embed([("track", "Track a mod"), ("check", "Check now"), ("help", "")])
    names = [f.name for f in e.fields]
    assert names == ["/check", "/help", "/track"]  # sorted
    assert e.fields[names.index("/help")].value == "—"  # empty desc placeholder


def test_build_list_embed():
    assert "Not tracking" in build_list_embed([]).description
    mods = [{"name": "SkyUI", "version": "5.2", "game_domain": "skyrim", "mod_id": 3863}]
    e = build_list_embed(mods)
    assert "[SkyUI](https://www.nexusmods.com/skyrim/mods/3863)" in e.description
    assert "v5.2" in e.description


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
    assert "update" in e.description.lower()
    assert e.url == "https://www.nexusmods.com/sse/mods/12"
    assert e.image.url == "http://x/p.jpg"

    # missing optional fields shouldn't crash; no image, no Author field
    bare = {"name": "X", "version": "", "author": "", "picture_url": "", "game_domain": "g", "mod_id": 1}  # noqa: E501
    e = build_update_embed(bare)
    assert e.image.url is None
    assert {f.name for f in e.fields} == {"Links"}
