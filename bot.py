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

XP_MIN = 10
XP_MAX = 20
XP_COOLDOWN = 60

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

level_messages = {
1: "✨ {user} has entered the Rezox Leveling Zone!",
2: "⚡ {user} just reached Level 2!",
3: "🔥 Level 3 unlocked for {user}!",
4: "🚀 {user} is gaining momentum — Level 4!",
5: "🏅 LEVEL 5! {user} just unlocked a new milestone!",
6: "💫 {user} reached Level 6!",
7: "🎯 Level 7 achieved by {user}!",
8: "⚡ {user} is climbing fast — Level 8!",
9: "🔥 Level 9 unlocked for {user}!",
10: "🏆 LEVEL 10! Double digits unlocked for {user}!",
11: "✨ {user} reached Level 11!",
12: "🚀 Level 12 unlocked!",
13: "🎮 {user} is now Level 13!",
14: "⚡ {user} keeps climbing — Level 14!",
15: "🏅 LEVEL 15! Another milestone for {user}!",
16: "🔥 {user} reached Level 16!",
17: "💫 Level 17 unlocked!",
18: "🎯 {user} is now Level 18!",
19: "🚀 One more level and it's 20 — keep going, {user}!",
20: "👑 LEVEL 20! {user} reached a major Rezox milestone!",
21: "⚡ {user} unlocked Level 21!",
22: "🔥 Level 22 achieved!",
23: "✨ {user} is now Level 23!",
24: "🚀 {user} reached Level 24!",
25: "🏆 LEVEL 25! Halfway to 50 — congratulations, {user}!",
26: "💫 Level 26 unlocked!",
27: "🎯 {user} reached Level 27!",
28: "⚡ Level 28 achieved!",
29: "🔥 One step away from 30, {user}!",
30: "👑 LEVEL 30! {user} has entered the Elite Zone!",
31: "🚀 Level 31 unlocked!",
32: "✨ {user} reached Level 32!",
33: "🔥 Level 33 achieved!",
34: "⚡ {user} is now Level 34!",
35: "🏅 LEVEL 35! Another big milestone!",
36: "💫 {user} reached Level 36!",
37: "🎯 Level 37 unlocked!",
38: "🚀 {user} keeps climbing — Level 38!",
39: "🔥 One level away from 40!",
40: "👑 LEVEL 40! {user} is getting legendary!",
41: "⚡ Level 41 unlocked!",
42: "✨ {user} reached Level 42!",
43: "🔥 Level 43 achieved!",
44: "🚀 {user} is now Level 44!",
45: "🏆 LEVEL 45! The final stretch begins!",
46: "💫 Level 46 unlocked!",
47: "🎯 {user} reached Level 47!",
48: "⚡ Just two levels away from 50!",
49: "🔥 ONE MORE LEVEL! {user} is almost at 50!",
50: "👑💎 LEVEL 50! {user} reached the legendary Rezox milestone!"
}

def xp_needed(level):
return 100 + (level * 75)

def get_font(size):
paths = [
"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
"/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
]

```
for path in paths:
    if os.path.exists(path):
        return ImageFont.truetype(path, size)

return ImageFont.load_default()
```

async def create_level_card(member, level, xp):
width = 1000
height = 350

