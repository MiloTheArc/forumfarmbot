import asyncio
import io
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
FORUM_CHANNEL_ID = int(os.getenv("FORUM_CHANNEL_ID", "0"))
PRIORITY_TAG_NAME = os.getenv("PRIORITY_TAG_NAME", "Priority Drop")
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/farm_priority.db")

WIKI_API = "https://arcraiders.wiki/api.php"
USER_AGENT = "ArcRaidersFarmPriorityBot/2.0 (Discord community bot)"

if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable.")
if not FORUM_CHANNEL_ID:
    raise RuntimeError("Missing FORUM_CHANNEL_ID environment variable.")

db_dir = os.path.dirname(DATABASE_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

# ---------------------------------------------------------------------------
# BUILT-IN ITEMS
#
# label     = what your community sees/uses
# wiki_file = the ARC Raiders Wiki item image file used automatically
# aliases   = other names people can type
# ---------------------------------------------------------------------------

ITEMS = {
    "herbals": {
        "label": "Herbals",
        "wiki_file": "File:Herbal Bandage.png",
        "aliases": ["herbal", "herbal bandage", "bandage", "herbals"],
    },
    "batts": {
        "label": "Batts",
        "wiki_file": "File:Battery.png",
        "aliases": ["battery", "batteries", "batts", "batt"],
    },
    "ducks": {
        "label": "Ducks",
        "wiki_file": "File:Rubber Duck.png",
        "aliases": ["duck", "ducks", "rubber duck", "rubber ducks"],
    },
    "arc circ": {
        "label": "ARC Circ",
        "wiki_file": "File:ARC Circuitry.png",
        "aliases": ["arc circ", "arc circuitry", "circuitry"],
    },
    "showstoppers": {
        "label": "Showstoppers",
        "wiki_file": "File:Showstopper.png",
        "aliases": ["showstopper", "showstoppers"],
    },
    "smokes": {
        "label": "Smokes",
        "wiki_file": "File:Smoke Grenade.png",
        "aliases": ["smoke", "smokes", "smoke grenade", "smoke grenades"],
    },
    "power rods": {
        "label": "Power Rods",
        "wiki_file": "File:Power Rod.png",
        "aliases": ["power rod", "power rods"],
    },
    "hatch key": {
        "label": "Hatch Key",
        "wiki_file": "File:Raider Hatch Key.png",
        "aliases": ["hatch key", "hatch keys", "raider hatch key", "raider hatch keys"],
    },
    "survivor mk3": {
        "label": "Survivor MK3",
        "wiki_file": "File:Looting Mk. 3 (Survivor).png",
        "aliases": ["survivor mk3", "survivor mk 3", "looting mk3 survivor", "survivor"],
    },
    "duct tape": {
        "label": "Duct Tape",
        "wiki_file": "File:Duct Tape.png",
        "aliases": ["duct tape", "ducttape"],
    },
    "light gun parts": {
        "label": "Light Gun Parts",
        "wiki_file": "File:Light Gun Parts.png",
        "aliases": ["light gun parts", "light parts", "lgp"],
    },
    "exodus modules": {
        "label": "Exodus Modules",
        "wiki_file": "File:Exodus Modules.png",
        "aliases": ["exodus module", "exodus modules", "exodus"],
    },
    "hornet drivers": {
        "label": "Hornet Drivers",
        "wiki_file": "File:Hornet Driver.png",
        "aliases": ["hornet driver", "hornet drivers", "hornet"],
    },
    "advanced electrical": {
        "label": "Advanced Electrical",
        "wiki_file": "File:Advanced Electrical Components.png",
        "aliases": [
            "advanced electrical",
            "advanced electrical components",
            "aec",
        ],
    },
    "heavy fuze": {
        "label": "Heavy Fuze",
        "wiki_file": "File:Heavy Fuze Grenade.png",
        "aliases": ["heavy fuze", "heavy fuse", "heavy fuze grenade"],
    },
}

ALIAS_TO_KEY = {}
for key, data in ITEMS.items():
    ALIAS_TO_KEY[key.casefold()] = key
    ALIAS_TO_KEY[data["label"].casefold()] = key
    for alias in data["aliases"]:
        ALIAS_TO_KEY[alias.casefold()] = key


def normalize_item(value: str) -> Optional[str]:
    return ALIAS_TO_KEY.get(value.strip().casefold())


def db_connect():
    return sqlite3.connect(DATABASE_PATH)


def init_db():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS farm_priority_posts (
                thread_id INTEGER PRIMARY KEY,
                forum_id INTEGER NOT NULL,
                item TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        conn.commit()


def save_priority(thread_id: int, forum_id: int, item: str, expires_at: datetime):
    with db_connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO farm_priority_posts
            (thread_id, forum_id, item, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (thread_id, forum_id, item, expires_at.isoformat()),
        )
        conn.commit()


def delete_priority(thread_id: int):
    with db_connect() as conn:
        conn.execute(
            "DELETE FROM farm_priority_posts WHERE thread_id = ?",
            (thread_id,),
        )
        conn.commit()


def get_expired_priorities():
    now = datetime.now(timezone.utc)
    expired = []

    with db_connect() as conn:
        rows = conn.execute(
            "SELECT thread_id, item, expires_at FROM farm_priority_posts"
        ).fetchall()

    for thread_id, item, expires_at_text in rows:
        try:
            expires_at = datetime.fromisoformat(expires_at_text)
        except ValueError:
            expired.append((thread_id, item))
            continue

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at <= now:
            expired.append((thread_id, item))

    return expired


def find_priority_tag(forum: discord.ForumChannel):
    wanted = PRIORITY_TAG_NAME.casefold().strip()
    for tag in forum.available_tags:
        if tag.name.casefold().strip() == wanted:
            return tag
    return None


def priority_emoji(priority: str) -> str:
    return {
        "LOW": "🟢",
        "MEDIUM": "🟡",
        "HIGH": "🟠",
        "VERY HIGH": "🔴",
    }.get(priority, "🔴")


def build_post_text(label: str, needed: int, priority: str, hours: int) -> str:
    emoji = priority_emoji(priority)
    return (
        f"**COMMUNITY FARM PRIORITY**\n"
        f"**{label.upper()}**\n"
        f"We really need this item right now!\n\n"
        f"If you've got some spare time and you're doing farming runs, "
        f"please keep an eye out for **{label.lower()}**.\n\n"
        f"**Needed:** {needed}\n"
        f"**Priority:** {emoji} {priority}\n\n"
        f"You don't have to farm it — but every little bit helps the community!\n\n"
        f"This post automatically disappears after **{hours} hours**.\n"
        f"**ARC RAIDERS FARMERS • Every drop counts ❤️**"
    )


async def get_wiki_image_bytes(wiki_file: str):
    """
    Resolve the current image URL through the MediaWiki API, then download it.
    Returns: (bytes, filename) or (None, None)
    """
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "iiprop": "url",
        "titles": wiki_file,
        "formatversion": "2",
    }

    headers = {"User-Agent": USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=20)

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(WIKI_API, params=params) as response:
                if response.status != 200:
                    print(f"Wiki API returned HTTP {response.status} for {wiki_file}")
                    return None, None

                data = await response.json(content_type=None)

            pages = data.get("query", {}).get("pages", [])
            if not pages:
                print(f"No wiki page returned for {wiki_file}")
                return None, None

            page = pages[0]
            imageinfo = page.get("imageinfo", [])
            if not imageinfo:
                print(f"No imageinfo found for {wiki_file}")
                return None, None

            image_url = imageinfo[0].get("url")
            if not image_url:
                return None, None

            async with session.get(image_url) as image_response:
                if image_response.status != 200:
                    print(
                        f"Image download returned HTTP {image_response.status} "
                        f"for {wiki_file}"
                    )
                    return None, None

                raw = await image_response.read()

        filename = wiki_file.replace("File:", "", 1).replace("/", "_")
        return raw, filename

    except Exception as exc:
        print(f"Image fetch failed for {wiki_file}: {type(exc).__name__}: {exc}")
        return None, None


class FarmPriorityBot(commands.Bot):
    async def setup_hook(self):
        init_db()

        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} commands to guild {GUILD_ID}")
        else:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} global commands")

        if not cleanup_expired_posts.is_running():
            cleanup_expired_posts.start()


