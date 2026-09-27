import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import random
import time
import os
import io
from PIL import Image, ImageDraw, ImageFont

TOKEN = os.getenv("DISCORD_TOKEN")

XP_COOLDOWN = 60
XP_MIN = 10
XP_MAX = 20
DAILY_XP = 100
MAX_LEVEL = 50

DB_FILE = "rezox.db"

db = sqlite3.connect(DB_FILE)
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
    last_claim INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")

db.commit()

last_xp = {}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


def xp_needed(level):
    return 100 + (level * 75)


def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


async def create_level_card(member, level):
    width = 900
    height = 260

    image = Image.new("RGB", (width, height), (24, 25, 28))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (8, 8, width - 8, height - 8),
        radius=25,
        fill=(24, 25, 28)
    )

    avatar_data = await member.display_avatar.read()
    avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA")

    avatar = avatar.resize((150, 150))

    mask = Image.new("L", (150, 150), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, 150, 150), fill=255)

    image.paste(
        avatar,
        (55, 55),
        mask
    )

    name_font = get_font(38)
    message_font = get_font(28)
    level_font = get_font(22)

    username = member.display_name

    draw.text(
        (255, 65),
        username,
        font=name_font,
        fill=(255, 255, 255)
    )

    draw.text(
        (255, 125),
        f"Congratulations! You reached Level {level}!",
        font=message_font,
        fill=(220, 220, 220)
    )

    draw.text(
        (255, 170),
        f"Level {level}",
        font=level_font,
        fill=(170, 170, 170)
    )

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)

    return output


async def get_user(guild_id, user_id):
    cursor.execute(
        "SELECT xp, level, messages FROM users WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    )

    data = cursor.fetchone()

    if data is None:
        cursor.execute(
            "INSERT INTO users (guild_id, user_id, xp, level, messages) VALUES (?, ?, 0, 1, 0)",
            (guild_id, user_id)
        )
        db.commit()
        return 0, 1, 0

    return data


async def save_user(guild_id, user_id, xp, level, messages):
    cursor.execute(
        """
        UPDATE users
        SET xp=?, level=?, messages=?
        WHERE guild_id=? AND user_id=?
        """,
        (xp, level, messages, guild_id, user_id)
    )

    db.commit()


async def give_level_role(member, level):
    guild_id = member.guild.id

    cursor.execute(
        """
        SELECT level, role_id
        FROM level_roles
        WHERE guild_id=? AND level<=?
        ORDER BY level DESC
        LIMIT 1
        """,
        (guild_id, level)
    )

    result = cursor.fetchone()

    if not result:
        return

    selected_level, role_id = result
    role = member.guild.get_role(role_id)

    if role is None:
        return

    if member.guild.me is None:
        return

    bot_member = member.guild.me

    if role >= bot_member.top_role:
        print(
            f"Cannot manage role {role.name}. "
            f"Move Rezox's role above it."
        )
        return

    cursor.execute(
        """
        SELECT role_id
        FROM level_roles
        WHERE guild_id=?
        """,
        (guild_id,)
    )

    configured_roles = cursor.fetchall()

    for row in configured_roles:
        old_role = member.guild.get_role(row[0])

        if old_role and old_role != role and old_role in member.roles:
            if old_role < bot_member.top_role:
                try:
                    await member.remove_roles(old_role)
                except discord.Forbidden:
                    pass

    if role not in member.roles:
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            pass


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Command sync error: {e}")

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

    old_time = last_xp.get((guild_id, user_id), 0)

    if now - old_time < XP_COOLDOWN:
        await bot.process_commands(message)
        return

    last_xp[(guild_id, user_id)] = now

    xp, level, messages = await get_user(
        guild_id,
        user_id
    )

    messages += 1

    xp += random.randint(XP_MIN, XP_MAX)

    leveled_up = False

    while level < MAX_LEVEL and xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
        leveled_up = True

    if level >= MAX_LEVEL:
        level = MAX_LEVEL
        xp = 0

    await save_user(
        guild_id,
        user_id,
        xp,
        level,
        messages
    )

    if leveled_up:
        await give_level_role(
            message.author,
            level
        )

        try:
            card = await create_level_card(
                message.author,
                level
            )

            file = discord.File(
                card,
                filename="levelup.png"
            )

            await message.channel.send(
                content=message.author.mention,
                file=file
            )

        except Exception as e:
            print(f"LEVEL CARD ERROR: {e}")

            await message.channel.send(
                f"🎉 {message.author.mention} reached Level {level}!"
            )

    await bot.process_commands(message)


@bot.tree.command(
    name="rank",
    description="Check your level, XP and server rank."
)
async def rank(interaction: discord.Interaction):
    xp, level, messages = await get_user(
        interaction.guild.id,
        interaction.user.id
    )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE guild_id=? AND level>?
        """,
        (interaction.guild.id, level)
    )

    higher = cursor.fetchone()[0]
    server_rank = higher + 1

    needed = xp_needed(level)

    embed = discord.Embed(
        title="📊 Your Rank",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(
        url=interaction.user.display_avatar.url
    )

    embed.add_field(
        name="Level",
        value=str(level),
        inline=True
    )

    embed.add_field(
        name="XP",
        value=f"{xp}/{needed}",
        inline=True
    )

    embed.add_field(
        name="Server Rank",
        value=f"#{server_rank}",
        inline=True
    )

    embed.add_field(
        name="Messages",
        value=str(messages),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="leaderboard",
    description="Show the server XP leaderboard."
)
async def leaderboard(interaction: discord.Interaction):
    cursor.execute(
        """
        SELECT user_id, xp, level, messages
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
            "No leveling data yet."
        )
        return

    text = ""

    for index, row in enumerate(rows, start=1):
        user_id, xp, level, messages = row

        member = interaction.guild.get_member(user_id)

        if member:
            name = member.display_name
        else:
            name = f"User {user_id}"

        text += (
            f"**{index}. {name}** — "
            f"Level {level} • {xp} XP\n"
        )

    embed = discord.Embed(
        title="🏆 Level Leaderboard",
        description=text,
        color=discord.Color.gold()
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="setlevelrole",
    description="Set a role for a specific level."
)
@app_commands.describe(
    level="Level from 1 to 50",
    role="Role to give at this level"
)
async def setlevelrole(
    interaction: discord.Interaction,
    level: app_commands.Range[int, 1, 50],
    role: discord.Role
):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message(
            "❌ You need Manage Roles permission.",
            ephemeral=True
        )
        return

    if interaction.guild.me and role >= interaction.guild.me.top_role:
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
        (interaction.guild.id, level, role.id)
    )

    db.commit()

    await interaction.response.send_message(
        f"✅ Level **{level}** is now linked to {role.mention}."
    )


