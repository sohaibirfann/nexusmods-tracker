from unittest.mock import patch

from conftest import HEADERS

FAKE = {
    "name": "SkyUI",
    "version": "5.2",
    "author": "Team",
    "picture_url": "http://x/p.jpg",
    "updated_timestamp": 2000000000,
}


async def _track(client, guild, mod_id=266, game="sse"):
    with patch("backend.main.get_mod_info", return_value=FAKE):
        return await client.post(
            f"/guilds/{guild}/mods", json={"game_domain": game, "mod_id": mod_id}, headers=HEADERS
        )


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_auth_required(client):
    r = await client.get("/guilds/1/mods")
    assert r.status_code == 401


async def test_search_short_query_skips_nexus(client):
    with patch("backend.main.search_mods") as m:
        r = await client.get("/mods/search", params={"q": "sk"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []
    m.assert_not_called()


async def test_search_maps_results(client):
    hits = [{"mod_id": 3863, "name": "SkyUI", "game_domain": "skyrim"}]
    with patch("backend.main.search_mods", return_value=hits) as m:
        r = await client.get("/mods/search", params={"q": "skyui"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == hits
    m.assert_awaited_once()


async def test_search_scopes_by_game(client):
    with patch("backend.main.search_mods", return_value=[]) as m:
        await client.get(
            "/mods/search", params={"q": "skyui", "game": "sse"}, headers=HEADERS
        )
    m.assert_awaited_once_with("skyui", game="sse")


async def test_games_empty_query_skips_fetch(client):
    with patch("backend.main.get_games") as m:
        r = await client.get("/games", params={"q": ""}, headers=HEADERS)
    assert r.json() == []
    m.assert_not_called()


async def test_games_filters_cached_list(client):
    games = [
        {"name": "Skyrim", "domain": "skyrim"},
        {"name": "Skyrim Special Edition", "domain": "skyrimspecialedition"},
        {"name": "Fallout 4", "domain": "fallout4"},
    ]
    with patch("backend.main.get_games", return_value=games):
        r = await client.get("/games", params={"q": "skyrim"}, headers=HEADERS)
    assert [g["domain"] for g in r.json()] == ["skyrim", "skyrimspecialedition"]


async def test_track_then_list(client):
    r = await _track(client, 1)
    assert r.status_code == 201
    assert r.json()["name"] == "SkyUI"
    r = await client.get("/guilds/1/mods", headers=HEADERS)
    assert len(r.json()) == 1


async def test_duplicate_returns_409(client):
    await _track(client, 1)
    r = await _track(client, 1)
    assert r.status_code == 409


async def test_untrack(client):
    await _track(client, 1)
    r = await client.delete(
        "/guilds/1/mods", params={"game_domain": "sse", "mod_id": 266}, headers=HEADERS
    )
    assert r.status_code == 204
    r = await client.delete(
        "/guilds/1/mods", params={"game_domain": "sse", "mod_id": 266}, headers=HEADERS
    )
    assert r.status_code == 404


async def test_per_guild_isolation_and_shared_prune(client):
    await _track(client, 1)
    await _track(client, 2)
    # guild 2 sees only its own list
    assert len((await client.get("/guilds/2/mods", headers=HEADERS)).json()) == 1
    # guild 1 untracks; shared mod row survives for guild 2
    await client.delete(
        "/guilds/1/mods", params={"game_domain": "sse", "mod_id": 266}, headers=HEADERS
    )
    assert len((await client.get("/guilds/1/mods", headers=HEADERS)).json()) == 0
    assert len((await client.get("/guilds/2/mods", headers=HEADERS)).json()) == 1
    # guild 2 leaves; mod row is now orphaned and pruned
    await client.delete("/guilds/2", headers=HEADERS)
    with patch("backend.main.get_updated_mods", return_value=[]):
        r = await client.post("/check", headers=HEADERS)
    assert r.json() == []


async def test_check_detects_change(client):
    await client.put("/guilds/1/channel", json={"channel_id": 999}, headers=HEADERS)
    await _track(client, 1)
    activity = [{"mod_id": 266, "latest_mod_activity": 2100000000}]
    newer = {**FAKE, "version": "5.3", "updated_timestamp": 2100000000}
    with (
        patch("backend.main.get_updated_mods", return_value=activity),
        patch("backend.main.get_mod_info", return_value=newer),
    ):
        r = await client.post("/check", headers=HEADERS)
    changed = r.json()
    assert len(changed) == 1
    assert changed[0]["mod"]["version"] == "5.3"
    assert changed[0]["notify"] == [{"guild_id": 1, "channel_id": 999}]
    # nothing new on a second pass
    with patch("backend.main.get_updated_mods", return_value=activity):
        r = await client.post("/check", headers=HEADERS)
    assert r.json() == []
