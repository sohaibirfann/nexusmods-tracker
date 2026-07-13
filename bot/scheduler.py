import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import api, settings

logger = logging.getLogger("bot.scheduler")

NEXUS_ORANGE = 0xDA8E35


def mod_url(game_domain: str, mod_id: int) -> str:
    return f"https://www.nexusmods.com/{game_domain}/mods/{mod_id}"


def abbrev(n: int) -> str:
    for unit, size in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if n >= size:
            return f"{n / size:.1f}{unit}".replace(".0", "")
    return str(n)


def _stat(total: int, delta: int) -> str:
    return f"{abbrev(total)} (+{abbrev(delta)})" if delta > 0 else abbrev(total)


def _changelog_body(changelog: list, link: str, limit: int = 6) -> str:
    """Markdown for the description: '### ' author headers, '- ' list items (hanging indent)."""
    lines = []
    for raw in changelog[:limit]:
        s = raw.strip()
        if not s or set(s) <= set("-–—=_*•· "):  # blank line or a horizontal rule
            continue
        if s.endswith(":"):
            lines.append(f"### {s}")
        else:
            lines.append(f"- {s.lstrip('-–—*•· ').strip()}")
    if not lines:
        return ""
    more = f"\n[…full changelog]({link}?tab=logs)" if len(changelog) > limit else ""
    return "\n".join(lines)[: 3900 - len(more)] + more


def build_mod_embed(
    mod: dict,
    status: str = "",
    *,
    update: bool = False,
    endorsement_delta: int = 0,
    download_delta: int = 0,
    changelog: list | tuple = (),
) -> discord.Embed:
    """Compact card: mod image as thumbnail, no big image, fields wrap 3-per-row."""
    link = mod_url(mod["game_domain"], mod["mod_id"])
    # update posts lead with the changelog (markdown); everything else with the mod summary
    changelog_md = _changelog_body(changelog, link) if update else ""
    body = changelog_md or (mod.get("summary") or "")[:300]
    description = "\n\n".join(p for p in (status, body) if p)
    embed = discord.Embed(
        title=mod["name"][:250], url=link, description=description, color=NEXUS_ORANGE
    )
    if mod.get("game_name"):
        embed.set_author(name=mod["game_name"], icon_url=mod.get("game_image_url") or None)
    if mod.get("picture_url"):
        embed.set_thumbnail(url=mod["picture_url"])

    updated = f"<t:{mod['nexus_updated_at']}:R>" if mod.get("nexus_updated_at") else None
    fields = []
    if not update:  # track/info: version + author lead; on update they move to the status line
        if mod.get("version"):
            fields.append(("Version", f"v{mod['version']}"))
        if mod.get("author"):
            fields.append(("Author", mod["author"][:200]))
        if updated:
            fields.append(("Updated", updated))
    if mod.get("endorsements"):
        fields.append(("Endorsements", _stat(mod["endorsements"], endorsement_delta)))
    if mod.get("downloads"):
        fields.append(("Downloads", _stat(mod["downloads"], download_delta)))
    if update and updated:
        fields.append(("Updated", updated))
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=True)
    return embed


def _ping_kwargs(role_id: int | None) -> dict:
    """content + scoped allowed_mentions to ping one role, or {} if none set."""
    if not role_id:
        return {}
    return {
        "content": f"<@&{role_id}>",
        # scope so a stray mention in content can never ping @everyone or another role
        "allowed_mentions": discord.AllowedMentions(
            everyone=False, users=False, roles=[discord.Object(role_id)]
        ),
    }


def mod_link_view(mod: dict) -> discord.ui.View:
    link = mod_url(mod["game_domain"], mod["mod_id"])
    view = discord.ui.View(timeout=None)  # link buttons carry no state, never expire
    view.add_item(discord.ui.Button(label="Mod page", url=link))
    view.add_item(discord.ui.Button(label="Changelog", url=f"{link}?tab=logs"))
    view.add_item(discord.ui.Button(label="Files", url=f"{link}?tab=files"))
    return view


def build_track_embed(mod: dict) -> discord.Embed:
    return build_mod_embed(mod, "✅ Now tracking this mod")


