import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import api, settings

logger = logging.getLogger("bot.scheduler")

NEXUS_ORANGE = 0xDA8E35


def mod_url(game_domain: str, mod_id: int) -> str:
    return f"https://www.nexusmods.com/{game_domain}/mods/{mod_id}"


def build_mod_embed(mod: dict, status: str = "") -> discord.Embed:
    """A big, consistent card for one mod: title link, fields, and a large image."""
    link = mod_url(mod["game_domain"], mod["mod_id"])
    embed = discord.Embed(
        title=mod["name"][:250], url=link, description=status, color=NEXUS_ORANGE
    )
    if mod.get("version"):
        embed.add_field(name="Version", value=f"v{mod['version']}", inline=True)
    if mod.get("author"):
        embed.add_field(name="Author", value=mod["author"][:200], inline=True)
    links = f"[Files]({link}?tab=files) • [Changelog]({link}?tab=logs)"
    embed.add_field(name="Links", value=links, inline=False)
    if mod.get("picture_url"):
        embed.set_image(url=mod["picture_url"])
    return embed


def build_track_embed(mod: dict) -> discord.Embed:
    return build_mod_embed(mod, "✅ Now tracking this mod.")


def build_update_embed(mod: dict) -> discord.Embed:
    return build_mod_embed(mod, "🔔 New update available!")


def build_list_embed(mods: list[dict]) -> discord.Embed:
    if not mods:
        return discord.Embed(
            title="Tracked mods", description="Not tracking anything yet.", color=NEXUS_ORANGE
        )
    lines = [
        f"[{m['name']}]({mod_url(m['game_domain'], m['mod_id'])}) — v{m['version']}" for m in mods
    ]
    # long lists get paginated in a later change; trim to the embed limit for now
    return discord.Embed(
        title="Tracked mods", description="\n".join(lines)[:4096], color=NEXUS_ORANGE
    )


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