@bot.tree.command(
    name="removelevelrole",
    description="Remove a level role configuration."
)
@app_commands.describe(
    level="Level from 1 to 50"
)
async def removelevelrole(
    interaction: discord.Interaction,
    level: app_commands.Range[int, 1, 50]
):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message(
            "❌ You need Manage Roles permission.",
            ephemeral=True
        )
        return

    cursor.execute(
        """
        DELETE FROM level_roles
        WHERE guild_id=? AND level=?
        """,
        (interaction.guild.id, level)
    )

    db.commit()

    await interaction.response.send_message(
        f"✅ Level role for Level **{level}** removed."
    )


@bot.tree.command(
    name="levelroles",
    description="Show all configured level roles."
)
async def levelroles(interaction: discord.Interaction):
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
            "No level roles are configured."
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
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="daily",
    description="Claim your daily XP reward."
)
async def daily(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    user_id = interaction.user.id
    now = int(time.time())

    cursor.execute(
        """
        SELECT last_claim
        FROM daily_claims
        WHERE guild_id=? AND user_id=?
        """,
        (guild_id, user_id)
    )

    result = cursor.fetchone()

    if result:
        last_claim = result[0]
    else:
        last_claim = 0

    cooldown = 86400
    remaining = cooldown - (now - last_claim)

    if remaining > 0:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await interaction.response.send_message(
            f"⏳ You already claimed your daily reward.\n"
            f"Come back in **{hours}h {minutes}m**.",
            ephemeral=True
        )
        return

    xp, level, messages = await get_user(
        guild_id,
        user_id
    )

    xp += DAILY_XP
    leveled_up = False

    while level < MAX_LEVEL and xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
        leveled_up = True

    if level >= MAX_LEVEL:
        level = MAX_LEVEL
        xp = 0

    await save_user(
        guild_id,
        user_id,
        xp,
        level,
        messages
    )

    cursor.execute(
        """
        INSERT OR REPLACE INTO daily_claims
        (guild_id, user_id, last_claim)
        VALUES (?, ?, ?)
        """,
        (guild_id, user_id, now)
    )

    db.commit()

    await interaction.response.send_message(
        f"🎁 {interaction.user.mention} claimed **+{DAILY_XP} XP**!\n"
        f"✨ Current Level: **{level}**"
    )

    if leveled_up:
        await give_level_role(
            interaction.user,
            level
        )


@bot.tree.command(
    name="levelcard",
    description="Show your current level card."
)
@app_commands.describe(
    member="Member whose level card you want to see"
)
async def levelcard(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    if member is None:
        member = interaction.user

    xp, level, messages = await get_user(
        interaction.guild.id,
        member.id
    )

    try:
        card = await create_level_card(
            member,
            level
        )

        file = discord.File(
            card,
            filename="levelcard.png"
        )

        await interaction.response.send_message(
            file=file
        )

    except Exception as e:
        print(f"LEVELCARD ERROR: {e}")

        await interaction.response.send_message(
            f"❌ Couldn't create the level card.",
            ephemeral=True
        )


@bot.tree.command(
    name="help",
    description="Show all Rezox commands."
)
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚡ Rezox Help",
        description="Your server's Level-Up Bot",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="📊 Leveling",
        value=(
            "`/rank` — Check your rank\n"
            "`/leaderboard` — Top 10 members\n"
            "`/levelcard` — Show your level card\n"
            "`/daily` — Claim daily XP"
        ),
        inline=False
    )

    embed.add_field(
        name="🎖️ Level Roles",
        value=(
            "`/setlevelrole` — Set a level role\n"
            "`/removelevelrole` — Remove a level role\n"
            "`/levelroles` — View configured roles"
        ),
        inline=False
    )

    embed.add_field(
        name="ℹ️ Other",
        value="`/help` — Show this menu",
        inline=False
    )

    embed.set_footer(
        text="Rezox • Level up, rank up."
    )

    await interaction.response.send_message(
        embed=embed
    )


if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable missing."
    )

bot.run(TOKEN)
