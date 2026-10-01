import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sqlite3
import io
import time
import aiohttp
import os

TOKEN = os.getenv("DISCORD_TOKEN")

# =========================================================
# SETTINGS
# =========================================================

XP_PER_MESSAGE = 10
XP_COOLDOWN = 60

DAILY_XP = 100
DAILY_COOLDOWN = 86400

MAX_LEVEL = 50

# =========================================================
# DISCORD
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect("rezox.db")
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER,
    guild_id INTEGER,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    messages INTEGER DEFAULT 0,
    last_xp REAL DEFAULT 0,
    last_daily REAL DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
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

# =========================================================
# XP
# =========================================================

def xp_needed(level):
    return level * 100


def get_user(guild_id, user_id):
    cur.execute("""
        SELECT xp, level, messages, last_xp, last_daily
        FROM users
        WHERE guild_id=? AND user_id=?
    """, (guild_id, user_id))

    row = cur.fetchone()

    if row is None:
        cur.execute("""
            INSERT INTO users
            (user_id, guild_id, xp, level, messages, last_xp, last_daily)
            VALUES (?, ?, 0, 1, 0, 0, 0)
        """, (user_id, guild_id))

        db.commit()

        return 0, 1, 0, 0, 0

    return row


def save_user(
    guild_id,
    user_id,
    xp,
    level,
    messages,
    last_xp,
    last_daily
):
    cur.execute("""
        UPDATE users
        SET xp=?,
            level=?,
            messages=?,
            last_xp=?,
            last_daily=?
        WHERE guild_id=? AND user_id=?
    """, (
        xp,
        level,
        messages,
        last_xp,
        last_daily,
        guild_id,
        user_id
    ))

    db.commit()

# =========================================================
# FONT SYSTEM
# =========================================================
# IMPORTANT:
# There is NO fit_font function anywhere in this code.
# All important card fonts have fixed sizes.
# =========================================================

FONT_FILES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
]


def load_font(size):
    for path in FONT_FILES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass

    return ImageFont.load_default()


FONT_SMALL = load_font(42)
FONT_LEVEL_UP = load_font(48)
FONT_USERNAME = load_font(76)
FONT_CONGRATS = load_font(116)
FONT_LEVEL = load_font(92)
FONT_ROLE = load_font(34)
FONT_SPARKLE = load_font(32)

# =========================================================
# AVATAR
# =========================================================

async def get_avatar(member):

    try:

        async with aiohttp.ClientSession() as session:

            async with session.get(
                str(member.display_avatar.with_size(512).url)
            ) as response:

                if response.status != 200:
                    raise Exception("Avatar download failed")

                data = await response.read()

        return Image.open(
            io.BytesIO(data)
        ).convert("RGBA")

    except Exception:

        return Image.new(
            "RGBA",
            (512, 512),
            (70, 70, 80, 255)
        )

# =========================================================
# LEVEL CARD
# =========================================================

