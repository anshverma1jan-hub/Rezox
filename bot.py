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

db = sqlite3.connect("levels.db")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    guild_id INTEGER,
    user_id INTEGER,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
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

db.commit()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

last_xp = {}


def xp_needed(level):
    return 100 + (level * 75)


def get_font(size):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    if os.path.exists(path):
        return ImageFont.truetype(path, size)

    return ImageFont.load_default()


async def create_level_card(member, level, xp):
    width = 900
    height = 300

    image = Image.new(
        "RGB",
        (width, height),
        (20, 22, 30)
    )

    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (10, 10, width - 10, height - 10),
        radius=30,
        fill=(30, 33, 44),
        outline=(80, 160, 255),
        width=3
    )

    try:
        avatar_data = await member.display_avatar.read()

        avatar = Image.open(
            io.BytesIO(avatar_data)
        ).convert("RGB")

        avatar = avatar.resize(
            (160, 160),
            Image.Resampling.LANCZOS
        )

        mask = Image.new(
            "L",
            (160, 160),
            0
        )

        mask_draw = ImageDraw.Draw(mask)

        mask_draw.ellipse(
            (0, 0, 160, 160),
            fill=255
        )

        image.paste(
            avatar,
            (60, 70),
            mask
        )

    except Exception as error:
        print("Avatar error:", error)

    username = member.display_name

    if len(username) > 20:
        username = username[:20] + "..."

    needed = xp_needed(level)

    draw.text(
        (260, 55),
        username,
        font=get_font(36),
        fill=(255, 255, 255)
    )

    draw.text(
        (260, 105),
        "LEVEL " + str(level),
        font=get_font(30),
        fill=(100, 180, 255)
    )

    draw.text(
        (260, 150),
        f"{xp} / {needed} XP",
        font=get_font(22),
        fill=(220, 220, 230)
    )

    bar_x = 260
    bar_y = 195
    bar_width = 570
    bar_height = 28

    draw.rounded_rectangle(
        (
            bar_x,
            bar_y,
            bar_x + bar_width,
            bar_y + bar_height
        ),
        radius=14,
        fill=(50, 54, 65)
    )

    progress = min(xp / needed, 1)

    if progress > 0:
        draw.rounded_rectangle(
            (
                bar_x,
                bar_y,
                bar_x + int(bar_width * progress),
                bar_y + bar_height
            ),
            radius=14,
            fill=(80, 165, 255)
        )

    draw.text(
        (260, 240),
        "REZOX • LEVEL UP",
        font=get_font(18),
        fill=(145, 150, 165)
    )

    output = io.BytesIO()

    image.save(
        output,
        format="PNG"
    )

    output.seek(0)

    return output


