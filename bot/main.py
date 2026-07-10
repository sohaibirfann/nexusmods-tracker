import logging

import discord
import httpx
from discord import app_commands

from bot.config import api, settings
from bot.scheduler import NEXUS_ORANGE, mod_url, run_check, start_scheduler

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


@bot.tree.error
async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
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


async def _do_track(guild_id: int, game_domain: str, mod_id: int) -> str:
    r = await api.post(
        f"/guilds/{guild_id}/mods", json={"game_domain": game_domain, "mod_id": mod_id}
    )
    if r.status_code == 201:
        d = r.json()
        return f"Now tracking **{d['name']}** (v{d['version']})."
    if r.status_code == 409:
        return "Already tracking that mod."
    if r.status_code == 404:
        return "That mod doesn't exist on Nexus."
    return "Something went wrong talking to the backend."


@bot.tree.command(name="setchannel", description="Set the channel where mod updates get posted")
@app_commands.describe(channel="Channel to post updates in (defaults to this one)")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    target = channel or interaction.channel
    await interaction.response.defer(ephemeral=True)
    await api.put(f"/guilds/{interaction.guild_id}/channel", json={"channel_id": target.id})
    await interaction.followup.send(f"Updates will be posted in {target.mention}.", ephemeral=True)


@bot.tree.command(name="track", description="Track a mod for updates")
@app_commands.describe(game="Nexus game domain e.g. skyrimspecialedition", mod_id="Numeric mod ID")
@app_commands.guild_only()
async def track(interaction: discord.Interaction, game: str, mod_id: int):
    await interaction.response.defer()
    await interaction.followup.send(await _do_track(interaction.guild_id, game, mod_id))


@bot.tree.command(name="trackurl", description="Track a mod by pasting its Nexus URL")
@app_commands.describe(url="Full mod URL, e.g. nexusmods.com/skyrimspecialedition/mods/266")
@app_commands.guild_only()
async def trackurl(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    parsed = parse_mod_url(url)
    if parsed is None:
        await interaction.followup.send(
            "Paste a full mod URL like nexusmods.com/skyrimspecialedition/mods/266"
        )
        return
    await interaction.followup.send(await _do_track(interaction.guild_id, *parsed))


@bot.tree.command(name="untrack", description="Stop tracking a mod")
@app_commands.describe(game="Nexus game domain", mod_id="Numeric mod ID")
@app_commands.guild_only()
async def untrack(interaction: discord.Interaction, game: str, mod_id: int):
    await interaction.response.defer()
    r = await api.delete(
        f"/guilds/{interaction.guild_id}/mods", params={"game_domain": game, "mod_id": mod_id}
    )
    if r.status_code == 204:
        await interaction.followup.send("Stopped tracking it.")
    elif r.status_code == 404:
        await interaction.followup.send("You're not tracking that mod.")
    else:
        await interaction.followup.send("Something went wrong.")


@bot.tree.command(name="list", description="List tracked mods")
@app_commands.guild_only()
async def list_mods(interaction: discord.Interaction):
    await interaction.response.defer()
    r = await api.get(f"/guilds/{interaction.guild_id}/mods")
    mods = r.json()
    if not mods:
        await interaction.followup.send("Not tracking anything yet.")
        return
    lines = [
        f"• **{m['name']}** — v{m['version']} ({m['game_domain']}, id {m['mod_id']})" for m in mods
    ]
    await interaction.followup.send("\n".join(lines)[:2000])


@bot.tree.command(name="info", description="Look up a mod without tracking it")
@app_commands.describe(game="Nexus game domain", mod_id="Numeric mod ID")
@app_commands.guild_only()
async def info(interaction: discord.Interaction, game: str, mod_id: int):
    await interaction.response.defer()
    r = await api.get("/mods/info", params={"game_domain": game, "mod_id": mod_id})
    if r.status_code == 404:
        await interaction.followup.send("That mod doesn't exist on Nexus.")
        return
    if r.status_code != 200:
        await interaction.followup.send("Something went wrong.")
        return
    d = r.json()
    embed = discord.Embed(
        title=d["name"],
        description=f"Version **{d['version']}** by {d['author']}",
        url=mod_url(game, mod_id),
        color=NEXUS_ORANGE,
    )
    if d.get("picture_url"):
        embed.set_thumbnail(url=d["picture_url"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="check", description="Check all tracked mods for updates now")
@app_commands.checks.cooldown(1, 300, key=lambda i: i.guild_id)
@app_commands.guild_only()
async def check(interaction: discord.Interaction):
    await interaction.response.defer()
    count = await run_check(bot)
    await interaction.followup.send(f"Check done — {count} update(s) found.")


def run():
    bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    run()
