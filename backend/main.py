import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from sqlalchemy import delete, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import Guild, Mod, Subscription
from backend.nexus import client as nexus_client
from backend.nexus import extract_fields, get_games, get_mod_info, get_updated_mods, search_mods
from backend.schemas import (
    ChangedModOut,
    GameOut,
    GuildOut,
    ModInfoOut,
    ModOut,
    NotifyTarget,
    SearchResultOut,
    SetChannelRequest,
    TrackModRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backend")

# mods updated within this window will show up in the bulk check; must stay
# comfortably longer than POLL_INTERVAL_MINUTES so no update slips between polls
CHECK_PERIOD = "1w"


def require_api_key(x_api_key: str | None = Header(None)) -> None:
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.internal_api_key):
        raise HTTPException(401, "invalid api key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await nexus_client.aclose()


app = FastAPI(title="Nexus Mod Tracker", lifespan=lifespan)
router = APIRouter(dependencies=[Depends(require_api_key)])


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _get_or_create_guild(db: AsyncSession, guild_id: int) -> Guild:
    guild = await db.get(Guild, guild_id)
    if guild is None:
        guild = Guild(guild_id=guild_id)
        db.add(guild)
        await db.flush()
    return guild


async def _prune_orphan_mods(db: AsyncSession) -> None:
    await db.execute(delete(Mod).where(~exists().where(Subscription.mod_pk == Mod.id)))


@router.get("/guilds/{guild_id}", response_model=GuildOut)
async def get_guild(guild_id: int, db: AsyncSession = Depends(get_db)):
    guild = await db.get(Guild, guild_id)
    return GuildOut(guild_id=guild_id, channel_id=guild.channel_id if guild else None)


@router.put("/guilds/{guild_id}/channel", status_code=204)
async def set_channel(
    guild_id: int, body: SetChannelRequest, db: AsyncSession = Depends(get_db)
):
    guild = await _get_or_create_guild(db, guild_id)
    guild.channel_id = body.channel_id
    await db.commit()


@router.get("/guilds/{guild_id}/mods", response_model=list[ModOut])
async def list_guild_mods(guild_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Mod)
        .join(Subscription, Subscription.mod_pk == Mod.id)
        .where(Subscription.guild_id == guild_id)
    )
    return result.scalars().all()


@router.post("/guilds/{guild_id}/mods", response_model=ModOut, status_code=201)
async def subscribe(guild_id: int, body: TrackModRequest, db: AsyncSession = Depends(get_db)):
    try:
        info = await get_mod_info(body.game_domain, body.mod_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, "That mod doesn't exist on Nexus") from e
        logger.warning("Nexus error tracking %s/%s: %s", body.game_domain, body.mod_id, e)
        raise HTTPException(502, "Nexus API error") from e

    await _get_or_create_guild(db, guild_id)

    mod = (
        await db.execute(
            select(Mod).where(Mod.game_domain == body.game_domain, Mod.mod_id == body.mod_id)
        )
    ).scalar_one_or_none()
    if mod is None:
        mod = Mod(game_domain=body.game_domain, mod_id=body.mod_id, **extract_fields(info))
        db.add(mod)
        await db.flush()

    db.add(Subscription(guild_id=guild_id, mod_pk=mod.id))
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "Already tracking that mod") from e
    return mod


@router.delete("/guilds/{guild_id}/mods", status_code=204)
async def unsubscribe(
    guild_id: int, game_domain: str, mod_id: int, db: AsyncSession = Depends(get_db)
):
    mod = (
        await db.execute(select(Mod).where(Mod.game_domain == game_domain, Mod.mod_id == mod_id))
    ).scalar_one_or_none()
    if mod is None:
        raise HTTPException(404, "Not tracking that mod")

    sub = (
        await db.execute(
            select(Subscription).where(
                Subscription.guild_id == guild_id, Subscription.mod_pk == mod.id
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(404, "Not tracking that mod")

    await db.delete(sub)
    await db.flush()
    await _prune_orphan_mods(db)
    await db.commit()


@router.delete("/guilds/{guild_id}", status_code=204)
async def remove_guild(guild_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Subscription).where(Subscription.guild_id == guild_id))
    await db.execute(delete(Guild).where(Guild.guild_id == guild_id))
    await _prune_orphan_mods(db)
    await db.commit()


@router.get("/games", response_model=list[GameOut])
async def games(q: str):
    ql = q.strip().lower()
    if not ql:
        return []
    try:
        matches = [g for g in await get_games() if ql in g["name"].lower()]
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, "Nexus API error") from e
    return matches[:25]


@router.get("/mods/search", response_model=list[SearchResultOut])
async def search(q: str, game: str | None = None):
    if len(q.strip()) < 3:
        return []
    try:
        return await search_mods(q, game=game)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, "Nexus API error") from e


@router.get("/mods/info", response_model=ModInfoOut)
async def mod_info(game_domain: str, mod_id: int):
    try:
        info = await get_mod_info(game_domain, mod_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, "That mod doesn't exist on Nexus") from e
        raise HTTPException(502, "Nexus API error") from e
    f = extract_fields(info)
    return ModInfoOut(
        game_domain=game_domain,
        mod_id=mod_id,
        name=f["name"],
        version=f["version"],
        author=f["author"],
        picture_url=f["picture_url"],
    )


@router.post("/check", response_model=list[ChangedModOut])
async def check_for_updates(db: AsyncSession = Depends(get_db)):
    # invariant: every row in `mods` has >=1 subscriber (we prune on unsubscribe/guild removal)
    mods = (await db.execute(select(Mod))).scalars().all()
    by_domain: dict[str, list[Mod]] = {}
    for mod in mods:
        by_domain.setdefault(mod.game_domain, []).append(mod)

    now = datetime.now(UTC)
    changed: list[Mod] = []

    for game_domain, domain_mods in by_domain.items():
        try:
            updated = await get_updated_mods(game_domain, period=CHECK_PERIOD)
        except Exception as e:
            logger.warning("Skipping game %s: %s", game_domain, e)
            continue
        activity = {u["mod_id"]: u["latest_mod_activity"] for u in updated}

        for mod in domain_mods:
            mod.last_checked = now
            latest = activity.get(mod.mod_id)
            if latest is None or latest <= mod.nexus_updated_at:
                continue
            try:
                info = await get_mod_info(mod.game_domain, mod.mod_id)
            except Exception as e:
                logger.warning("Skipping %s/%s: %s", mod.game_domain, mod.mod_id, e)
                continue
            for key, value in extract_fields(info).items():
                setattr(mod, key, value)
            changed.append(mod)

    await db.commit()

    targets_by_mod: dict[int, list[NotifyTarget]] = {}
    if changed:
        rows = (
            await db.execute(
                select(Subscription.mod_pk, Guild.guild_id, Guild.channel_id)
                .join(Guild, Guild.guild_id == Subscription.guild_id)
                .where(
                    Subscription.mod_pk.in_([m.id for m in changed]),
                    Guild.channel_id.is_not(None),
                )
            )
        ).all()
        for mod_pk, guild_id, channel_id in rows:
            targets_by_mod.setdefault(mod_pk, []).append(
                NotifyTarget(guild_id=guild_id, channel_id=channel_id)
            )

    out = [
        ChangedModOut(mod=ModOut.model_validate(mod), notify=targets_by_mod.get(mod.id, []))
        for mod in changed
    ]

    logger.info(
        "Checked %d mods across %d games, %d changed", len(mods), len(by_domain), len(changed)
    )
    return out


app.include_router(router)
