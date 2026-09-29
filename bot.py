import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
import sqlite3
import aiohttp
import io
import os
import time
import random

TOKEN = os.getenv("DISCORD_TOKEN")

MAX_LEVEL = 50
XP_COOLDOWN = 60
DAILY_XP = 100

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

db = sqlite3.connect("rezox.db")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    guild_id INTEGER,
    user_id INTEGER,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    messages INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER,
    level INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, level)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_claims (
    guild_id INTEGER,
    user_id INTEGER,
    last_claim REAL,
    PRIMARY KEY (guild_id, user_id)
)
""")

db.commit()

xp_cooldowns = {}


def xp_needed(level):
    return 100 + (level * 75)


def get_user(guild_id, user_id):
    cursor.execute(
        "SELECT xp, level, messages FROM users WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    )
    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            "INSERT INTO users (guild_id, user_id, xp, level, messages) VALUES (?, ?, 0, 1, 0)",
            (guild_id, user_id)
        )
        db.commit()
        return 0, 1, 0

    return row


def add_xp(guild_id, user_id, amount):
    xp, level, messages = get_user(guild_id, user_id)

    xp += amount
    messages += 1

    old_level = level

    while level < MAX_LEVEL and xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1

    cursor.execute("""
        UPDATE users
        SET xp=?, level=?, messages=?
        WHERE guild_id=? AND user_id=?
    """, (xp, level, messages, guild_id, user_id))

    db.commit()

    return old_level, level, xp, messages


async def get_avatar(user):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(user.display_avatar.url) as response:
                data = await response.read()

        avatar = Image.open(io.BytesIO(data)).convert("RGBA")
        return avatar

    except Exception:
        return None


def load_font(size, bold=True):
    possible_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in possible_fonts:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def fit_font(draw, text, max_width, start_size, minimum_size=20):
    size = start_size

    while size > minimum_size:
        font = load_font(size)
        box = draw.textbbox((0, 0), text, font=font)

        if box[2] - box[0] <= max_width:
            return font

        size -= 2

    return load_font(minimum_size)


def make_level_card(user, level, avatar):
    WIDTH = 1500
    HEIGHT = 560

    img = Image.new("RGB", (WIDTH, HEIGHT), (24, 25, 29))
    draw = ImageDraw.Draw(img)

    # Simple classic border
    draw.rounded_rectangle(
        (8, 8, WIDTH - 8, HEIGHT - 8),
        radius=28,
        outline=(75, 75, 82),
        width=4
    )

    # Avatar
    if avatar:
        avatar = avatar.resize((290, 290))

        mask = Image.new("L", (290, 290), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 290, 290), fill=255)

        img.paste(avatar, (75, 135), mask)

        draw.ellipse(
            (75, 135, 365, 425),
            outline=(255, 255, 255),
            width=5
        )

    # Username
    username = user.display_name

    username_font = fit_font(
        draw,
        username,
        980,
        78,
        42
    )

    draw.text(
        (420, 55),
        username,
        font=username_font,
        fill=(255, 255, 255)
    )

    # CONGRATULATIONS
    congratulations = "CONGRATULATIONS!"

    congrats_font = fit_font(
        draw,
        congratulations,
        980,
        76,
        44
    )

    draw.text(
        (420, 175),
        congratulations,
        font=congrats_font,
        fill=(255, 255, 255)
    )

    # LEVEL TEXT
    level_text = f"YOU REACHED LEVEL {level}!"

    level_font = fit_font(
        draw,
        level_text,
        980,
        66,
        38
    )

    draw.text(
        (420, 295),
        level_text,
        font=level_font,
        fill=(255, 255, 255)
    )

    # Small clean bottom line
    bottom_font = load_font(30)

    draw.text(
        (420, 415),
        "Keep going!",
        font=bottom_font,
        fill=(180, 180, 185)
    )

    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)

    return output


async def give_level_role(member, level):
    cursor.execute(
        "SELECT role_id FROM level_roles WHERE guild_id=? AND level=?",
        (member.guild.id, level)
    )

    row = cursor.fetchone()

    if row is None:
        return None

    role = member.guild.get_role(row[0])

    if role is None:
        return None

    # Remove previous configured level roles
    cursor.execute(
        "SELECT role_id FROM level_roles WHERE guild_id=?",
        (member.guild.id,)
    )

    all_roles = cursor.fetchall()

    for role_row in all_roles:
        old_role = member.guild.get_role(role_row[0])

        if old_role and old_role in member.roles and old_role.id != role.id:
            try:
                await member.remove_roles(old_role)
            except discord.Forbidden:
                pass

    try:
        await member.add_roles(role)
        return role
    except discord.Forbidden:
        return None


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print("Slash command sync error:", e)

    print(f"Rezox is online as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is None:
        return

    user_id = message.author.id
    guild_id = message.guild.id

    now = time.time()
    key = (guild_id, user_id)

    if key in xp_cooldowns:
        if now - xp_cooldowns[key] < XP_COOLDOWN:
            await bot.process_commands(message)
            return

    xp_cooldowns[key] = now

    amount = random.randint(10, 20)

    old_level, new_level, xp, messages = add_xp(
        guild_id,
        user_id,
        amount
    )

    if new_level > old_level:
        avatar = await get_avatar(message.author)

        card = make_level_card(
            message.author,
            new_level,
            avatar
        )

        role = await give_level_role(
            message.author,
            new_level
        )

        if role:
            content = (
                f"{message.author.mention}\n"
                f"🎉 **Congratulations! You got a new role {role.mention}**"
            )
        else:
            content = f"{message.author.mention}\n🎉 **Congratulations!**"

        file = discord.File(
            card,
            filename="levelup.png"
        )

        await message.channel.send(
            content=content,
            file=file
        )

    await bot.process_commands(message)


@bot.tree.command(name="rank", description="Check your current level and XP")
async def rank(interaction: discord.Interaction):
    xp, level, messages = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    await interaction.response.send_message(
        f"🏆 **{interaction.user.display_name}**\n"
        f"Level: **{level}**\n"
        f"XP: **{xp}/{xp_needed(level)}**\n"
        f"Messages: **{messages}**"
    )


@bot.tree.command(name="leaderboard", description="Show the server XP leaderboard")
async def leaderboard(interaction: discord.Interaction):
    cursor.execute("""
        SELECT user_id, xp, level
        FROM users
        WHERE guild_id=?
        ORDER BY level DESC, xp DESC
        LIMIT 10
    """, (interaction.guild.id,))

    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No XP data yet.")
        return

    text = "🏆 **REZOX LEADERBOARD**\n\n"

    for i, (user_id, xp, level) in enumerate(rows, start=1):
        member = interaction.guild.get_member(user_id)

        if member:
            name = member.display_name
        else:
            name = f"User {user_id}"

        text += f"**{i}. {name}** — Level **{level}** | XP **{xp}**\n"

    await interaction.response.send_message(text)


@bot.tree.command(name="levelcard", description="Show your current level card")
async def levelcard(interaction: discord.Interaction):
    xp, level, messages = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    await interaction.response.defer()

    avatar = await get_avatar(interaction.user)

    card = make_level_card(
        interaction.user,
        level,
        avatar
    )

    file = discord.File(
        card,
        filename="levelcard.png"
    )

    await interaction.followup.send(
        file=file
    )


@bot.tree.command(name="test", description="Preview a level-up card without changing XP")
@app_commands.describe(level="Level to preview, from 1 to 50")
async def test(interaction: discord.Interaction, level: int = 5):
    if level < 1 or level > 50:
        await interaction.response.send_message(
            "❌ Level must be between **1 and 50**.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    avatar = await get_avatar(interaction.user)

    card = make_level_card(
        interaction.user,
        level,
        avatar
    )

    file = discord.File(
        card,
        filename="test_levelup.png"
    )

    await interaction.followup.send(
        content=f"🧪 **Level {level} Card Preview**\nXP and level were not changed.",
        file=file
    )


@bot.tree.command(name="daily", description="Claim your daily 100 XP")
async def daily(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    user_id = interaction.user.id
    now = time.time()

    cursor.execute(
        "SELECT last_claim FROM daily_claims WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    )

    row = cursor.fetchone()

    if row:
        remaining = 86400 - (now - row[0])

        if remaining > 0:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)

            await interaction.response.send_message(
                f"⏳ You already claimed your daily XP.\n"
                f"Come back in **{hours}h {minutes}m**."
            )
            return

        cursor.execute("""
            UPDATE daily_claims
            SET last_claim=?
            WHERE guild_id=? AND user_id=?
        """, (now, guild_id, user_id))

    else:
        cursor.execute("""
            INSERT INTO daily_claims
            (guild_id, user_id, last_claim)
            VALUES (?, ?, ?)
        """, (guild_id, user_id, now))

    db.commit()

    old_level, new_level, xp, messages = add_xp(
        guild_id,
        user_id,
        DAILY_XP
    )

    message = "🎁 **You received +100 XP!**"

    if new_level > old_level:
        role = await give_level_role(
            interaction.user,
            new_level
        )

        message += f"\n🎉 **You reached Level {new_level}!**"

        if role:
            message += f"\n🎖️ New role: {role.mention}"

    await interaction.response.send_message(message)


@bot.tree.command(name="setlevelrole", description="Set a role for a specific level")
@app_commands.describe(
    level="Level from 1 to 50",
    role="Role to give at that level"
)
@app_commands.checks.has_permissions(manage_roles=True)
async def setlevelrole(
    interaction: discord.Interaction,
    level: int,
    role: discord.Role
):
    if level < 1 or level > 50:
        await interaction.response.send_message(
            "❌ Level must be between **1 and 50**.",
            ephemeral=True
        )
        return

    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "❌ My bot role must be **above** that role.",
            ephemeral=True
        )
        return

    cursor.execute("""
        INSERT OR REPLACE INTO level_roles
        (guild_id, level, role_id)
        VALUES (?, ?, ?)
    """, (interaction.guild.id, level, role.id))

    db.commit()

    await interaction.response.send_message(
        f"✅ Level **{level}** will now give {role.mention}"
    )


@bot.tree.command(name="removelevelrole", description="Remove a level role")
@app_commands.describe(level="Level from 1 to 50")
@app_commands.checks.has_permissions(manage_roles=True)
async def removelevelrole(
    interaction: discord.Interaction,
    level: int
):
    cursor.execute("""
        DELETE FROM level_roles
        WHERE guild_id=? AND level=?
    """, (interaction.guild.id, level))

    db.commit()

    await interaction.response.send_message(
        f"✅ Level **{level}** role removed."
    )


@bot.tree.command(name="levelroles", description="Show all configured level roles")
async def levelroles(interaction: discord.Interaction):
    cursor.execute("""
        SELECT level, role_id
        FROM level_roles
        WHERE guild_id=?
        ORDER BY level ASC
    """, (interaction.guild.id,))

    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message(
            "No level roles are configured yet."
        )
        return

    text = "🎖️ **LEVEL ROLES**\n\n"

    for level, role_id in rows:
        role = interaction.guild.get_role(role_id)

        if role:
            text += f"Level **{level}** → {role.mention}\n"

    await interaction.response.send_message(text)


@bot.tree.command(name="help", description="Show Rezox commands")
async def help_command(interaction: discord.Interaction):
    text = """
🤖 **REZOX COMMANDS**

📊 **Leveling**
`/rank` — Check your level and XP
`/leaderboard` — Server leaderboard
`/levelcard` — Show your level card
`/test` — Preview level-up card
`/daily` — Claim +100 XP

🎖️ **Level Roles**
`/setlevelrole` — Set a level role
`/removelevelrole` — Remove a level role
`/levelroles` — View level roles

✨ **Levels:** 1–50
⚡ **XP cooldown:** 60 seconds
"""

    await interaction.response.send_message(text)


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
