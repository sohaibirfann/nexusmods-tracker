import logging
import re

import discord
import httpx
from discord import app_commands

from bot.config import api, settings
from bot.scheduler import (
    PAGE_SIZE,
    build_help_embed,
    build_list_embed,
    build_mod_embed,
    build_status_embed,
    build_track_embed,
    paginate,
    run_check,
    start_scheduler,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bot")


def parse_mod_url(url: str) -> tuple[str, int] | None:
    """Pull (game_domain, mod_id) out of a Nexus mod URL, or None if it doesn't fit."""
    cleaned = url.strip().split("?")[0].split("#")[0].rstrip("/")
    if "/mods/" not in cleaned:
        return None
    before, after = cleaned.split("/mods/", 1)
    game = before.split("/")[-1]
    mod_id = after.split("/")[0]
    # a game domain is a bare slug; a dot means we grabbed the hostname, not a game
    if not game or "." in game or not mod_id.isdigit():
        return None
    return game, int(mod_id)


_TRACK_VALUE = re.compile(r"^([\w-]+):(\d+)$")


def parse_track_value(value: str) -> tuple[str, int] | None:
    """Parse a picked suggestion's 'game:modid' value, or None for free-typed text."""
    m = _TRACK_VALUE.match(value.strip())
    return (m.group(1), int(m.group(2))) if m else None


class TrackerBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        start_scheduler(self)

    async def close(self):
        await api.aclose()
        await super().close()


bot = TrackerBot()


@bot.event
async def on_ready():
    logger.info("Logged in as %s", bot.user)


@bot.event
async def on_guild_remove(guild: discord.Guild):
    try:
        await api.delete(f"/guilds/{guild.id}")
    except httpx.HTTPError as e:
        logger.warning("Cleanup failed for guild %s: %s", guild.id, e)


WELCOME = (
    "👋 **Thanks for adding me!**\n"
    "1. Run `/setchannel` to pick where mod updates get posted.\n"
    "2. Use `/track` to follow a mod — I'll announce new versions automatically.\n"
    "Run `/help` to see everything I can do."
)


@bot.event
async def on_guild_join(guild: discord.Guild):
    channel = guild.system_channel
    if channel is None or not channel.permissions_for(guild.me).send_messages:
        return
    try:
        await channel.send(WELCOME)
    except discord.HTTPException as e:
        logger.warning("Welcome message failed for guild %s: %s", guild.id, e)


@bot.tree.error
async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if interaction.type == discord.InteractionType.autocomplete:
        logger.warning("Autocomplete error: %s", error)
        return
    if isinstance(error, app_commands.CommandOnCooldown):
        msg = f"Slow down — try again in {error.retry_after:.0f}s."
    elif isinstance(error, app_commands.MissingPermissions):
        msg = "You need the Manage Server permission for that."
    else:
        logger.exception("Command error", exc_info=error)
        msg = "Something went wrong."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def _do_track(guild_id: int, game_domain: str, mod_id: int) -> dict | str:
    """Returns the tracked mod on success, or an error message string."""
    r = await api.post(
        f"/guilds/{guild_id}/mods", json={"game_domain": game_domain, "mod_id": mod_id}
    )
    if r.status_code == 201:
        return r.json()
    if r.status_code == 409:
        return "Already tracking that mod."
    if r.status_code == 404:
        return "That mod doesn't exist on Nexus."
    return "Something went wrong talking to the backend."


async def _send_track_result(interaction: discord.Interaction, result: dict | str) -> None:
    if isinstance(result, dict):
        await interaction.followup.send(embed=build_track_embed(result))
    else:
        await interaction.followup.send(result)


async def _resolve_mod(game: str, mod: str) -> tuple[str, int] | None:
    """Turn a picked suggestion or free-typed name into (game_domain, mod_id)."""
    parsed = parse_track_value(mod)
    if parsed is not None:
        return parsed
    r = await api.get("/mods/search", params={"q": mod, "game": game})
    results = r.json() if r.status_code == 200 else []
    return (results[0]["game_domain"], results[0]["mod_id"]) if results else None


NO_CHANNEL_WARNING = "⚠️ No update channel set yet — run `/setchannel` so I can post updates."


async def _has_channel(guild_id: int) -> bool:
    try:
        r = await api.get(f"/guilds/{guild_id}")
    except httpx.HTTPError:
        return True
    if r.status_code != 200:
        return True
    return r.json().get("channel_id") is not None


async def _track_and_reply(interaction: discord.Interaction, game_domain: str, mod_id: int) -> None:
    result = await _do_track(interaction.guild_id, game_domain, mod_id)
    await _send_track_result(interaction, result)
    if isinstance(result, dict) and not await _has_channel(interaction.guild_id):
        await interaction.followup.send(NO_CHANNEL_WARNING, ephemeral=True)


@bot.tree.command(name="setchannel", description="Set the channel where mod updates get posted")
@app_commands.describe(channel="Channel to post updates in (defaults to this one)")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    target = channel or interaction.channel
    await interaction.response.defer(ephemeral=True)
    await api.put(f"/guilds/{interaction.guild_id}/channel", json={"channel_id": target.id})
    if target.permissions_for(interaction.guild.me).send_messages:
        msg = f"Updates will be posted in {target.mention}."
    else:
        msg = f"Set to {target.mention}, but I can't post there — grant me Send Messages."
    await interaction.followup.send(msg, ephemeral=True)


# Discord discards autocomplete replies after ~3s, so these calls fail fast
AUTOCOMPLETE_TIMEOUT = 2


async def game_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if len(current.strip()) < 2:
        return []
    try:
        r = await api.get("/games", params={"q": current}, timeout=AUTOCOMPLETE_TIMEOUT)
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    return [app_commands.Choice(name=g["name"][:100], value=g["domain"]) for g in r.json()]


async def mod_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if len(current.strip()) < 3:
        return []
    game = getattr(interaction.namespace, "game", None)
    params = {"q": current, "game": game} if game else {"q": current}
    try:
        r = await api.get("/mods/search", params=params, timeout=AUTOCOMPLETE_TIMEOUT)
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    return [
        app_commands.Choice(name=m["name"][:100], value=f"{m['game_domain']}:{m['mod_id']}")
        for m in r.json()
    ]


@bot.tree.command(name="track", description="Track a mod for updates")
@app_commands.describe(game="Pick the game", mod="Search the mod by name")
@app_commands.autocomplete(game=game_autocomplete, mod=mod_autocomplete)
@app_commands.guild_only()
async def track(interaction: discord.Interaction, game: str, mod: str):
    await interaction.response.defer(ephemeral=True)
    parsed = await _resolve_mod(game, mod)
    if parsed is None:
        await interaction.followup.send("No mod found by that name.")
        return
    await _track_and_reply(interaction, *parsed)


@bot.tree.command(name="trackurl", description="Track a mod by pasting its Nexus URL")
@app_commands.describe(url="Full mod URL, e.g. nexusmods.com/skyrimspecialedition/mods/266")
@app_commands.guild_only()
async def trackurl(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=True)
    parsed = parse_mod_url(url)
    if parsed is None:
        await interaction.followup.send(
            "Paste a full mod URL like nexusmods.com/skyrimspecialedition/mods/266"
        )
        return
    await _track_and_reply(interaction, *parsed)


def _find_tracked(tracked: list[dict], mod: str) -> dict | None:
    """Match a picked 'game:modid' value or a free-typed name against the tracked list."""
    parsed = parse_track_value(mod)
    if parsed is not None:
        game, mod_id = parsed
        return next(
            (m for m in tracked if m["game_domain"] == game and m["mod_id"] == mod_id), None
        )
    cur = mod.strip().lower()
    return next((m for m in tracked if cur in m["name"].lower()), None)


async def tracked_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    try:
        r = await api.get(f"/guilds/{interaction.guild_id}/mods", timeout=AUTOCOMPLETE_TIMEOUT)
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    cur = current.strip().lower()
    mods = [m for m in r.json() if cur in m["name"].lower()]
    return [
        app_commands.Choice(
            name=f"{m['name']} — {m['game_domain']}"[:100],
            value=f"{m['game_domain']}:{m['mod_id']}",
        )
        for m in mods[:25]
    ]


@bot.tree.command(name="untrack", description="Stop tracking a mod")
@app_commands.describe(mod="Pick one of your tracked mods")
@app_commands.autocomplete(mod=tracked_autocomplete)
@app_commands.guild_only()
async def untrack(interaction: discord.Interaction, mod: str):
    await interaction.response.defer(ephemeral=True)
    r = await api.get(f"/guilds/{interaction.guild_id}/mods")
    target = _find_tracked(r.json() if r.status_code == 200 else [], mod)
    if target is None:
        await interaction.followup.send("You're not tracking that mod.")
        return
    r = await api.delete(
        f"/guilds/{interaction.guild_id}/mods",
        params={"game_domain": target["game_domain"], "mod_id": target["mod_id"]},
    )
    if r.status_code == 204:
        await interaction.followup.send(f"Stopped tracking **{target['name']}**.")
    else:
        await interaction.followup.send("Something went wrong.")


class ListView(discord.ui.View):
    def __init__(self, mods: list[dict]):
        super().__init__(timeout=120)
        self.mods = mods
        self.page = 0
        self._sync()

    def _sync(self) -> None:
        _, self.page, pages = paginate(self.mods, self.page)
        self.prev_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= pages - 1

    async def _show(self, interaction: discord.Interaction) -> None:
        self._sync()
        await interaction.response.edit_message(
            embed=build_list_embed(self.mods, self.page), view=self
        )

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await self._show(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self._show(interaction)


@bot.tree.command(name="list", description="List tracked mods")
@app_commands.guild_only()
async def list_mods(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    r = await api.get(f"/guilds/{interaction.guild_id}/mods")
    if r.status_code != 200:
        await interaction.followup.send("Couldn't fetch your list.")
        return
    mods = r.json()
    kwargs = {"embed": build_list_embed(mods)}
    if len(mods) > PAGE_SIZE:
        kwargs["view"] = ListView(mods)
    await interaction.followup.send(**kwargs)
    if mods and not await _has_channel(interaction.guild_id):
        await interaction.followup.send(NO_CHANNEL_WARNING, ephemeral=True)


@bot.tree.command(name="status", description="Show this server's tracker setup")
@app_commands.guild_only()
async def status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    gid = interaction.guild_id
    r = await api.get(f"/guilds/{gid}/mods")
    if r.status_code != 200:
        await interaction.followup.send("Couldn't fetch your status.")
        return
    guild = await api.get(f"/guilds/{gid}")
    channel_id = guild.json().get("channel_id") if guild.status_code == 200 else None
    g = interaction.guild
    icon_url = g.icon.url if g.icon else None
    await interaction.followup.send(
        embed=build_status_embed(
            g.name, icon_url, channel_id, len(r.json()), settings.poll_interval_minutes
        )
    )


class TrackButtonView(discord.ui.View):
    def __init__(self, game_domain: str, mod_id: int):
        super().__init__(timeout=120)
        self.game_domain = game_domain
        self.mod_id = mod_id

    @discord.ui.button(label="Track this", style=discord.ButtonStyle.success)
    async def track_this(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await _track_and_reply(interaction, self.game_domain, self.mod_id)


@bot.tree.command(name="info", description="Look up a mod without tracking it")
@app_commands.describe(game="Pick the game", mod="Search the mod by name")
@app_commands.autocomplete(game=game_autocomplete, mod=mod_autocomplete)
@app_commands.guild_only()
async def info(interaction: discord.Interaction, game: str, mod: str):
    await interaction.response.defer(ephemeral=True)
    parsed = await _resolve_mod(game, mod)
    if parsed is None:
        await interaction.followup.send("No mod found by that name.")
        return
    game_domain, mod_id = parsed
    r = await api.get("/mods/info", params={"game_domain": game_domain, "mod_id": mod_id})
    if r.status_code == 404:
        await interaction.followup.send("That mod doesn't exist on Nexus.")
        return
    if r.status_code != 200:
        await interaction.followup.send("Something went wrong.")
        return
    await interaction.followup.send(
        embed=build_mod_embed(r.json()), view=TrackButtonView(game_domain, mod_id)
    )


@bot.tree.command(name="check", description="Check all tracked mods for updates now")
# one global bucket: /check runs a full cross-guild sweep, so it serves everyone at once
@app_commands.checks.cooldown(1, 300, key=lambda i: None)
@app_commands.guild_only()
async def check(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    count = await run_check(bot)
    await interaction.followup.send(f"Check done — {count} update(s) found.")


@bot.tree.command(name="help", description="Show what this bot can do")
@app_commands.guild_only()
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=build_help_embed())


def run():
    bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    run()