async def create_level_card(member, level, role=None):

    WIDTH = 1800
    HEIGHT = 650

    # -----------------------------------------------------
    # BACKGROUND
    # -----------------------------------------------------

    image = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (13, 15, 23, 255)
    )

    # -----------------------------------------------------
    # PURPLE GLOW
    # -----------------------------------------------------

    glow = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 0)
    )

    glow_draw = ImageDraw.Draw(glow)

    glow_draw.ellipse(
        (1050, -250, 2050, 850),
        fill=(120, 50, 210, 90)
    )

    glow_draw.ellipse(
        (-350, 250, 700, 950),
        fill=(70, 35, 150, 55)
    )

    glow = glow.filter(
        ImageFilter.GaussianBlur(100)
    )

    image = Image.alpha_composite(
        image,
        glow
    )

    draw = ImageDraw.Draw(image)

    # -----------------------------------------------------
    # BORDER
    # -----------------------------------------------------

    draw.rounded_rectangle(
        (8, 8, WIDTH - 8, HEIGHT - 8),
        radius=32,
        outline=(145, 80, 255, 255),
        width=5
    )

    # -----------------------------------------------------
    # AVATAR
    # -----------------------------------------------------

    avatar = await get_avatar(member)

    # -----------------------------------------------------
    # FADED AVATAR ON RIGHT
    # -----------------------------------------------------

    right_avatar = avatar.copy()

    right_avatar = right_avatar.resize(
        (700, 700),
        Image.Resampling.LANCZOS
    )

    right_mask = Image.new(
        "L",
        (700, 700),
        0
    )

    right_mask_draw = ImageDraw.Draw(
        right_mask
    )

    right_mask_draw.ellipse(
        (0, 0, 700, 700),
        fill=55
    )

    right_avatar.putalpha(
        right_mask
    )

    image.alpha_composite(
        right_avatar,
        (1170, -20)
    )

    # -----------------------------------------------------
    # MAIN PFP
    # -----------------------------------------------------

    avatar_size = 350

    avatar = avatar.resize(
        (avatar_size, avatar_size),
        Image.Resampling.LANCZOS
    )

    avatar_mask = Image.new(
        "L",
        (avatar_size, avatar_size),
        0
    )

    avatar_mask_draw = ImageDraw.Draw(
        avatar_mask
    )

    avatar_mask_draw.ellipse(
        (0, 0, avatar_size, avatar_size),
        fill=255
    )

    avatar_x = 55
    avatar_y = 150

    # PFP border
    draw.ellipse(
        (
            avatar_x - 15,
            avatar_y - 15,
            avatar_x + avatar_size + 15,
            avatar_y + avatar_size + 15
        ),
        fill=(125, 65, 230, 255)
    )

    image.paste(
        avatar,
        (avatar_x, avatar_y),
        avatar_mask
    )

    # -----------------------------------------------------
    # TEXT POSITION
    # -----------------------------------------------------

    text_x = 470

    # -----------------------------------------------------
    # USERNAME
    # -----------------------------------------------------
    # Only truncate very long names.
    # Font size NEVER changes.
    # -----------------------------------------------------

    username = member.display_name

    if len(username) > 24:
        username = username[:24] + "..."

    # -----------------------------------------------------
    # LEVEL UP
    # -----------------------------------------------------

    draw.text(
        (text_x, 35),
        "LEVEL UP",
        font=FONT_LEVEL_UP,
        fill=(210, 170, 255, 255)
    )

    # -----------------------------------------------------
    # USERNAME
    # -----------------------------------------------------

    draw.text(
        (text_x, 90),
        username,
        font=FONT_USERNAME,
        fill=(255, 255, 255, 255)
    )

    # -----------------------------------------------------
    # CONGRATULATIONS
    # -----------------------------------------------------

    draw.text(
        (text_x, 210),
        "CONGRATULATIONS!",
        font=FONT_CONGRATS,
        fill=(255, 255, 255, 255)
    )

    # -----------------------------------------------------
    # LEVEL
    # -----------------------------------------------------

    level_text = f"YOU REACHED LEVEL {level}!"

    draw.text(
        (text_x, 355),
        level_text,
        font=FONT_LEVEL,
        fill=(180, 105, 255, 255)
    )

    # -----------------------------------------------------
    # ROLE
    # -----------------------------------------------------

    if role:

        role_text = f"NEW ROLE: {role.name}"

        if len(role_text) > 38:
            role_text = role_text[:38] + "..."

        draw.text(
            (text_x, 515),
            role_text,
            font=FONT_ROLE,
            fill=(225, 225, 235, 255)
        )

    # -----------------------------------------------------
    # SPARKLES
    # -----------------------------------------------------

    sparkle_positions = [
        (420, 30),
        (1120, 85),
        (1090, 570),
        (1550, 60),
        (1700, 500),
        (395, 580)
    ]

    for x, y in sparkle_positions:

        draw.text(
            (x, y),
            "*",
            font=FONT_SPARKLE,
            fill=(190, 120, 255, 255)
        )

    # -----------------------------------------------------
    # SAVE PNG
    # -----------------------------------------------------

    output = io.BytesIO()

    image.convert("RGB").save(
        output,
        format="PNG",
        optimize=True
    )

    output.seek(0)

    return output

# =========================================================
# LEVEL ROLES
# =========================================================

