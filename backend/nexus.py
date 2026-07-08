import logging

import httpx

from backend.config import settings

BASE = "https://api.nexusmods.com"
logger = logging.getLogger("backend.nexus")

# one client for the process lifetime, shared across all calls
client = httpx.AsyncClient(
    base_url=BASE,
    headers={"apikey": settings.nexus_api_key, "accept": "application/json"},
    timeout=15,
)


def _check_rate_limit(resp: httpx.Response) -> None:
    remaining = resp.headers.get("x-rl-daily-remaining")
    if remaining is not None and int(remaining) < 50:
        logger.warning("Nexus daily rate limit low: %s remaining", remaining)


async def get_mod_info(game_domain: str, mod_id: int) -> dict:
    """Fetch metadata for one mod. Raises httpx.HTTPStatusError on non-2xx (e.g. 404)."""
    resp = await client.get(f"/v1/games/{game_domain}/mods/{mod_id}.json")
    _check_rate_limit(resp)
    resp.raise_for_status()
    return resp.json()


async def get_updated_mods(game_domain: str, period: str = "1w") -> list[dict]:
    """Mods with activity in the last `period` (1d/1w/1m) for a game, one call per game."""
    resp = await client.get(
        f"/v1/games/{game_domain}/mods/updated.json", params={"period": period}
    )
    _check_rate_limit(resp)
    resp.raise_for_status()
    return resp.json()


def extract_fields(info: dict) -> dict:
    """Pull just the fields we use out of a raw Nexus mod response, safely."""
    return {
        "name": str(info.get("name", "")),
        "version": str(info.get("version", "")),
        "author": str(info.get("author", "")),
        "picture_url": str(info.get("picture_url", "")),
        "nexus_updated_at": int(info.get("updated_timestamp", 0)),
    }
