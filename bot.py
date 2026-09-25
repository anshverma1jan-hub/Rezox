
import os
import random
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands

# =========================
# REZOX SETTINGS
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")

XP_MIN = 10
XP_MAX = 20
XP_COOLDOWN = 60  # seconds

# =========================
# DATABASE
# =========================

db = sqlite3.connect("levels.db")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER,
    guild_id INTEGER,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    messages INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
)
""")

db.commit()

# =========================
# BOT
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# XP cooldown memory
xp_cooldowns = {}

# =========================
# LEVEL MESSAGES
# =========================

level_messages = {
    1: "🎉 @user just reached **Level 1!** The grind begins!",
    2: "⚡ @user reached **Level 2!** Keep going!",
    3: "🔥 @user just unlocked **Level 3!**",
    4: "🚀 @user reached **Level 4!** You're getting started!",
    5: "🏆 GG @user! You reached **Level 5!**",
    6: "💥 @user hit **Level 6!**",
    7: "😎 @user is now **Level 7!**",
    8: "⚡ **Level 8 unlocked!** Keep grinding @user!",
    9: "🔥 @user is almost at Level 10!",
    10: "👑 @user reached **LEVEL 10!** Respect!",
    11: "🚀 @user reached **Level 11!**",
    12: "💎 @user just hit **Level 12!**",
    13: "🔥 @user reached **Level 13!**",
    14: "⚡ Level 14! @user isn't stopping!",
    15: "🏆 @user reached **Level 15!**",
    16: "💥 @user is now **Level 16!**",
    17: "😈 @user reached **Level 17!**",
    18: "🚀 Level 18 unlocked for @user!",
    19: "🔥 One more level! @user reached **19!**",
    20: "👑 **LEVEL 20!** @user is officially a grinder!"
}

# =========================
# XP FUNCTION
# =========================

def xp_needed(level):
    return 100 + (level * 75)


# =========================
# BOT READY
# =========================

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Command sync error: {e}")

    print(f"Rezox is online as {bot.user}")


# =========================
# MESSAGE XP
# =========================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        return

    user_id = message.author.id
    guild_id = message.guild.id

    # Create user if not exists
    cursor.execute(
        "SELECT xp, level, messages FROM users WHERE user_id=? AND guild_id=?",
        (user_id, guild_id)
    )

    result = cursor.fetchone()

    if result is None:
        cursor.execute(
            "INSERT INTO users (user_id, guild_id, xp, level, messages) VALUES (?, ?, 0, 0, 0)",
            (user_id, guild_id)
        )
        db.commit()

        xp = 0
        level = 0
        messages = 0

    else:
        xp, level, messages = result

    messages += 1

    # XP cooldown
    now = discord.utils.utcnow().timestamp()
    last_xp = xp_cooldowns.get((guild_id, user_id), 0)

    if now - last_xp >= XP_COOLDOWN:

        gained_xp = random.randint(XP_MIN, XP_MAX)
        xp += gained_xp

        xp_cooldowns[(guild_id, user_id)] = now

        # Level up
        new_level = level

        while xp >= xp_needed(new_level):
            xp -= xp_needed(new_level)
            new_level += 1

        if new_level > level:

            cursor.execute(
                """
                UPDATE users
                SET xp=?, level=?, messages=?
                WHERE user_id=? AND guild_id=?
                """,
                (xp, new_level, messages, user_id, guild_id)
            )

            db.commit()

            # Get custom message
            msg = level_messages.get(
                new_level,
                f"🎉 @user reached **Level {new_level}!** Keep grinding!"
            )

            msg = msg.replace("@user", message.author.mention)

            await message.channel.send(msg)

        else:

            cursor.execute(
                """
                UPDATE users
                SET xp=?, messages=?
                WHERE user_id=? AND guild_id=?
                """,
                (xp, messages, user_id, guild_id)
            )

            db.commit()

    else:

        cursor.execute(
            """
            UPDATE users
            SET messages=?
            WHERE user_id=? AND guild_id=?
            """,
            (messages, user_id, guild_id)
        )

        db.commit()

    await bot.process_commands(message)


# =========================
# /RANK
# =========================

@bot.tree.command(name="rank", description="Check your Rezox level and XP")
async def rank(interaction: discord.Interaction):

    user_id = interaction.user.id
    guild_id = interaction.guild.id

    cursor.execute(
        "SELECT xp, level, messages FROM users WHERE user_id=? AND guild_id=?",
        (user_id, guild_id)
    )

    result = cursor.fetchone()

    if result is None:
        xp = 0
        level = 0
        messages = 0
    else:
        xp, level, messages = result

    required = xp_needed(level)

    percentage = int((xp / required) * 10)

    bar = "█" * percentage + "░" * (10 - percentage)

    embed = discord.Embed(
        title="📊 Rezox Rank",
        description=f"**{interaction.user.display_name}**",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    embed.add_field(
        name="Level",
        value=f"**{level}**",
        inline=True
    )

    embed.add_field(
        name="XP",
        value=f"**{xp} / {required}**",
        inline=True
    )

    embed.add_field(
        name="Messages",
        value=f"**{messages}**",
        inline=True
    )

    embed.add_field(
        name="Progress",
        value=f"`{bar}`",
        inline=False
    )

    await interaction.response.send_message(embed=embed)


# =========================
# /LEADERBOARD
# =========================

@bot.tree.command(
    name="leaderboard",
    description="Show the server XP leaderboard"
)
async def leaderboard(interaction: discord.Interaction):

    guild_id = interaction.guild.id

    cursor.execute(
        """
        SELECT user_id, level, xp
        FROM users
        WHERE guild_id=?
        ORDER BY level DESC, xp DESC
        LIMIT 10
        """,
        (guild_id,)
    )

    users = cursor.fetchall()

    if not users:
        await interaction.response.send_message(
            "📊 Abhi leaderboard empty hai!"
        )
        return

    text = ""

    medals = ["🥇", "🥈", "🥉"]

    for index, (user_id, level, xp) in enumerate(users):

        member = interaction.guild.get_member(user_id)

        if member:
            name = member.display_name
        else:
            name = f"User {user_id}"

        prefix = medals[index] if index < 3 else f"**{index + 1}.**"

        text += (
            f"{prefix} **{name}** — "
            f"Level **{level}** • {xp} XP\n"
        )

    embed = discord.Embed(
        title="🏆 REZOX LEADERBOARD",
        description=text,
        color=discord.Color.gold()
    )

    await interaction.response.send_message(embed=embed)


# =========================
# RUN BOT
# =========================

if not TOKEN:
    raise ValueError("DISCORD_TOKEN is missing!")

bot.run(TOKEN)
