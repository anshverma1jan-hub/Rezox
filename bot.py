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

# =========================================================
# DISCORD
# =========================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================================================
# DATABASE
# =========================================================

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


# =========================================================
# XP SYSTEM
# =========================================================

def xp_needed(level):
    return 100 + (level * 75)


def get_user(guild_id, user_id):
    cursor.execute(
        """
        SELECT xp, level, messages
        FROM users
        WHERE guild_id=? AND user_id=?
        """,
        (guild_id, user_id)
    )

    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            """
            INSERT INTO users
            (guild_id, user_id, xp, level, messages)
            VALUES (?, ?, 0, 1, 0)
            """,
            (guild_id, user_id)
        )

        db.commit()

        return 0, 1, 0

    return row


def add_xp(guild_id, user_id, amount):
    xp, level, messages = get_user(
        guild_id,
        user_id
    )

    old_level = level

    xp += amount
    messages += 1

    while level < MAX_LEVEL:
        required = xp_needed(level)

        if xp < required:
            break

        xp -= required
        level += 1

    cursor.execute(
        """
        UPDATE users
        SET xp=?, level=?, messages=?
        WHERE guild_id=? AND user_id=?
        """,
        (
            xp,
            level,
            messages,
            guild_id,
            user_id
        )
    )

    db.commit()

    return old_level, level, xp, messages


# =========================================================
# FONTS
# =========================================================

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"

if not os.path.exists(FONT_PATH):
    FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size):
    return ImageFont.truetype(
        FONT_PATH,
        size
    )


# =========================================================
# AVATAR
# =========================================================

async def get_avatar(user):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                user.display_avatar.url
            ) as response:

                data = await response.read()

        return Image.open(
            io.BytesIO(data)
        ).convert("RGBA")

    except Exception:
        return None


# =========================================================
# LEVEL CARD
# =========================================================

def make_level_card(user, level, avatar):

    # BIG CARD
    WIDTH = 1600
    HEIGHT = 700

    background = (14, 16, 21)
    white = (255, 255, 255)
    blue = (45, 130, 255)
    border = (35, 100, 210)

    img = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        background
    )

    draw = ImageDraw.Draw(img)

    # -----------------------------------------------------
    # OUTER BORDER
    # -----------------------------------------------------

    draw.rounded_rectangle(
        (8, 8, WIDTH - 8, HEIGHT - 8),
        radius=32,
        outline=border,
        width=6
    )

    # -----------------------------------------------------
    # LARGE AVATAR
    # -----------------------------------------------------

    avatar_size = 390
    avatar_x = 65
    avatar_y = 155

    if avatar:

        avatar = avatar.resize(
            (avatar_size, avatar_size),
            Image.Resampling.LANCZOS
        )

        mask = Image.new(
            "L",
            (avatar_size, avatar_size),
            0
        )

        mask_draw = ImageDraw.Draw(mask)

        mask_draw.ellipse(
            (0, 0, avatar_size, avatar_size),
            fill=255
        )

        img.paste(
            avatar,
            (avatar_x, avatar_y),
            mask
        )

        draw.ellipse(
            (
                avatar_x,
                avatar_y,
                avatar_x + avatar_size,
                avatar_y + avatar_size
            ),
            outline=blue,
            width=9
        )

    # -----------------------------------------------------
    # USERNAME
    # -----------------------------------------------------

    username = user.display_name

    username_font = font(100)

    # Username is allowed to be slightly smaller only if
    # the actual username is extremely long.
    username_size = 100

    while (
        draw.textbbox(
            (0, 0),
            username,
            font=username_font
        )[2] > 1010
        and username_size > 60
    ):
        username_size -= 4
        username_font = font(username_size)

    draw.text(
        (510, 45),
        username,
        font=username_font,
        fill=white
    )

    # -----------------------------------------------------
    # HUGE CONGRATULATIONS
    # -----------------------------------------------------

    congratulations_font = font(125)

    draw.text(
        (510, 205),
        "CONGRATULATIONS!",
        font=congratulations_font,
        fill=white
    )

    # -----------------------------------------------------
    # HUGE LEVEL TEXT
    # -----------------------------------------------------

    level_font = font(105)

    level_text = f"YOU REACHED LEVEL {level}!"

    draw.text(
        (510, 395),
        level_text,
        font=level_font,
        fill=blue
    )

    # -----------------------------------------------------
    # SAVE IMAGE
    # -----------------------------------------------------

    output = io.BytesIO()

    img.save(
        output,
        format="PNG"
    )

    output.seek(0)

    return output