```
image = Image.new(
    "RGB",
    (width, height),
    (16, 18, 25)
)

draw = ImageDraw.Draw(image)

draw.rounded_rectangle(
    (10, 10, width - 10, height - 10),
    radius=35,
    fill=(25, 28, 38),
    outline=(75, 85, 110),
    width=3
)

draw.rounded_rectangle(
    (35, 30, width - 35, 38),
    radius=4,
    fill=(80, 160, 255)
)

try:
    avatar_bytes = await member.display_avatar.read()

    avatar = Image.open(
        io.BytesIO(avatar_bytes)
    ).convert("RGB")

    avatar = avatar.resize(
        (190, 190),
        Image.Resampling.LANCZOS
    )

    mask = Image.new(
        "L",
        (190, 190),
        0
    )

    mask_draw = ImageDraw.Draw(mask)

    mask_draw.ellipse(
        (0, 0, 190, 190),
        fill=255
    )

    draw.ellipse(
        (48, 78, 242, 272),
        fill=(80, 160, 255)
    )

    image.paste(
        avatar,
        (52, 82),
        mask
    )

except Exception as error:
    print(f"Avatar error: {error}")

username_font = get_font(42)
level_font = get_font(34)
normal_font = get_font(25)
small_font = get_font(20)

username = member.display_name

if len(username) > 22:
    username = username[:22] + "..."

draw.text(
    (290, 75),
    username,
    font=username_font,
    fill=(255, 255, 255)
)

draw.text(
    (290, 135),
    f"LEVEL {level}",
    font=level_font,
    fill=(105, 180, 255)
)

needed = xp_needed(level)

draw.text(
    (290, 185),
    f"{xp:,} / {needed:,} XP",
    font=normal_font,
    fill=(210, 215, 225)
)

bar_x = 290
bar_y = 235
bar_width = 620
bar_height = 32

draw.rounded_rectangle(
    (
        bar_x,
        bar_y,
        bar_x + bar_width,
        bar_y + bar_height
    ),
    radius=16,
    fill=(48, 52, 65)
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
        radius=16,
        fill=(80, 165, 255)
    )

draw.text(
    (290, 295),
    "REZOX • LEVEL UP",
    font=small_font,
    fill=(135, 145, 165)
)

output = io.BytesIO()

image.save(
    output,
    format="PNG"
)

output.seek(0)

return output
```

async def give_level_role(member, new_level):
guild = member.guild

```
cursor.execute("""
    SELECT level, role_id
    FROM level_roles
    WHERE guild_id = ?
    AND level <= ?
    ORDER BY level DESC
    LIMIT 1
""", (
    guild.id,
    new_level
))

result = cursor.fetchone()

if not result:
    return

role_level, role_id = result
new_role = guild.get_role(role_id)

if not new_role:
    return

bot_member = guild.me

if not bot_member:
    return

if new_role >= bot_member.top_role:
    print(
        f"Cannot manage role {new_role.name}: "
        f"Rezox role is not high enough."
    )
    return

cursor.execute("""
    SELECT role_id
    FROM level_roles
    WHERE guild_id = ?
    AND level < ?
""", (
    guild.id,
    role_level
))

old_roles = cursor.fetchall()

for (old_role_id,) in old_roles:
    old_role = guild.get_role(old_role_id)

    if old_role and old_role in member.roles:
        if old_role < bot_member.top_role:
            try:
                await member.remove_roles(
                    old_role,
                    reason="Rezox level role upgrade"
                )
            except Exception as error:
                print(f"Remove role error: {error}")

if new_role not in member.roles:
    try:
        await member.add_roles(
            new_role,
            reason=f"Rezox Level {new_level}"
        )
    except Exception as error:
        print(f"Add role error: {error}")
```

@bot.event
async def on_ready():
try:
synced = await bot.tree.sync()
print(f"Synced {len(synced)} slash commands.")
except Exception as error:
print(f"Slash command sync error: {error}")

```
print(f"Rezox is online as {bot.user}")
```

@bot.event
async def on_message(message):
if message.author.bot:
return

```
if message.guild is None:
    return

guild_id = message.guild.id
user_id = message.author.id

current_time = time.time()
key = (guild_id, user_id)

if key in last_xp:
    if current_time - last_xp[key] < XP_COOLDOWN:
        await bot.process_commands(message)
        return

last_xp[key] = current_time

gained_xp = random.randint(
    XP_MIN,
    XP_MAX
)

cursor.execute("""
    SELECT xp, level, messages
    FROM users
    WHERE guild_id = ?
    AND user_id = ?
""", (
    guild_id,
    user_id
))

result = cursor.fetchone()

if result:
    xp, level, messages = result
else:
    xp = 0
    level = 0
    messages = 0

old_level = level

xp += gained_xp
messages += 1

while xp >= xp_needed(level):
    xp -= xp_needed(level)
    level += 1

cursor.execute("""
    INSERT OR REPLACE INTO users
    (
        guild_id,
        user_id,
        xp,
        level,
        messages
    )
    VALUES (?, ?, ?, ?, ?)
""", (
    guild_id,
    user_id,
    xp,
    level,
    messages
))

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

        level_text = level_messages.get(
            level,
            f"🔥 {message.author.mention} reached Level {level}!"
        )

        level_text = level_text.format(
            user=message.author.mention
        )

        embed = discord.Embed(
            title="🎉 LEVEL UP!",
            description=level_text,
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
        print(f"LEVEL CARD ERROR: {error}")

        await message.channel.send(
            f"🎉 {message.author.mention} reached **Level {level}**!"
        )

await bot.process_commands(message)
```