def build_update_embed(
    mod: dict,
    previous_version: str = "",
    endorsement_delta: int = 0,
    download_delta: int = 0,
    changelog: list | tuple = (),
) -> discord.Embed:
    v = mod.get("version")
    if previous_version and v and previous_version != v:
        status = f"🔔 Updated: v{previous_version} → v{v}"
    elif v:
        status = f"🔔 Updated to v{v}"
    else:
        status = "🔔 New version available"
    return build_mod_embed(
        mod,
        status,
        update=True,
        endorsement_delta=endorsement_delta,
        download_delta=download_delta,
        changelog=changelog,
    )


HELP_SECTIONS = [
    (
        "⚙️ Setup",
        [
            ("setchannel", "pick the channel where updates get posted"),
            ("setping", "role to ping when a mod updates"),
        ],
    ),
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
            ("status", "see this server's setup"),
        ],
    ),
]


def _cmd(name: str, ids: dict) -> str:
    """A clickable </name:id> mention when we know the command's id, else plain /name."""
    return f"</{name}:{ids[name]}>" if name in ids else f"/{name}"


def build_help_embed(command_ids: dict | None = None) -> discord.Embed:
    ids = command_ids or {}
    sections = [
        f"**{heading}**\n" + "\n".join(f"{_cmd(name, ids)} — {desc}" for name, desc in cmds)
        for heading, cmds in HELP_SECTIONS
    ]
    return discord.Embed(
        title="Nexus Mods Tracker",
        description="Get pinged the moment your favorite Nexus mods update.\n\n"
        + "\n\n".join(sections),
        color=NEXUS_ORANGE,
    )


def build_welcome_embed(command_ids: dict | None = None) -> discord.Embed:
    ids = command_ids or {}
    embed = discord.Embed(
        title="👋 Thanks for adding me!",
        description=(
            "I watch Nexus Mods and announce new versions right here.\n\n"
            f"**1.** Run {_cmd('setchannel', ids)} to pick where updates get posted\n"
            f"**2.** Use {_cmd('track', ids)} to follow your first mod"
        ),
        color=NEXUS_ORANGE,
    )
    embed.set_footer(text="/help shows everything I can do")
    return embed


def build_status_embed(
    guild_name: str,
    guild_icon_url: str | None,
    channel_id: int | None,
    ping_role_id: int | None,
    mod_count: int,
    poll_minutes: int,
) -> discord.Embed:
    channel = f"<#{channel_id}>" if channel_id else "⚠️ Not set — run `/setchannel`"
    ping = f"<@&{ping_role_id}>" if ping_role_id else "Not set"
    embed = discord.Embed(title="Server status", color=NEXUS_ORANGE)
    embed.set_author(name=guild_name)
    if guild_icon_url:
        embed.set_thumbnail(url=guild_icon_url)
    embed.add_field(name="Update channel", value=channel, inline=True)
    embed.add_field(name="Ping role", value=ping, inline=True)
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


def _list_line(m: dict) -> str:
    line = f"[{m['name']}]({mod_url(m['game_domain'], m['mod_id'])}) — v{m['version']}"
    if m.get("nexus_updated_at"):
        line += f" · updated <t:{m['nexus_updated_at']}:R>"
    return line


def build_list_embed(mods: list[dict], page: int = 0) -> discord.Embed:
    if not mods:
        return discord.Embed(
            title="Tracked mods", description="Not tracking anything yet.", color=NEXUS_ORANGE
        )
    page_mods, page, pages = paginate(mods, page)
    embed = discord.Embed(
        title="Tracked mods",
        description="\n".join(_list_line(m) for m in page_mods),
        color=NEXUS_ORANGE,
    )
    total = len(mods)
    footer = f"{total} mod{'' if total == 1 else 's'} tracked"
    if pages > 1:
        footer = f"Page {page + 1}/{pages} · {footer}"
    embed.set_footer(text=footer)
    return embed


async def post_updates(bot: discord.Client, changed: list[dict]) -> None:
    for item in changed:
        embed = build_update_embed(
            item["mod"],
            item.get("previous_version", ""),
            item.get("endorsement_delta", 0),
            item.get("download_delta", 0),
            item.get("changelog", []),
        )
        view = mod_link_view(item["mod"])
        for target in item["notify"]:
            channel = bot.get_channel(target["channel_id"])
            if channel is None:
                logger.warning(
                    "Channel %s not found (guild %s)", target["channel_id"], target["guild_id"]
                )
                continue
            try:
                await channel.send(
                    embed=embed, view=view, **_ping_kwargs(target.get("ping_role_id"))
                )
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
