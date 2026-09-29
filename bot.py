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


def load_font(size):
    fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for font in fonts:
        if os.path.exists(font):
            return ImageFont.truetype(font, size)

    return ImageFont.load_default()


def fit_font(draw, text, max_width, starting_size, minimum_size):
    size = starting_size

    while size >= minimum_size:
        font = load_font(size)
        box = draw.textbbox((0, 0), text, font=font)

        if box[2] - box[0] <= max_width:
            return font

        size -= 2

    return load_font(minimum_size)


async def get_avatar(user):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(user.display_avatar.url) as response:
                data = await response.read()

        return Image.open(io.BytesIO(data)).convert("RGBA")

    except Exception:
        return None


def make_level_card(user, level, avatar):
    WIDTH = 1600
    HEIGHT = 600

    # Dark classic background
    img = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        (18, 20, 25)
    )

    draw = ImageDraw.Draw(img)

    # Outer border
    draw.rounded_rectangle(
        (8, 8, WIDTH - 8, HEIGHT - 8),
        radius=30,
        outline=(55, 120, 255),
        width=5
    )

    # -------------------------
    # LARGE PROFILE PICTURE
    # -------------------------

    if avatar:
        avatar = avatar.resize((360, 360))

        mask = Image.new("L", (360, 360), 0)
        mask_draw = ImageDraw.Draw(mask)

        mask_draw.ellipse(
            (0, 0, 360, 360),
            fill=255
        )

        img.paste(
            avatar,
            (70, 120),
            mask
        )

        draw.ellipse(
            (70, 120, 430, 480),
            outline=(35, 125, 255),
            width=8
        )

    # -------------------------
    # USERNAME - VERY LARGE
    # -------------------------

    username = user.display_name

    username_font = fit_font(
        draw,
        username,
        1050,
        90,
        45
    )

    draw.text(
        (500, 45),
        username,
        font=username_font,
        fill=(255, 255, 255)
    )

    # -------------------------
    # CONGRATULATIONS - HUGE
    # -------------------------

    congratulations = "CONGRATULATIONS!"

    congratulations_font = fit_font(
        draw,
        congratulations,
        1050,
        92,
        52
    )

    draw.text(
        (500, 190),
        congratulations,
        font=congratulations_font,
        fill=(255, 255, 255)
    )

    # -------------------------
    # LEVEL - HUGE
    # -------------------------

    level_text = f"YOU REACHED LEVEL {level}!"

    level_font = fit_font(
        draw,
        level_text,
        1050,
        72,
        42
    )

    draw.text(
        (500, 335),
        level_text,
        font=level_font,
        fill=(55, 135, 255)
    )

    # Save
    output = io.BytesIO()

    img.save(
        output,
        format="PNG"
    )

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

    new_role = member.guild.get_role(row[0])

    if new_role is None:
        return None

    # Remove previous configured level roles
    cursor.execute(
        "SELECT role_id FROM level_roles WHERE guild_id=?",
        (member.guild.id,)
    )

    old_roles = cursor.fetchall()

    for old_role_data in old_roles:
        old_role = member.guild.get_role(old_role_data[0])

        if old_role and old_role in member.roles and old_role.id != new_role.id:
            try:
                await member.remove_roles(old_role)
            except discord.Forbidden:
                pass

    try:
        await member.add_roles(new_role)
        return new_role
    except discord.Forbidden:
        return None


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Sync error: {e}")

    print(f"Rezox is online as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is None:
        return

    guild_id = message.guild.id
    user_id = message.author.id

    now = time.time()
    cooldown_key = (guild_id, user_id)

    if cooldown_key in xp_cooldowns:
        if now - xp_cooldowns[cooldown_key] < XP_COOLDOWN:
            await bot.process_commands(message)
            return

    xp_cooldowns[cooldown_key] = now

    amount = random.randint(10, 20)

    old_level, new_level, xp, messages = add_xp(
        guild_id,
        user_id,
        amount
    )

    # LEVEL UP
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
            content = (
                f"{message.author.mention}\n"
                f"🎉 **Congratulations!**"
            )

        file = discord.File(
            card,
            filename="rezox_levelup.png"
        )

        await message.channel.send(
            content=content,
            file=file
        )

    await bot.process_commands(message)


@bot.tree.command(
    name="rank",
    description="Check your level and XP"
)
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


@bot.tree.command(
    name="leaderboard",
    description="Show the XP leaderboard"
)
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
        await interaction.response.send_message(
            "No XP data yet."
        )
        return

    text = "🏆 **REZOX LEADERBOARD**\n\n"

    for i, row in enumerate(rows, start=1):
        user_id, xp, level = row

        member = interaction.guild.get_member(user_id)

        if member:
            name = member.display_name
        else:
            name = f"User {user_id}"

        text += (
            f"**{i}. {name}** — "
            f"Level **{level}** | XP **{xp}**\n"
        )

    await interaction.response.send_message(text)


@bot.tree.command(
    name="levelcard",
    description="Show your current level card"
)
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
        filename="rezox_levelcard.png"
    )

    await interaction.followup.send(
        file=file
    )