async def apply_level_role(member, level):

    cur.execute("""
        SELECT role_id
        FROM level_roles
        WHERE guild_id=? AND level=?
    """, (
        member.guild.id,
        level
    ))

    row = cur.fetchone()

    if not row:
        return None

    role = member.guild.get_role(
        row[0]
    )

    if role is None:
        return None

    if role >= member.guild.me.top_role:
        return None

    try:

        await member.add_roles(
            role,
            reason="Rezox level reward"
        )

    except Exception:

        return None

    # Remove lower configured level roles
    cur.execute("""
        SELECT role_id
        FROM level_roles
        WHERE guild_id=? AND level<?
    """, (
        member.guild.id,
        level
    ))

    old_roles = cur.fetchall()

    for old_row in old_roles:

        old_role = member.guild.get_role(
            old_row[0]
        )

        if old_role and old_role in member.roles:

            try:

                await member.remove_roles(
                    old_role,
                    reason="Rezox level progression"
                )

            except Exception:
                pass

    return role

# =========================================================
# LEVEL UP MESSAGE
# =========================================================

async def send_level_up(
    member,
    level,
    role=None,
    channel=None
):

    card = await create_level_card(
        member,
        level,
        role
    )

    file = discord.File(
        card,
        filename="rezox-levelup.png"
    )

    content = None

    if role:

        content = (
            f"🎉 **Congratulations!** "
            f"You got a new role {role.mention}"
        )

    if channel is None:
        channel = member.guild.system_channel

    if channel is None:

        for ch in member.guild.text_channels:

            permissions = ch.permissions_for(
                member.guild.me
            )

            if permissions.send_messages:

                channel = ch
                break

    if channel:

        try:

            await channel.send(
                content=content,
                file=file
            )

        except Exception as e:

            print(
                "Level card send error:",
                e
            )

# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    try:

        synced = await bot.tree.sync()

        print(
            f"Synced {len(synced)} slash commands"
        )

    except Exception as e:

        print(
            "Slash command sync error:",
            e
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

        while (
            level < MAX_LEVEL
            and xp >= xp_needed(level)
        ):

            xp -= xp_needed(level)
            level += 1

        save_user(
            guild_id,
            user_id,
            xp,
            level,
            messages,
            last_xp,
            last_daily
        )

        if level > old_level:

            for new_level in range(
                old_level + 1,
                level + 1
            ):

                role = await apply_level_role(
                    message.author,
                    new_level
                )

                await send_level_up(
                    message.author,
                    new_level,
                    role,
                    message.channel
                )

    else:

        save_user(
            guild_id,
            user_id,
            xp,
            level,
            messages,
            last_xp,
            last_daily
        )

    await bot.process_commands(
        message
    )

# =========================================================
# /RANK
# =========================================================

@bot.tree.command(
    name="rank",
    description="Check your current level and XP"
)
async def rank(interaction: discord.Interaction):

    xp, level, messages, last_xp, last_daily = get_user(
        interaction.guild.id,
        interaction.user.id
    )

    if level < MAX_LEVEL:

        needed = xp_needed(level)
        xp_text = f"{xp}/{needed}"

    else:

        xp_text = "MAX LEVEL"

    embed = discord.Embed(
        title="📊 Your Rezox Rank",
        color=discord.Color.blue()
    )

    embed.set_thumbnail(
        url=interaction.user.display_avatar.url
    )

    embed.add_field(
        name="Level",
        value=f"**{level}**",
        inline=True
    )

    embed.add_field(
        name="XP",
        value=f"**{xp_text}**",
        inline=True
    )

    embed.add_field(
        name="Messages",
        value=f"**{messages}**",
        inline=True
    )

    await interaction.response.send_message(
        embed=embed
    )

# =========================================================
# /LEADERBOARD
# =========================================================

@bot.tree.command(
    name="leaderboard",
    description="Show the server XP leaderboard"
)
async def leaderboard(interaction: discord.Interaction):

    cur.execute("""
        SELECT user_id, level, xp
        FROM users
        WHERE guild_id=?
        ORDER BY level DESC, xp DESC
        LIMIT 10
    """, (
        interaction.guild.id,
    ))

    rows = cur.fetchall()

    if not rows:

        await interaction.response.send_message(
            "No leaderboard data yet."
        )

        return

    description = ""

    for index, row in enumerate(
        rows,
        start=1
    ):

        user_id, level, xp = row

        member = interaction.guild.get_member(
            user_id
        )

        if member:
            name = member.display_name
        else:
            name = f"User {user_id}"

        description += (
            f"**{index}. {name}** — "
            f"Level **{level}** • "
            f"**{xp} XP**\n"
        )

    embed = discord.Embed(
        title="🏆 Rezox Leaderboard",
        description=description,
        color=discord.Color.blue()
    )

    await interaction.response.send_message(
        embed=embed
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
    role="Role to give at that level"
)
@app_commands.checks.has_permissions(
    manage_roles=True
)
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
    interaction: discord.Interaction,
    level: app_commands.Range[int, 1, 50]
):

    cur.execute("""
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

# =========================================================
# /LEVELROLES
# =========================================================

@bot.tree.command(
    name="levelroles",
    description="Show configured level roles"
)
async def levelroles(interaction: discord.Interaction):

    cur.execute("""
        SELECT level, role_id
        FROM level_roles
        WHERE guild_id=?
        ORDER BY level ASC
    """, (
        interaction.guild.id,
    ))

    rows = cur.fetchall()

    if not rows:

        await interaction.response.send_message(
            "No level roles have been configured."
        )

        return

    text = ""

    for level, role_id in rows:

        role = interaction.guild.get_role(
            role_id
        )

        if role:

            text += (
                f"**Level {level}** → "
                f"{role.mention}\n"
            )

        else:

            text += (
                f"**Level {level}** → "
                f"Deleted role\n"
            )

    embed = discord.Embed(
        title="🎖️ Level Roles",
        description=text,
        color=discord.Color.blue()
    )

    await interaction.response.send_message(
        embed=embed
    )

# =========================================================
# /LEVELCARD
# =========================================================

@bot.tree.command(
    name="levelcard",
    description="Show your current level card"
)
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

    await interaction.followup.send(
        file=file
    )

# =========================================================
# /TEST
# =========================================================

@bot.tree.command(
    name="test",
    description="Preview the level-up card"
)
@app_commands.describe(
    level="Preview level from 1 to 50"
)
async def test(
    interaction: discord.Interaction,
    level: app_commands.Range[int, 1, 50] = 5
):

    await interaction.response.defer()

    cur.execute("""
        SELECT role_id
        FROM level_roles
        WHERE guild_id=? AND level=?
    """, (
        interaction.guild.id,
        level
    ))

    row = cur.fetchone()

    role = None

    if row:
        role = interaction.guild.get_role(
            row[0]
        )

    card = await create_level_card(
        interaction.user,
        level,
        role
    )

    file = discord.File(
        card,
        filename="rezox-test-levelup.png"
    )

    await interaction.followup.send(
        content="🧪 **Level-up card preview**",
        file=file
    )

# =========================================================
# /DAILY
# =========================================================

@bot.tree.command(
    name="daily",
    description="Claim your daily XP"
)
async def daily(interaction: discord.Interaction):

    guild_id = interaction.guild.id
    user_id = interaction.user.id

    xp, level, messages, last_xp, last_daily = get_user(
        guild_id,
        user_id
    )

    now = time.time()

    remaining = DAILY_COOLDOWN - (
        now - last_daily
    )

    if remaining > 0:

        hours = int(
            remaining // 3600
        )

        minutes = int(
            (remaining % 3600) // 60
        )

        await interaction.response.send_message(
            f"⏳ You can claim your daily XP "
            f"again in **{hours}h {minutes}m**."
        )

        return

    xp += DAILY_XP
    last_daily = now

    old_level = level

    while (
        level < MAX_LEVEL
        and xp >= xp_needed(level)
    ):

        xp -= xp_needed(level)
        level += 1

    save_user(
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

        for new_level in range(
            old_level + 1,
            level + 1
        ):

            role = await apply_level_role(
                interaction.user,
                new_level
            )

            await send_level_up(
                interaction.user,
                new_level,
                role,
                interaction.channel
            )

# =========================================================
# /HELP
# =========================================================

@bot.tree.command(
    name="help",
    description="Show Rezox commands"
)
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

    await interaction.response.send_message(
        embed=embed
    )

# =========================================================
# ERROR HANDLER
# =========================================================

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

        print(
            "setlevelrole error:",
            error
        )

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ Something went wrong.",
                ephemeral=True
            )

# =========================================================
# START BOT
# =========================================================

if not TOKEN:

    print("❌ DISCORD_TOKEN is missing!")

else:

    bot.run(TOKEN)
