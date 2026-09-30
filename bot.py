import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
import sqlite3
import io
import time
import aiohttp
import os

TOKEN = os.getenv("DISCORD_TOKEN")

XP_PER_MESSAGE = 10
XP_COOLDOWN = 60
DAILY_XP = 100
DAILY_COOLDOWN = 86400
MAX_LEVEL = 50

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

db = sqlite3.connect("rezox.db")
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    guild_id INTEGER,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    messages INTEGER DEFAULT 0,
    last_xp REAL DEFAULT 0,
    last_daily REAL DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER,
    level INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, level)
)
""")

db.commit()

last_xp_time = {}


def xp_needed(level):
    return level * 100


def get_user(guild_id, user_id):
    cur.execute(
        "SELECT xp, level, messages, last_xp, last_daily FROM users WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    )
    row = cur.fetchone()

    if row is None:
        cur.execute(
            "INSERT INTO users (user_id, guild_id) VALUES (?, ?)",
            (user_id, guild_id)
        )
        db.commit()
        return 0, 1, 0, 0, 0

    return row


def set_user(guild_id, user_id, xp, level, messages, last_xp, last_daily):
    cur.execute("""
        UPDATE users
        SET xp=?, level=?, messages=?, last_xp=?, last_daily=?
        WHERE guild_id=? AND user_id=?
    """, (xp, level, messages, last_xp, last_daily, guild_id, user_id))

    db.commit()


def get_font(size, bold=True):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


async def get_avatar(member):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(member.display_avatar.url)) as response:
                data = await response.read()

        avatar = Image.open(io.BytesIO(data)).convert("RGBA")
        return avatar

    except Exception:
        return Image.new("RGBA", (400, 400), (45, 48, 55, 255))


def fit_font(text, max_size, min_size, max_width):
    size = max_size

    while size > min_size:
        font = get_font(size)
        box = font.getbbox(text)
        width = box[2] - box[0]

        if width <= max_width:
            return font

        size -= 2

    return get_font(min_size)


async def create_level_card(member, level):
    WIDTH = 1800
    HEIGHT = 600

    image = Image.new("RGB", (WIDTH, HEIGHT), (12, 14, 18))
    draw = ImageDraw.Draw(image)

    # Clean blue border
    draw.rounded_rectangle(
        (8, 8, WIDTH - 8, HEIGHT - 8),
        radius=35,
        outline=(55, 145, 255),
        width=5
    )

    # Very subtle background
    draw.rounded_rectangle(
        (25, 25, WIDTH - 25, HEIGHT - 25),
        radius=30,
        fill=(18, 21, 27)
    )

    # -------------------------
    # AVATAR
    # -------------------------

    avatar = await get_avatar(member)

    avatar_size = 350
    avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse(
        (0, 0, avatar_size, avatar_size),
        fill=255
    )

    avatar_x = 55
    avatar_y = 125

    image.paste(
        avatar,
        (avatar_x, avatar_y),
        mask
    )

    # Avatar border
    draw.ellipse(
        (
            avatar_x - 7,
            avatar_y - 7,
            avatar_x + avatar_size + 7,
            avatar_y + avatar_size + 7
        ),
        outline=(65, 155, 255),
        width=7
    )

    # -------------------------
    # TEXT AREA
    # -------------------------

    text_x = 470
    text_width = 1270

    username = member.display_name

    username_font = fit_font(
        username,
        105,
        70,
        text_width
    )

    congratulations_font = fit_font(
        "CONGRATULATIONS!",
        145,
        125,
        text_width
    )

    level_text = f"YOU REACHED LEVEL {level}!"

    level_font = fit_font(
        level_text,
        125,
        105,
        text_width
    )

    # Username
    draw.text(
        (text_x, 38),
        username,
        font=username_font,
        fill=(235, 238, 245)
    )

    # HUGE congratulations
    draw.text(
        (text_x, 150),
        "CONGRATULATIONS!",
        font=congratulations_font,
        fill=(255, 255, 255)
    )

    # HUGE level text
    draw.text(
        (text_x, 330),
        level_text,
        font=level_font,
        fill=(75, 160, 255)
    )

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)

    return output


async def send_level_up(member, level, role=None):
    card = await create_level_card(member, level)

    text = f"🎉 Congratulations! You got a new role {role.mention}" if role else ""

    file = discord.File(
        card,
        filename="rezox-levelup.png"
    )

    try:
        await member.guild.system_channel.send(
            content=text,
            file=file
        )
    except Exception:
        for channel in member.guild.text_channels:
            if channel.permissions_for(member.guild.me).send_messages:
                try:
                    await channel.send(
                        content=text,
                        file=file
                    )
                    break
                except Exception:
                    continue


async def apply_level_role(member, level):
    cur.execute(
        "SELECT role_id FROM level_roles WHERE guild_id=? AND level=?",
        (member.guild.id, level)
    )

    row = cur.fetchone()

    if not row:
        return None

    role = member.guild.get_role(row[0])

    if role is None:
        return None

    try:
        await member.add_roles(role, reason="Rezox level reward")
    except Exception:
        return None

    # Remove older configured level roles
    cur.execute(
        "SELECT role_id FROM level_roles WHERE guild_id=? AND level<?",
        (member.guild.id, level)
    )

    old_roles = cur.fetchall()

    for old in old_roles:
        old_role = member.guild.get_role(old[0])

        if old_role and old_role in member.roles:
            try:
                await member.remove_roles(
                    old_role,
                    reason="Rezox level progression"
                )
            except Exception:
                pass

    return role


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print("Slash command sync error:", e)

    print(f"Rezox is online as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is None:
        return

    guild_id = message.guild.id
    user_id = message.author.id

    xp, level, messages, last_xp, last_daily = get_user(
        guild_id,
        user_id
    )

    messages += 1

    now = time.time()

    if now - last_xp >= XP_COOLDOWN:

        last_xp = now
        xp += XP_PER_MESSAGE

        old_level = level

        while level < MAX_LEVEL and xp >= xp_needed(level):
            xp -= xp_needed(level)
            level += 1

        set_user(
            guild_id,
            user_id,
            xp,
            level,
            messages,
            last_xp,
            last_daily
        )

        if level > old_level:

            for new_level in range(old_level + 1, level + 1):
                role = await apply_level_role(
                    message.author,
                    new_level
                )

                await send_level_up(
                    message.author,
                    new_level,
                    role
                )

    else:
        set_user(
            guild_id,
            user_id,
            xp,
            level,
            messages,
            last_xp,
            last_daily
        )

    await bot.process_commands(message)


@bot.tree.command(name="rank", description="Check your current level and XP")
async def rank(interaction: discord.Interaction):

    xp, level, messages, last_xp, last_daily = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    needed = xp_needed(level) if level < MAX_LEVEL else 0

    embed = discord.Embed(
        title="📊 Your Rezox Rank",
        color=discord.Color.blue()
    )

    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    embed.add_field(
        name="Level",
        value=f"**{level}**",
        inline=True
    )

    embed.add_field(
        name="XP",
        value=f"**{xp}/{needed}**" if level < MAX_LEVEL else "**MAX LEVEL**",
        inline=True
    )

    embed.add_field(
        name="Messages",
        value=f"**{messages}**",
        inline=True
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Show the server XP leaderboard")
async def leaderboard(interaction: discord.Interaction):

    cur.execute("""
        SELECT user_id, level, xp
        FROM users
        WHERE guild_id=?
        ORDER BY level DESC, xp DESC
        LIMIT 10
    """, (interaction.guild.id,))

    rows = cur.fetchall()

    if not rows:
        await interaction.response.send_message(
            "No leaderboard data yet."
        )
        return

    description = ""

    for index, row in enumerate(rows, start=1):
        user_id, level, xp = row
        member = interaction.guild.get_member(user_id)

        name = member.display_name if member else f"User {user_id}"

        description += (
            f"**{index}. {name}** — "
            f"Level **{level}** • **{xp} XP**\n"
        )

    embed = discord.Embed(
        title="🏆 Rezox Leaderboard",
        description=description,
        color=discord.Color.blue()
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setlevelrole", description="Set a role for a level")
@app_commands.describe(
    level="Level from 1 to 50",
    role="Role to give at that level"
)
@app_commands.checks.has_permissions(manage_roles=True)
async def setlevelrole(
    interaction: discord.Interaction,
    level: app_commands.Range[int, 1, 50],
    role: discord.Role
):

    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "❌ My bot role must be higher than that role.",
            ephemeral=True
        )
        return

    cur.execute("""
        INSERT OR REPLACE INTO level_roles
        (guild_id, level, role_id)
        VALUES (?, ?, ?)
    """, (
        interaction.guild.id,
        level,
        role.id
    ))

    db.commit()

    await interaction.response.send_message(
        f"✅ Level **{level}** → {role.mention}"
    )


@bot.tree.command(name="removelevelrole", description="Remove a level role")
@app_commands.describe(level="Level from 1 to 50")
@app_commands.checks.has_permissions(manage_roles=True)
async def removelevelrole(
    interaction: discord.Interaction,
    level: app_commands.Range[int, 1, 50]
):

    cur.execute(
        "DELETE FROM level_roles WHERE guild_id=? AND level=?",
        (interaction.guild.id, level)
    )

    db.commit()

    await interaction.response.send_message(
        f"✅ Level **{level}** role removed."
    )


@bot.tree.command(name="levelroles", description="Show configured level roles")
async def levelroles(interaction: discord.Interaction):

    cur.execute("""
        SELECT level, role_id
        FROM level_roles
        WHERE guild_id=?
        ORDER BY level ASC
    """, (interaction.guild.id,))

    rows = cur.fetchall()

    if not rows:
        await interaction.response.send_message(
            "No level roles have been configured."
        )
        return

    text = ""

    for level, role_id in rows:
        role = interaction.guild.get_role(role_id)

        if role:
            text += f"**Level {level}** → {role.mention}\n"
        else:
            text += f"**Level {level}** → Deleted role\n"

    embed = discord.Embed(
        title="🎖️ Level Roles",
        description=text,
        color=discord.Color.blue()
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="levelcard", description="Show your current level card")
async def levelcard(interaction: discord.Interaction):

    await interaction.response.defer()

    xp, level, messages, last_xp, last_daily = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    card = await create_level_card(
        interaction.user,
        level
    )

    file = discord.File(
        card,
        filename="rezox-level.png"
    )

    await interaction.followup.send(file=file)


@bot.tree.command(name="test", description="Preview a level-up card")
@app_commands.describe(level="Preview level from 1 to 50")
async def test(
    interaction: discord.Interaction,
    level: app_commands.Range[int, 1, 50] = 5
):

    await interaction.response.defer()

    card = await create_level_card(
        interaction.user,
        level
    )

    file = discord.File(
        card,
        filename="rezox-test-levelup.png"
    )

    await interaction.followup.send(
        content="🧪 Level-up card preview",
        file=file
    )


@bot.tree.command(name="daily", description="Claim your daily XP")
async def daily(interaction: discord.Interaction):

    guild_id = interaction.guild.id
    user_id = interaction.user.id

    xp, level, messages, last_xp, last_daily = get_user(
        guild_id,
        user_id
    )

    now = time.time()

    remaining = DAILY_COOLDOWN - (now - last_daily)

    if remaining > 0:

        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)

        await interaction.response.send_message(
            f"⏳ You can claim your daily XP again in "
            f"**{hours}h {minutes}m**."
        )
        return

    xp += DAILY_XP
    last_daily = now

    old_level = level

    while level < MAX_LEVEL and xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1

    set_user(
        guild_id,
        user_id,
        xp,
        level,
        messages,
        last_xp,
        last_daily
    )

    await interaction.response.send_message(
        f"🎁 You claimed **+{DAILY_XP} XP**!"
    )

    if level > old_level:

        for new_level in range(old_level + 1, level + 1):

            role = await apply_level_role(
                interaction.user,
                new_level
            )

            await send_level_up(
                interaction.user,
                new_level,
                role
            )


@bot.tree.command(name="help", description="Show Rezox commands")
async def help_command(interaction: discord.Interaction):

    embed = discord.Embed(
        title="🤖 Rezox Commands",
        description=(
            "`/rank` — Check your level and XP\n"
            "`/leaderboard` — Server leaderboard\n"
            "`/levelcard` — Show your level card\n"
            "`/test` — Preview level-up card\n"
            "`/daily` — Claim +100 XP daily\n"
            "`/setlevelrole` — Set automatic level role\n"
            "`/removelevelrole` — Remove level role\n"
            "`/levelroles` — View level roles\n"
            "`/help` — Show this menu"
        ),
        color=discord.Color.blue()
    )

    await interaction.response.send_message(embed=embed)


@setlevelrole.error
async def setlevelrole_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need **Manage Roles** permission.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ Something went wrong.",
            ephemeral=True
        )


bot.run(TOKEN)
