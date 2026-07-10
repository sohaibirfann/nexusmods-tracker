from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.main import (
    game_autocomplete,
    mod_autocomplete,
    parse_mod_url,
    parse_track_value,
    tracked_autocomplete,
)
from bot.scheduler import build_update_embed


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