intents = discord.Intents.default()
bot = FarmPriorityBot(command_prefix="!", intents=intents)


@app_commands.command(
    name="farmpriority",
    description="Create an automatic ARC Raiders farm-priority post."
)
@app_commands.describe(
    item="Start typing the item name",
    needed="How many the community needs",
    priority="Priority level",
    hours="Hours before the post auto-deletes (default 24)",
)
@app_commands.choices(
    priority=[
        app_commands.Choice(name="LOW", value="LOW"),
        app_commands.Choice(name="MEDIUM", value="MEDIUM"),
        app_commands.Choice(name="HIGH", value="HIGH"),
        app_commands.Choice(name="VERY HIGH", value="VERY HIGH"),
    ]
)
@app_commands.checks.has_permissions(manage_threads=True)
async def farmpriority(
    interaction: discord.Interaction,
    item: str,
    needed: app_commands.Range[int, 1, 99999],
    priority: app_commands.Choice[str],
    hours: app_commands.Range[int, 1, 168] = 24,
):
    await interaction.response.defer(ephemeral=True)

    item_key = normalize_item(item)
    if item_key is None:
        supported = ", ".join(data["label"] for data in ITEMS.values())
        await interaction.followup.send(
            "❌ That item is not in the built-in list yet.\n\n"
            f"**Available:** {supported}",
            ephemeral=True,
        )
        return

    item_data = ITEMS[item_key]
    label = item_data["label"]

    try:
        channel = bot.get_channel(FORUM_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(FORUM_CHANNEL_ID)

        if not isinstance(channel, discord.ForumChannel):
            await interaction.followup.send(
                "❌ FORUM_CHANNEL_ID is not a Discord Forum channel.",
                ephemeral=True,
            )
            return

        tag = find_priority_tag(channel)
        tags = [tag] if tag else []

        title = f"COMMUNITY FARM PRIORITY — {label.upper()}"
        content = build_post_text(label, needed, priority.value, hours)

        kwargs = {
            "name": title[:100],
            "content": content,
            "applied_tags": tags,
            "auto_archive_duration": 1440,
            "reason": f"Farm priority created by {interaction.user}",
        }

        # Download the correct ARC Raiders item picture automatically.
        image_bytes, image_filename = await get_wiki_image_bytes(
            item_data["wiki_file"]
        )
        image_loaded = image_bytes is not None

        if image_loaded:
            kwargs["file"] = discord.File(
                io.BytesIO(image_bytes),
                filename=image_filename,
            )

        result = await channel.create_thread(**kwargs)
        thread = getattr(result, "thread", result)

        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        save_priority(thread.id, channel.id, label, expires_at)

        image_status = "🖼️ Correct item image added automatically." if image_loaded else (
            "⚠️ Post created, but the item image could not be downloaded this time."
        )

        await interaction.followup.send(
            f"✅ **{label}** priority created: <#{thread.id}>\n"
            f"{image_status}\n"
            f"🗑️ Auto-delete: **{hours} hours**.",
            ephemeral=True,
        )

    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I do not have enough permissions in the forum channel.\n"
            "Give the bot: View Channel, Send Messages, Create Public Threads, "
            "Send Messages in Threads, Attach Files and Manage Threads.",
            ephemeral=True,
        )
    except Exception as exc:
        print(f"farmpriority error: {type(exc).__name__}: {exc}")
        await interaction.followup.send(
            f"❌ Could not create the priority post.\n"
            f"`{type(exc).__name__}: {exc}`",
            ephemeral=True,
        )


