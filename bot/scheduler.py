import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import api, settings

logger = logging.getLogger("bot.scheduler")

NEXUS_ORANGE = 0xDA8E35
SPACER = chr(0x200B)  # zero-width space; Discord rejects empty field name/value


def mod_url(game_domain: str, mod_id: int) -> str:
    return f"https://www.nexusmods.com/{game_domain}/mods/{mod_id}"


def abbrev(n: int) -> str:
    for unit, size in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if n >= size:
            return f"{n / size:.1f}{unit}".replace(".0", "")
    return str(n)


def build_mod_embed(mod: dict, status: str = "") -> discord.Embed:
    """A big, consistent card for one mod: title link, grouped fields, and a large image."""
    link = mod_url(mod["game_domain"], mod["mod_id"])
    summary = (mod.get("summary") or "")[:400]
    description = "\n\n".join(p for p in (status, summary) if p)
    embed = discord.Embed(
        title=mod["name"][:250], url=link, description=description, color=NEXUS_ORANGE
    )
    if mod.get("game_name"):
        embed.set_author(name=mod["game_name"])
    if mod.get("game_image_url"):
        embed.set_thumbnail(url=mod["game_image_url"])

    basic = []
    if mod.get("version"):
        basic.append(("Version", f"v{mod['version']}"))
    if mod.get("author"):
        basic.append(("Author", mod["author"][:200]))
    stats = []
    if mod.get("endorsements"):
        stats.append(("Endorsements", abbrev(mod["endorsements"])))
    if mod.get("downloads"):
        stats.append(("Downloads", abbrev(mod["downloads"])))
    if mod.get("nexus_updated_at"):
        stats.append(("Updated", f"<t:{mod['nexus_updated_at']}:R>"))
    links = f"[Files]({link}?tab=files) • [Changelog]({link}?tab=logs)"

    groups = [g for g in (basic, stats) if g]
    for group in groups:
        for name, value in group:
            embed.add_field(name=name, value=value, inline=True)
        embed.add_field(name=SPACER, value=SPACER, inline=False)
    embed.add_field(name="Links", value=links, inline=False)

    if mod.get("picture_url"):
        embed.set_image(url=mod["picture_url"])
    return embed


def build_track_embed(mod: dict) -> discord.Embed:
    return build_mod_embed(mod, "✅ Now tracking this mod.")


def build_update_embed(mod: dict) -> discord.Embed:
    return build_mod_embed(mod, "🔔 New update available!")


HELP_SECTIONS = [
    ("⚙️ Setup", [("setchannel", "pick the channel where updates get posted")]),
    (
        "📥 Tracking",
        [
            ("track", "track a mod by name"),
            ("trackurl", "track a mod by pasting its URL"),
            ("untrack", "stop tracking a mod"),
        ],
    ),
    (
        "🔍 Browse",
        [
            ("list", "see your tracked mods"),
            ("info", "preview a mod without tracking it"),
            ("check", "check for updates right now"),
        ],
    ),
]


def build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎮 Nexus Mods Tracker",
        description="Get pinged the moment your favorite Nexus mods update.",
        color=NEXUS_ORANGE,
    )
    for heading, cmds in HELP_SECTIONS:
        value = "\n".join(f"`/{name}` — {desc}" for name, desc in cmds)
        embed.add_field(name=heading, value=value, inline=False)
    return embed


def build_status_embed(
    guild_name: str,
    guild_icon_url: str | None,
    channel_id: int | None,
    mod_count: int,
    poll_minutes: int,
) -> discord.Embed:
    channel = f"<#{channel_id}>" if channel_id else "Not set — run `/setchannel`"
    embed = discord.Embed(title="📊 Server status", color=NEXUS_ORANGE)
    embed.set_author(name=guild_name)
    if guild_icon_url:
        embed.set_thumbnail(url=guild_icon_url)
    embed.add_field(name="Update channel", value=channel, inline=True)
    embed.add_field(name="Tracked mods", value=str(mod_count), inline=True)
    embed.add_field(name="Check interval", value=f"every {poll_minutes} min", inline=True)
    embed.set_footer(text="/list to see tracked mods · /help for all commands")
    return embed


PAGE_SIZE = 10


def paginate(items: list, page: int, size: int = PAGE_SIZE) -> tuple[list, int, int]:
    """Return (page_slice, clamped_page, total_pages)."""
    pages = max(1, (len(items) + size - 1) // size)
    page = max(0, min(page, pages - 1))
    return items[page * size : page * size + size], page, pages


def build_list_embed(mods: list[dict], page: int = 0) -> discord.Embed:
    if not mods:
        return discord.Embed(
            title="Tracked mods", description="Not tracking anything yet.", color=NEXUS_ORANGE
        )
    page_mods, page, pages = paginate(mods, page)
    lines = [
        f"[{m['name']}]({mod_url(m['game_domain'], m['mod_id'])}) — v{m['version']}"
        for m in page_mods
    ]
    embed = discord.Embed(title="Tracked mods", description="\n".join(lines), color=NEXUS_ORANGE)
    if pages > 1:
        embed.set_footer(text=f"Page {page + 1}/{pages}")
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