# =========================================================
# LEVEL ROLE
# =========================================================

async def give_level_role(member, level):

    cursor.execute(
        """
        SELECT role_id
        FROM level_roles
        WHERE guild_id=? AND level=?
        """,
        (
            member.guild.id,
            level
        )
    )

    row = cursor.fetchone()

    if row is None:
        return None

    new_role = member.guild.get_role(
        row[0]
    )

    if new_role is None:
        return None

    # Remove old configured level roles
    cursor.execute(
        """
        SELECT role_id
        FROM level_roles
        WHERE guild_id=?
        """,
        (member.guild.id,)
    )

    old_roles = cursor.fetchall()

    for role_data in old_roles:

        old_role = member.guild.get_role(
            role_data[0]
        )

        if (
            old_role
            and old_role in member.roles
            and old_role.id != new_role.id
        ):

            try:
                await member.remove_roles(
                    old_role
                )

            except discord.Forbidden:
                pass

    # Give new role
    try:

        await member.add_roles(
            new_role
        )

        return new_role

    except discord.Forbidden:
        return None


# =========================================================
# BOT READY
# =========================================================

@bot.event
async def on_ready():

    try:

        synced = await bot.tree.sync()

        print(
            f"Synced {len(synced)} slash commands."
        )

    except Exception as error:

        print(
            f"Slash command error: {error}"
        )

    print(
        f"Rezox is online as {bot.user}"
    )


# =========================================================
# MESSAGE XP
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if message.guild is None:
        return

    guild_id = message.guild.id
    user_id = message.author.id

    now = time.time()

    cooldown_key = (
        guild_id,
        user_id
    )

    # 60 second XP cooldown
    if cooldown_key in xp_cooldowns:

        if (
            now - xp_cooldowns[cooldown_key]
            < XP_COOLDOWN
        ):

            await bot.process_commands(
                message
            )

            return

    xp_cooldowns[cooldown_key] = now

    earned_xp = random.randint(
        10,
        20
    )

    old_level, new_level, xp, messages = add_xp(
        guild_id,
        user_id,
        earned_xp
    )

    # =====================================================
    # LEVEL UP
    # =====================================================

    if new_level > old_level:

        avatar = await get_avatar(
            message.author
        )

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
                f"🎉 **Congratulations! You got a new role "
                f"{role.mention}**"
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

    await bot.process_commands(
        message
    )


# =========================================================
# /RANK
# =========================================================

@bot.tree.command(
    name="rank",
    description="Check your level and XP"
)
async def rank(interaction):

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


# =========================================================
# /LEADERBOARD
# =========================================================

@bot.tree.command(
    name="leaderboard",
    description="Show the server leaderboard"
)
async def leaderboard(interaction):

    cursor.execute(
        """
        SELECT user_id, xp, level
        FROM users
        WHERE guild_id=?
        ORDER BY level DESC, xp DESC
        LIMIT 10
        """,
        (interaction.guild.id,)
    )

    rows = cursor.fetchall()

    if not rows:

        await interaction.response.send_message(
            "No XP data yet."
        )

        return

    text = "🏆 **REZOX LEADERBOARD**\n\n"

    for position, row in enumerate(
        rows,
        start=1
    ):

        user_id, xp, level = row

        member = interaction.guild.get_member(
            user_id
        )

        if member:
            name = member.display_name
        else:
            name = f"User {user_id}"

        text += (
            f"**{position}. {name}** — "
            f"Level **{level}** | XP **{xp}**\n"
        )

    await interaction.response.send_message(
        text
    )


# =========================================================
# /LEVELCARD
# =========================================================

@bot.tree.command(
    name="levelcard",
    description="Show your current level card"
)
async def levelcard(interaction):

    xp, level, messages = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    await interaction.response.defer()

    avatar = await get_avatar(
        interaction.user
    )

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


# =========================================================
# /TEST
# =========================================================

@bot.tree.command(
    name="test",
    description="Preview a level-up card"
)
@app_commands.describe(
    level="Level to preview from 1 to 50"
)
async def test(
    interaction,
    level: int = 5
):

    if level < 1 or level > 50:

        await interaction.response.send_message(
            "❌ Level must be between **1 and 50**.",
            ephemeral=True
        )

        return

    await interaction.response.defer()

    avatar = await get_avatar(
        interaction.user
    )

    card = make_level_card(
        interaction.user,
        level,
        avatar
    )

    file = discord.File(
        card,
        filename="rezox_test.png"
    )

    await interaction.followup.send(
        content=(
            f"🧪 **Level {level} Preview**\n"
            f"XP and level were not changed."
        ),
        file=file
    )