@farmpriority.autocomplete("item")
async def farmpriority_item_autocomplete(
    interaction: discord.Interaction,
    current: str,
):
    current_cf = current.casefold().strip()

    matches = []
    for key, data in ITEMS.items():
        search_text = " ".join([data["label"], key] + data["aliases"]).casefold()

        if not current_cf or current_cf in search_text:
            matches.append(
                app_commands.Choice(
                    name=data["label"],
                    value=data["label"],
                )
            )

    return matches[:25]


@app_commands.command(
    name="farmpriorityclose",
    description="Delete the farm-priority post you are currently in."
)
@app_commands.checks.has_permissions(manage_threads=True)
async def farmpriorityclose(interaction: discord.Interaction):
    channel = interaction.channel

    if not isinstance(channel, discord.Thread):
        await interaction.response.send_message(
            "❌ Use this command inside the priority post you want to delete.",
            ephemeral=True,
        )
        return

    thread_id = channel.id

    await interaction.response.send_message(
        "✅ Closing this farm-priority post.",
        ephemeral=True,
    )

    delete_priority(thread_id)

    try:
        await asyncio.sleep(1)
        await channel.delete(reason=f"Closed by {interaction.user}")
    except discord.NotFound:
        pass


@farmpriority.error
async def farmpriority_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ Only moderators with **Manage Threads** can use this command."
    else:
        message = f"❌ Command error: `{type(error).__name__}: {error}`"

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@farmpriorityclose.error
async def farmpriorityclose_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ Only moderators with **Manage Threads** can use this command."
    else:
        message = f"❌ Command error: `{type(error).__name__}: {error}`"

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


bot.tree.add_command(farmpriority)
bot.tree.add_command(farmpriorityclose)


@tasks.loop(seconds=60)
async def cleanup_expired_posts():
    for thread_id, item in get_expired_priorities():
        try:
            channel = bot.get_channel(thread_id)
            if channel is None:
                channel = await bot.fetch_channel(thread_id)

            if isinstance(channel, discord.Thread):
                await channel.delete(reason="Farm priority expired")
                print(f"Deleted expired priority: {item} ({thread_id})")

        except discord.NotFound:
            pass
        except discord.Forbidden:
            print(f"Missing permission to delete thread {thread_id}")
            continue
        except Exception as exc:
            print(
                f"Cleanup error for {thread_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        delete_priority(thread_id)


@cleanup_expired_posts.before_loop
async def before_cleanup():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("Farm Priority Bot V2 is online.")


bot.run(TOKEN)
