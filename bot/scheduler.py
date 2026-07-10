import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import api, settings

logger = logging.getLogger("bot.scheduler")

NEXUS_ORANGE = 0xDA8E35


def mod_url(game_domain: str, mod_id: int) -> str:
    return f"https://www.nexusmods.com/{game_domain}/mods/{mod_id}"


def build_update_embed(mod: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mod['name'][:250]} updated!",
        description=f"New version: **v{mod['version']}**",
        url=mod_url(mod["game_domain"], mod["mod_id"]),
        color=NEXUS_ORANGE,
    )
    if mod.get("author"):
        embed.add_field(name="Author", value=mod["author"][:200], inline=True)
    if mod.get("picture_url"):
        embed.set_thumbnail(url=mod["picture_url"])
    return embed


async def post_updates(bot: discord.Client, changed: list[dict]) -> None:
    for item in changed:
        embed = build_update_embed(item["mod"])
        for target in item["notify"]:
            channel = bot.get_channel(target["channel_id"])
            if channel is None:
                logger.warning(
                    "Channel %s not found (guild %s)", target["channel_id"], target["guild_id"]
                )
                continue
            try:
                await channel.send(embed=embed)
            except discord.HTTPException as e:
                logger.warning("Failed to post to channel %s: %s", target["channel_id"], e)


async def run_check(bot: discord.Client) -> int:
    r = await api.post("/check")
    r.raise_for_status()
    changed = r.json()
    await post_updates(bot, changed)
    return len(changed)


async def poll_and_notify(bot: discord.Client) -> None:
    try:
        await run_check(bot)
    except Exception as e:
        logger.warning("Poll failed: %s", e)


def start_scheduler(bot: discord.Client) -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_and_notify, "interval", minutes=settings.poll_interval_minutes, args=[bot]
    )
    scheduler.start()
    logger.info("Scheduler started (every %d min)", settings.poll_interval_minutes)