@bot.tree.command(
name="rank",
description="Check your Rezox level and XP"
)
async def rank(interaction: discord.Interaction):
cursor.execute("""
SELECT xp, level, messages
FROM users
WHERE guild_id = ?
AND user_id = ?
""", (
interaction.guild.id,
interaction.user.id
))

```
result = cursor.fetchone()

if result:
    xp, level, messages = result
else:
    xp = 0
    level = 0
    messages = 0

needed = xp_needed(level)

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
    value=f"**{xp} / {needed}**",
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
```

@bot.tree.command(
name="leaderboard",
description="Show the Rezox XP leaderboard"
)
async def leaderboard(interaction: discord.Interaction):
cursor.execute("""
SELECT user_id, level, xp
FROM users
WHERE guild_id = ?
ORDER BY level DESC, xp DESC
LIMIT 10
""", (
interaction.guild.id,
))

```
rows = cursor.fetchall()

if not rows:
    await interaction.response.send_message(
        "📊 Leaderboard abhi empty hai."
    )
    return

text = ""

for index, (user_id, level, xp) in enumerate(
    rows,
    start=1
):
    member = interaction.guild.get_member(
        user_id
    )

    if member:
        name = member.display_name
    else:
        name = f"User {user_id}"

    text += (
        f"**#{index}** {name} "
        f"— Level **{level}** • {xp} XP\n"
    )

embed = discord.Embed(
    title="🏆 Rezox Leaderboard",
    description=text,
    color=discord.Color.gold()
)

await interaction.response.send_message(
    embed=embed
)
```

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

```
bot_member = interaction.guild.me

if not bot_member:
    await interaction.response.send_message(
        "❌ Rezox ka server member data nahi mila.",
        ephemeral=True
    )
    return

if role >= bot_member.top_role:
    await interaction.response.send_message(
        "❌ Rezox ka role is role se upar hona chahiye.",
        ephemeral=True
    )
    return

cursor.execute("""
    INSERT OR REPLACE INTO level_roles
    (
        guild_id,
        level,
        role_id
    )
    VALUES (?, ?, ?)
""", (
    interaction.guild.id,
    level,
    role.id
))

db.commit()

await interaction.response.send_message(
    f"✅ Level **{level}** → {role.mention} set kar diya!"
)
```

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

```
cursor.execute("""
    DELETE FROM level_roles
    WHERE guild_id = ?
    AND level = ?
""", (
    interaction.guild.id,
    level
))

db.commit()

await interaction.response.send_message(
    f"🗑️ Level **{level}** ka automatic role remove kar diya."
)
```

@bot.tree.command(
name="levelroles",
description="Show all automatic level roles"
)
async def levelroles(interaction: discord.Interaction):
cursor.execute("""
SELECT level, role_id
FROM level_roles
WHERE guild_id = ?
ORDER BY level ASC
""", (
interaction.guild.id,
))

```
rows = cursor.fetchall()

if not rows:
    await interaction.response.send_message(
        "📋 Abhi koi level role set nahi hai."
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

embed = discord.Embed(
    title="🎖️ Rezox Level Roles",
    description=text,
    color=discord.Color.blurple()
)

await interaction.response.send_message(
    embed=embed
)
```

if not TOKEN:
raise RuntimeError(
"DISCORD_TOKEN environment variable missing."
)

bot.run(TOKEN)