@bot.tree.command(
    name="test",
    description="Preview a level-up card"
)
@app_commands.describe(
    level="Level to preview from 1 to 50"
)
async def test(
    interaction: discord.Interaction,
    level: int = 5
):

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
        filename="rezox_test_card.png"
    )

    await interaction.followup.send(
        content=f"🧪 **Level {level} Preview**\nXP and level were not changed.",
        file=file
    )


@bot.tree.command(
    name="daily",
    description="Claim your daily 100 XP"
)
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
                f"⏳ Daily already claimed.\n"
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

    text = "🎁 **You received +100 XP!**"

    if new_level > old_level:

        role = await give_level_role(
            interaction.user,
            new_level
        )

        text += f"\n🎉 **You reached Level {new_level}!**"

        if role:
            text += f"\n🎖️ New role: {role.mention}"

    await interaction.response.send_message(text)


@bot.tree.command(
    name="setlevelrole",
    description="Set a role for a level"
)
@app_commands.describe(
    level="Level from 1 to 50",
    role="Role to give"
)
@app_commands.checks.has_permissions(
    manage_roles=True
)
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
            "❌ My bot role must be above that role.",
            ephemeral=True
        )
        return

    cursor.execute("""
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


@bot.tree.command(
    name="removelevelrole",
    description="Remove a level role"
)
@app_commands.describe(
    level="Level from 1 to 50"
)
@app_commands.checks.has_permissions(
    manage_roles=True
)
async def removelevelrole(
    interaction: discord.Interaction,
    level: int
):

    cursor.execute("""
        DELETE FROM level_roles
        WHERE guild_id=? AND level=?
    """, (
        interaction.guild.id,
        level
    ))

    db.commit()

    await interaction.response.send_message(
        f"✅ Level **{level}** role removed."
    )


@bot.tree.command(
    name="levelroles",
    description="Show configured level roles"
)
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
            "No level roles configured."
        )
        return

    text = "🎖️ **LEVEL ROLES**\n\n"

    for level, role_id in rows:

        role = interaction.guild.get_role(role_id)

        if role:
            text += f"Level **{level}** → {role.mention}\n"

    await interaction.response.send_message(text)


@bot.tree.command(
    name="help",
    description="Show Rezox commands"
)
async def help_command(interaction: discord.Interaction):

    text = """
🤖 **REZOX COMMANDS**

📊 **LEVELING**
`/rank` — Check level and XP
`/leaderboard` — Server leaderboard
`/levelcard` — Your current card
`/test` — Preview level-up card
`/daily` — Claim +100 XP

🎖️ **LEVEL ROLES**
`/setlevelrole` — Set level role
`/removelevelrole` — Remove level role
`/levelroles` — View level roles

✨ Levels: **1–50**
⚡ XP cooldown: **60 seconds**
"""

    await interaction.response.send_message(text)


@setlevelrole.error
async def setlevelrole_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):
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