async def give_level_role(member, level):
    cursor.execute(
        """
        SELECT level, role_id
        FROM level_roles
        WHERE guild_id = ?
        AND level <= ?
        ORDER BY level DESC
        LIMIT 1
        """,
        (
            member.guild.id,
            level
        )
    )

    result = cursor.fetchone()

    if not result:
        return

    role_level, role_id = result

    new_role = member.guild.get_role(role_id)

    if not new_role:
        return

    bot_member = member.guild.me

    if not bot_member:
        return

    if new_role >= bot_member.top_role:
        print("Rezox cannot manage this role.")
        return

    cursor.execute(
        """
        SELECT role_id
        FROM level_roles
        WHERE guild_id = ?
        AND level < ?
        """,
        (
            member.guild.id,
            role_level
        )
    )

    old_roles = cursor.fetchall()

    for old_role_id in old_roles:
        old_role = member.guild.get_role(
            old_role_id[0]
        )

        if old_role and old_role in member.roles:
            try:
                await member.remove_roles(old_role)
            except Exception as error:
                print("Remove role error:", error)

    if new_role not in member.roles:
        try:
            await member.add_roles(new_role)
        except Exception as error:
            print("Add role error:", error)


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as error:
        print("Slash sync error:", error)

    print(f"Rezox is online as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is None:
        return

    key = (
        message.guild.id,
        message.author.id
    )

    now = time.time()

    if key in last_xp:
        if now - last_xp[key] < XP_COOLDOWN:
            await bot.process_commands(message)
            return

    last_xp[key] = now

    gained_xp = random.randint(
        XP_MIN,
        XP_MAX
    )

    cursor.execute(
        """
        SELECT xp, level, messages
        FROM users
        WHERE guild_id = ?
        AND user_id = ?
        """,
        (
            message.guild.id,
            message.author.id
        )
    )

    result = cursor.fetchone()

    if result:
        xp, level, messages = result
    else:
        xp = 0
        level = 0
        messages = 0

    old_level = level

    if level < 50:
        xp += gained_xp

        while level < 50 and xp >= xp_needed(level):
            xp -= xp_needed(level)
            level += 1

    messages += 1

    cursor.execute(
        """
        INSERT OR REPLACE INTO users
        (guild_id, user_id, xp, level, messages)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            message.guild.id,
            message.author.id,
            xp,
            level,
            messages
        )
    )

    db.commit()

    if level > old_level:
        await give_level_role(
            message.author,
            level
        )

        try:
            card = await create_level_card(
                message.author,
                level,
                xp
            )

            file = discord.File(
                card,
                filename="rezox_levelup.png"
            )

            embed = discord.Embed(
                title="🎉 LEVEL UP!",
                description=(
                    f"{message.author.mention} "
                    f"reached **Level {level}**!"
                ),
                color=discord.Color.blurple()
            )

            embed.set_image(
                url="attachment://rezox_levelup.png"
            )

            embed.set_footer(
                text=f"Rezox • Level {level}"
            )

            await message.channel.send(
                content=message.author.mention,
                embed=embed,
                file=file
            )

        except Exception as error:
            print("LEVEL CARD ERROR:", error)

            await message.channel.send(
                f"🎉 {message.author.mention} "
                f"reached **Level {level}**!"
            )

    await bot.process_commands(message)


@bot.tree.command(
    name="rank",
    description="Check your Rezox level and XP"
)
async def rank(interaction: discord.Interaction):
    cursor.execute(
        """
        SELECT xp, level, messages
        FROM users
        WHERE guild_id = ?
        AND user_id = ?
        """,
        (
            interaction.guild.id,
            interaction.user.id
        )
    )

    result = cursor.fetchone()

    if result:
        xp, level, messages = result
    else:
        xp = 0
        level = 0
        messages = 0

    embed = discord.Embed(
        title=f"📊 {interaction.user.display_name}'s Rank",
        color=discord.Color.blurple()
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
        value=f"**{xp} / {xp_needed(level)}**",
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


@bot.tree.command(
    name="leaderboard",
    description="Show the Rezox XP leaderboard"
)
async def leaderboard(interaction: discord.Interaction):
    cursor.execute(
        """
        SELECT user_id, level, xp
        FROM users
        WHERE guild_id = ?
        ORDER BY level DESC, xp DESC
        LIMIT 10
        """,
        (
            interaction.guild.id,
        )
    )

    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message(
            "📊 Leaderboard abhi empty hai."
        )
        return

    lines = []

    for index, row in enumerate(rows, start=1):
        user_id, level, xp = row

        member = interaction.guild.get_member(
            user_id
        )

        if member:
            name = member.display_name
        else:
            name = f"User {user_id}"

        lines.append(
            f"**#{index}** {name} — "
            f"Level **{level}** • {xp} XP"
        )

    embed = discord.Embed(
        title="🏆 Rezox Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold()
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="setlevelrole",
    description="Set an automatic role for a level"
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
            "❌ Tumhare paas Manage Roles permission nahi hai.",
            ephemeral=True
        )
        return

    bot_member = interaction.guild.me

    if not bot_member:
        await interaction.response.send_message(
            "❌ Rezox member data nahi mila.",
            ephemeral=True
        )
        return

    if role >= bot_member.top_role:
        await interaction.response.send_message(
            "❌ Rezox ka role is role se upar hona chahiye.",
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
        f"✅ Level **{level}** → "
        f"{role.mention} set kar diya!"
    )


@bot.tree.command(
    name="removelevelrole",
    description="Remove an automatic level role"
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
            "❌ Tumhare paas Manage Roles permission nahi hai.",
            ephemeral=True
        )
        return

    cursor.execute(
        """
        DELETE FROM level_roles
        WHERE guild_id = ?
        AND level = ?
        """,
        (
            interaction.guild.id,
            level
        )
    )

    db.commit()

    await interaction.response.send_message(
        f"🗑️ Level **{level}** ka role remove kar diya."
    )


@bot.tree.command(
    name="levelroles",
    description="Show all automatic level roles"
)
async def levelroles(interaction: discord.Interaction):
    cursor.execute(
        """
        SELECT level, role_id
        FROM level_roles
        WHERE guild_id = ?
        ORDER BY level ASC
        """,
        (
            interaction.guild.id,
        )
    )

    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message(
            "📋 Abhi koi level role set nahi hai."
        )
        return

    lines = []

    for level, role_id in rows:
        role = interaction.guild.get_role(
            role_id
        )

        if role:
            lines.append(
                f"**Level {level}** → {role.mention}"
            )

    if not lines:
        await interaction.response.send_message(
            "📋 Koi valid level role nahi mila."
        )
        return

    embed = discord.Embed(
        title="🎖️ Rezox Level Roles",
        description="\n".join(lines),
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed
    )


if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable missing."
    )

bot.run(TOKEN)