# =========================================================
# /DAILY
# =========================================================

@bot.tree.command(
    name="daily",
    description="Claim your daily 100 XP"
)
async def daily(interaction):

    guild_id = interaction.guild.id
    user_id = interaction.user.id

    now = time.time()

    cursor.execute(
        """
        SELECT last_claim
        FROM daily_claims
        WHERE guild_id=? AND user_id=?
        """,
        (
            guild_id,
            user_id
        )
    )

    row = cursor.fetchone()

    if row:

        remaining = 86400 - (
            now - row[0]
        )

        if remaining > 0:

            hours = int(
                remaining // 3600
            )

            minutes = int(
                (remaining % 3600) // 60
            )

            await interaction.response.send_message(
                f"⏳ Daily already claimed.\n"
                f"Come back in **{hours}h {minutes}m**."
            )

            return

        cursor.execute(
            """
            UPDATE daily_claims
            SET last_claim=?
            WHERE guild_id=? AND user_id=?
            """,
            (
                now,
                guild_id,
                user_id
            )
        )

    else:

        cursor.execute(
            """
            INSERT INTO daily_claims
            (guild_id, user_id, last_claim)
            VALUES (?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                now
            )
        )

    db.commit()

    old_level, new_level, xp, messages = add_xp(
        guild_id,
        user_id,
        DAILY_XP
    )

    response = (
        "🎁 **You received +100 XP!**"
    )

    if new_level > old_level:

        role = await give_level_role(
            interaction.user,
            new_level
        )

        response += (
            f"\n🎉 **You reached Level {new_level}!**"
        )

        if role:

            response += (
                f"\n🎖️ New role: {role.mention}"
            )

    await interaction.response.send_message(
        response
    )


# =========================================================
# /SETLEVELROLE
# =========================================================

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
    interaction,
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

    cursor.execute(
        """
        INSERT OR REPLACE INTO level_roles
        (guild_id, level, role_id)
        VALUES (?, ?, ?)
        """,
        (
            interaction.guild.id,
            level,
            role.id
        )
    )

    db.commit()

    await interaction.response.send_message(
        f"✅ Level **{level}** → {role.mention}"
    )


# =========================================================
# /REMOVELEVELROLE
# =========================================================

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
    interaction,
    level: int
):

    cursor.execute(
        """
        DELETE FROM level_roles
        WHERE guild_id=? AND level=?
        """,
        (
            interaction.guild.id,
            level
        )
    )

    db.commit()

    await interaction.response.send_message(
        f"✅ Level **{level}** role removed."
    )


# =========================================================
# /LEVELROLES
# =========================================================

@bot.tree.command(
    name="levelroles",
    description="Show all level roles"
)
async def levelroles(interaction):

    cursor.execute(
        """
        SELECT level, role_id
        FROM level_roles
        WHERE guild_id=?
        ORDER BY level ASC
        """,
        (interaction.guild.id,)
    )

    rows = cursor.fetchall()

    if not rows:

        await interaction.response.send_message(
            "No level roles configured."
        )

        return

    text = "🎖️ **LEVEL ROLES**\n\n"

    for level, role_id in rows:

        role = interaction.guild.get_role(
            role_id
        )

        if role:

            text += (
                f"Level **{level}** → "
                f"{role.mention}\n"
            )

    await interaction.response.send_message(
        text
    )


# =========================================================
# /HELP
# =========================================================

@bot.tree.command(
    name="help",
    description="Show Rezox commands"
)
async def help_command(interaction):

    text = """
🤖 **REZOX COMMANDS**

📊 **LEVELING**
`/rank` — Check level and XP
`/leaderboard` — Server leaderboard
`/levelcard` — Show your card
`/test` — Preview level-up card
`/daily` — Claim +100 XP

🎖️ **LEVEL ROLES**
`/setlevelrole` — Set level role
`/removelevelrole` — Remove level role
`/levelroles` — View level roles

✨ Levels: **1–50**
⚡ XP cooldown: **60 seconds**
"""

    await interaction.response.send_message(
        text
    )


# =========================================================
# PERMISSION ERROR
# =========================================================

@setlevelrole.error
async def setlevelrole_error(
    interaction,
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


# =========================================================
# START
# =========================================================

bot.run(TOKEN)
