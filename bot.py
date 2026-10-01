"""
Rezox - Discord leveling bot
Requires: discord.py (2.x), Pillow, aiohttp, PyNaCl (optional, only for voice - not needed here)

Environment variable:
    DISCORD_TOKEN  - your bot token
"""

import asyncio
import os
import random
import sqlite3
import threading
import time
import traceback
import unicodedata
from contextlib import closing
from functools import lru_cache
from io import BytesIO
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

DB_FILE = "rezox.db"

XP_PER_MESSAGE = 10
XP_COOLDOWN = 60            # seconds
DAILY_XP = 100
DAILY_COOLDOWN = 24 * 60 * 60  # seconds
MAX_LEVEL = 50

# Card canvas
CARD_W = 1800
CARD_H = 650

# Fixed font sizes (NEVER auto-fitted)
FONT_LEVEL_UP = 46
FONT_USERNAME = 76
FONT_CONGRATS = 106
FONT_LEVEL = 88
FONT_ROLE = 36
FONT_LABEL = 30

# Fixed layout
AVATAR_SIZE = 340
AVATAR_X = 70
AVATAR_Y = (CARD_H - AVATAR_SIZE) // 2
TEXT_X = 450
USERNAME_MAX_WIDTH = 1000
ROLE_MAX_WIDTH = 760
BAR_W = 1080
BAR_H = 30
BAR_Y = 538

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "DejaVuSansCondensed-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
    "arialbd.ttf",
]

# Colors
COL_WHITE = (245, 245, 255, 255)
COL_SOFT = (205, 198, 235, 255)
COL_VIOLET = (167, 139, 250, 255)
COL_VIOLET_BRIGHT = (196, 148, 255, 255)
COL_PURPLE = (124, 58, 237, 255)

# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

http_session: Optional[aiohttp.ClientSession] = None
DB_LOCK = threading.Lock()


# ============================================================
# XP / LEVEL HELPERS
# ============================================================

def xp_needed(level: int) -> int:
    """XP required to go from `level` to `level + 1`."""
    return max(1, level) * 100


def apply_xp(level: int, xp: int, gain: int) -> Tuple[int, int]:
    """
    Add XP to a (level, xp) pair, handling multiple level-ups and
    preserving leftover XP. Returns (new_level, new_xp).
    """
    level = max(1, min(MAX_LEVEL, int(level)))
    xp = max(0, int(xp)) + max(0, int(gain))

    if level >= MAX_LEVEL:
        return MAX_LEVEL, 0

    while level < MAX_LEVEL and xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1

    if level >= MAX_LEVEL:
        level = MAX_LEVEL
        xp = 0

    return level, xp


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m"
    return "less than a minute"


# ============================================================
# DATABASE (sqlite3, executed in worker threads)
# ============================================================

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with DB_LOCK, closing(db_connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER NOT NULL,
                guild_id   INTEGER NOT NULL,
                xp         INTEGER NOT NULL DEFAULT 0,
                level      INTEGER NOT NULL DEFAULT 1,
                messages   INTEGER NOT NULL DEFAULT 0,
                last_xp    REAL NOT NULL DEFAULT 0,
                last_daily REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS level_roles (
                guild_id INTEGER NOT NULL,
                level    INTEGER NOT NULL,
                role_id  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, level)
            )
            """
        )
        conn.commit()


def _ensure_user(conn: sqlite3.Connection, guild_id: int, user_id: int) -> sqlite3.Row:
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, guild_id, xp, level, messages, last_xp, last_daily) "
        "VALUES (?, ?, 0, 1, 0, 0, 0)",
        (user_id, guild_id),
    )
    return conn.execute(
        "SELECT * FROM users WHERE user_id = ? AND guild_id = ?",
        (user_id, guild_id),
    ).fetchone()


def db_award_message(guild_id: int, user_id: int, now: float) -> Dict[str, Any]:
    """Count a message and award XP if the cooldown has passed."""
    with DB_LOCK, closing(db_connect()) as conn:
        row = _ensure_user(conn, guild_id, user_id)
        old_level = int(row["level"])
        xp = int(row["xp"])
        messages = int(row["messages"]) + 1
        last_xp = float(row["last_xp"])

        if old_level >= MAX_LEVEL or (now - last_xp) < XP_COOLDOWN:
            conn.execute(
                "UPDATE users SET messages = ? WHERE user_id = ? AND guild_id = ?",
                (messages, user_id, guild_id),
            )
            conn.commit()
            return {"leveled_up": False, "level": old_level, "xp": xp}

        new_level, new_xp = apply_xp(old_level, xp, XP_PER_MESSAGE)
        conn.execute(
            "UPDATE users SET xp = ?, level = ?, messages = ?, last_xp = ? "
            "WHERE user_id = ? AND guild_id = ?",
            (new_xp, new_level, messages, now, user_id, guild_id),
        )
        conn.commit()
        return {"leveled_up": new_level > old_level, "level": new_level, "xp": new_xp}


def db_claim_daily(guild_id: int, user_id: int, now: float) -> Dict[str, Any]:
    with DB_LOCK, closing(db_connect()) as conn:
        row = _ensure_user(conn, guild_id, user_id)
        last_daily = float(row["last_daily"])
        elapsed = now - last_daily

        if last_daily > 0 and elapsed < DAILY_COOLDOWN:
            conn.commit()
            return {"success": False, "remaining": DAILY_COOLDOWN - elapsed}

        old_level = int(row["level"])
        old_xp = int(row["xp"])
        new_level, new_xp = apply_xp(old_level, old_xp, DAILY_XP)
        conn.execute(
            "UPDATE users SET xp = ?, level = ?, last_daily = ? WHERE user_id = ? AND guild_id = ?",
            (new_xp, new_level, now, user_id, guild_id),
        )
        conn.commit()
        return {
            "success": True,
            "old_level": old_level,
            "level": new_level,
            "xp": new_xp,
            "leveled_up": new_level > old_level,
        }


def db_get_user(guild_id: int, user_id: int) -> Dict[str, Any]:
    """Return a user's stats (defaults if the user has no row yet) plus server position."""
    with DB_LOCK, closing(db_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        ).fetchone()
        if row is None:
            return {"xp": 0, "level": 1, "messages": 0, "position": None}

        position = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE guild_id = ? "
            "AND (level > ? OR (level = ? AND xp > ?))",
            (guild_id, row["level"], row["level"], row["xp"]),
        ).fetchone()["c"] + 1

        return {
            "xp": int(row["xp"]),
            "level": int(row["level"]),
            "messages": int(row["messages"]),
            "position": int(position),
        }


def db_leaderboard(guild_id: int, limit: int = 10) -> List[Dict[str, int]]:
    with DB_LOCK, closing(db_connect()) as conn:
        rows = conn.execute(
            "SELECT user_id, level, xp FROM users WHERE guild_id = ? "
            "ORDER BY level DESC, xp DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()
        return [
            {"user_id": int(r["user_id"]), "level": int(r["level"]), "xp": int(r["xp"])}
            for r in rows
        ]


def db_set_level_role(guild_id: int, level: int, role_id: int) -> None:
    with DB_LOCK, closing(db_connect()) as conn:
        conn.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (guild_id, level, role_id),
        )
        conn.commit()


def db_remove_level_role(guild_id: int, level: int) -> bool:
    with DB_LOCK, closing(db_connect()) as conn:
        cur = conn.execute(
            "DELETE FROM level_roles WHERE guild_id = ? AND level = ?",
            (guild_id, level),
        )
        conn.commit()
        return cur.rowcount > 0


def db_get_level_roles(guild_id: int) -> List[Tuple[int, int]]:
    with DB_LOCK, closing(db_connect()) as conn:
        rows = conn.execute(
            "SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC",
            (guild_id,),
        ).fetchall()
        return [(int(r["level"]), int(r["role_id"])) for r in rows]


async def run_db(func: Callable[..., Any], *args: Any) -> Any:
    return await asyncio.to_thread(func, *args)


# ============================================================
# ROLE HANDLING
# ============================================================

async def grant_level_roles(member: discord.Member, level: int) -> Optional[discord.Role]:
    """
    Give the member the highest configured reward role for their level and
    remove other configured reward roles. Returns the role if it was newly added.
    """
    guild = member.guild
    try:
        rows = await run_db(db_get_level_roles, guild.id)
    except Exception as e:
        print(f"[roles] Database error: {e}")
        return None

    if not rows:
        return None

    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        print(f"[roles] Missing Manage Roles permission in guild {guild.id}")
        return None

    configured: List[discord.Role] = []
    eligible: Optional[discord.Role] = None

    for lvl, role_id in rows:
        role = guild.get_role(role_id)
        if role is None:
            print(f"[roles] Configured role {role_id} (level {lvl}) no longer exists in guild {guild.id}")
            continue
        configured.append(role)
        if lvl <= level:
            eligible = role  # rows are sorted ascending, so the last match is the highest

    # Remove other configured reward roles
    to_remove = [
        r for r in configured
        if r != eligible and r in member.roles and not r.managed and r < me.top_role
    ]
    if to_remove:
        try:
            await member.remove_roles(*to_remove, reason="Rezox level reward update")
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"[roles] Could not remove old roles from {member.id}: {e}")

    if eligible is None or eligible in member.roles:
        return None

    if eligible.managed or eligible >= me.top_role:
        print(f"[roles] Role hierarchy prevents giving {eligible.id} in guild {guild.id}")
        return None

    try:
        await member.add_roles(eligible, reason=f"Rezox level reward (level {level})")
        return eligible
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"[roles] Could not add role {eligible.id} to {member.id}: {e}")
        return None


# ============================================================
# AVATAR DOWNLOADING
# ============================================================

async def fetch_avatar(member: discord.abc.User) -> Optional[bytes]:
    """Download a high resolution avatar. Returns None on failure."""
    global http_session
    try:
        asset = member.display_avatar.with_size(1024).with_static_format("png")
        url = str(asset.url)
    except Exception as e:
        print(f"[avatar] Could not build avatar URL: {e}")
        return None

    try:
        session = http_session
        if session is None or session.closed:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as temp:
                async with temp.get(url) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    print(f"[avatar] HTTP {resp.status} for {url}")
                    return None
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.read()
            print(f"[avatar] HTTP {resp.status} for {url}")
    except Exception as e:
        print(f"[avatar] Download failed: {e}")
    return None


# ============================================================
# FONT LOADING (fixed sizes only - no auto fitting)
# ============================================================

@lru_cache(maxsize=32)
def load_font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    print("[font] No TTF font found, using Pillow default font")
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def clean_text(text: str, fallback: str) -> str:
    """Remove emoji/symbol/control characters that a TTF font would render as boxes."""
    out = []
    for ch in str(text):
        cat = unicodedata.category(ch)
        if cat in ("So", "Sk", "Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            continue
        if ord(ch) > 0xFFFF:
            continue
        out.append(ch)
    cleaned = "".join(out).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned if cleaned else fallback


def truncate_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    """Truncate with '...' so text fits. The font size is never changed."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    text = text.rstrip()
    return (text + ellipsis) if text else ellipsis


def draw_spaced(draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
                font: ImageFont.ImageFont, fill: tuple, spacing: int) -> int:
    """Draw text with letter spacing. Returns the x coordinate after the last letter."""
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += int(draw.textlength(ch, font=font)) + spacing
    return x


# ============================================================
# CARD GENERATION
# ============================================================

def _overlay(base: Image.Image, layer: Image.Image, xy: Tuple[int, int]) -> Image.Image:
    """Alpha-composite `layer` onto `base` at xy (clips safely at the canvas edges)."""
    full = Image.new("RGBA", base.size, (0, 0, 0, 0))
    full.paste(layer, xy)
    return Image.alpha_composite(base, full)


def _make_fallback_avatar(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (38, 34, 66, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([size * 0.30, size * 0.16, size * 0.70, size * 0.56], fill=(112, 104, 160, 255))
    d.ellipse([size * 0.14, size * 0.60, size * 0.86, size * 1.30], fill=(112, 104, 160, 255))
    return img


def _load_avatar_image(data: Optional[bytes]) -> Image.Image:
    if data:
        try:
            img = Image.open(BytesIO(data))
            img.seek(0)
            img = img.convert("RGBA")
            w, h = img.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            return img.crop((left, top, left + side, top + side))
        except Exception as e:
            print(f"[avatar] Could not decode avatar image: {e}")
    return _make_fallback_avatar()


def _circle_mask(size: int) -> Image.Image:
    ss = 4
    mask = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * ss - 1, size * ss - 1], fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def _circular_avatar(img: Image.Image, size: int) -> Image.Image:
    out = img.resize((size, size), Image.LANCZOS).convert("RGBA")
    out.putalpha(_circle_mask(size))
    return out


def _make_ring(diameter: int, width: int, color: tuple) -> Image.Image:
    ss = 4
    big = Image.new("RGBA", (diameter * ss, diameter * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse(
        [0, 0, diameter * ss - 1, diameter * ss - 1], outline=color, width=width * ss
    )
    return big.resize((diameter, diameter), Image.LANCZOS)


def _draw_star(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill: tuple) -> None:
    k = r * 0.22
    d.polygon(
        [
            (cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
            (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k),
        ],
        fill=fill,
    )


def _make_background(w: int, h: int) -> Image.Image:
    bg = Image.new("RGBA", (w, h), (8, 8, 18, 255))
    d = ImageDraw.Draw(bg)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=(int(8 + 8 * t), int(8 + 4 * t), int(18 + 16 * t), 255))

    # Soft purple glows (drawn small, blurred, scaled up for speed)
    small = Image.new("RGBA", (w // 4, h // 4), (0, 0, 0, 0))
    sd = ImageDraw.Draw(small)
    sd.ellipse([-15, 10, 130, 150], fill=(124, 58, 237, 120))      # behind avatar
    sd.ellipse([330, -70, 520, 70], fill=(91, 33, 182, 100))       # top right
    sd.ellipse([150, 115, 340, 205], fill=(109, 40, 217, 55))      # bottom
    sd.ellipse([-60, -60, 80, 40], fill=(76, 29, 149, 90))         # top left
    small = small.filter(ImageFilter.GaussianBlur(28))
    glow = small.resize((w, h), Image.LANCZOS)
    return Image.alpha_composite(bg, glow)


def _make_decorations(w: int, h: int, level: int) -> Image.Image:
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = random.Random(1000 + level)

    # Subtle circles around the avatar and in the corner
    cx = AVATAR_X + AVATAR_SIZE // 2
    cy = AVATAR_Y + AVATAR_SIZE // 2
    for radius, alpha in ((222, 46), (268, 28), (318, 16)):
        d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                  outline=(139, 92, 246, alpha), width=2)
    d.ellipse([1640, -90, 1900, 170], outline=(139, 92, 246, 30), width=2)

    # Thin diagonal lines (far right, away from text)
    for i in range(5):
        x0 = 1650 + i * 32
        d.line([(x0, h), (w, h - (w - x0))], fill=(139, 92, 246, 20), width=2)

    # Particles
    for _ in range(46):
        px = rng.randint(10, w - 10)
        py = rng.randint(10, h - 10)
        pr = rng.choice((1.5, 2, 2.5, 3, 4))
        pa = rng.randint(40, 130)
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(167, 139, 250, pa))

    # Stars
    for sx, sy, sr, sa in (
        (58, 62, 11, 200), (420, 596, 8, 150), (1388, 62, 10, 180),
        (1712, 548, 12, 190), (1654, 262, 7, 150), (392, 44, 7, 150),
    ):
        _draw_star(d, sx, sy, sr, (196, 160, 255, sa))

    return layer


def _text_glow(base: Image.Image, xy: Tuple[int, int], text: str,
               font: ImageFont.ImageFont, color: tuple, blur: int) -> Image.Image:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=font, fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(base, layer)


def build_card_image(avatar_bytes: Optional[bytes], username: str, level: int,
                     xp: int, role_name: Optional[str]) -> BytesIO:
    """Build the level card (1800x650) and return PNG bytes. Fixed fonts, fixed coordinates."""
    W, H = CARD_W, CARD_H
    level = max(1, min(MAX_LEVEL, int(level)))
    is_max = level >= MAX_LEVEL
    need = xp_needed(level)
    xp = max(0, int(xp))

    avatar_src = _load_avatar_image(avatar_bytes)

    # ---------- background ----------
    base = _make_background(W, H)

    # Large faded avatar on the far right (subtle, kept clear of the text)
    faded_size = 560
    faded = avatar_src.resize((faded_size, faded_size), Image.LANCZOS).convert("L")
    faded = ImageOps.colorize(faded, black=(10, 6, 24), white=(150, 110, 255)).convert("RGBA")
    fmask = _circle_mask(faded_size).filter(ImageFilter.GaussianBlur(6))
    faded.putalpha(fmask.point(lambda v: int(v * 0.16)))
    base = _overlay(base, faded, (1590, 45))

    # Decorations
    base = Image.alpha_composite(base, _make_decorations(W, H, level))

    # ---------- main avatar ----------
    ring_gap = 6
    ring_w = 7
    ring_d = AVATAR_SIZE + 2 * (ring_gap + ring_w)
    ring_x = AVATAR_X - (ring_gap + ring_w)
    ring_y = AVATAR_Y - (ring_gap + ring_w)

    # soft glow behind the ring
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow_layer).ellipse(
        [ring_x - 6, ring_y - 6, ring_x + ring_d + 6, ring_y + ring_d + 6],
        outline=(139, 92, 246, 170), width=16,
    )
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(18))
    base = Image.alpha_composite(base, glow_layer)

    base = _overlay(base, _make_ring(ring_d, ring_w, (150, 100, 255, 255)), (ring_x, ring_y))
    base = _overlay(base, _circular_avatar(avatar_src, AVATAR_SIZE), (AVATAR_X, AVATAR_Y))

    # ---------- text ----------
    f_label_big = load_font(FONT_LEVEL_UP)
    f_user = load_font(FONT_USERNAME)
    f_congrats = load_font(FONT_CONGRATS)
    f_level = load_font(FONT_LEVEL)
    f_role = load_font(FONT_ROLE)
    f_small = load_font(FONT_LABEL)

    measure = ImageDraw.Draw(Image.new("RGBA", (10, 10)))

    safe_name = clean_text(username, "MEMBER")
    safe_name = truncate_text(measure, safe_name, f_user, USERNAME_MAX_WIDTH)

    y_levelup = 40
    y_user = 96
    y_congrats = 180
    y_level = 305
    y_role = 425
    y_xp_label = 490

    # Glows behind big text
    base = _text_glow(base, (TEXT_X, y_congrats), "CONGRATULATIONS!", f_congrats, (124, 58, 237, 200), 16)
    level_text = f"LEVEL {level}!"
    prefix = "YOU REACHED "
    prefix_w = int(measure.textlength(prefix, font=f_level))
    base = _text_glow(base, (TEXT_X + prefix_w, y_level), level_text, f_level, (150, 90, 255, 190), 14)

    d = ImageDraw.Draw(base)

    # LEVEL UP (small, letter-spaced) + accent line
    end_x = draw_spaced(d, TEXT_X, y_levelup, "LEVEL UP", f_label_big, COL_VIOLET, 10)
    d.line([(end_x + 20, y_levelup + 33), (end_x + 220, y_levelup + 33)], fill=(96, 64, 170, 255), width=3)

    # Username
    d.text((TEXT_X, y_user), safe_name, font=f_user, fill=COL_WHITE)

    # CONGRATULATIONS!
    d.text((TEXT_X, y_congrats), "CONGRATULATIONS!", font=f_congrats, fill=COL_WHITE)

    # YOU REACHED LEVEL X!
    d.text((TEXT_X, y_level), prefix, font=f_level, fill=COL_SOFT)
    d.text((TEXT_X + prefix_w, y_level), level_text, font=f_level, fill=COL_VIOLET_BRIGHT)

    # Optional NEW ROLE
    if role_name:
        label = "NEW ROLE: "
        label_w = int(measure.textlength(label, font=f_role))
        safe_role = clean_text(role_name, "ROLE")
        safe_role = truncate_text(measure, safe_role, f_role, ROLE_MAX_WIDTH - label_w)
        d.text((TEXT_X, y_role), label, font=f_role, fill=(150, 140, 190, 255))
        d.text((TEXT_X + label_w, y_role), safe_role, font=f_role, fill=COL_VIOLET)

    # ---------- XP bar ----------
    bar_x0 = TEXT_X
    bar_x1 = TEXT_X + BAR_W
    bar_y0 = BAR_Y
    bar_y1 = BAR_Y + BAR_H
    radius = BAR_H // 2

    if is_max:
        d.text((bar_x0, y_xp_label), "MAX LEVEL", font=f_small, fill=COL_VIOLET_BRIGHT)
        ratio = 1.0
        pct_text = "100%"
    else:
        d.text((bar_x0, y_xp_label), f"XP {xp} / {need}", font=f_small, fill=COL_SOFT)
        ratio = max(0.0, min(1.0, xp / need))
        pct_text = f"{int(ratio * 100)}%"
    d.text((bar_x1, y_xp_label), pct_text, font=f_small, fill=COL_SOFT, anchor="ra")

    d.rounded_rectangle([bar_x0, bar_y0, bar_x1, bar_y1], radius=radius,
                        fill=(26, 22, 48, 255), outline=(62, 46, 112, 255), width=2)

    fill_w = int(BAR_W * ratio)
    if ratio > 0:
        fill_w = max(fill_w, BAR_H)  # keep the rounded cap visible
        grad = Image.new("RGBA", (fill_w, BAR_H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for x in range(fill_w):
            t = x / max(1, fill_w - 1)
            gd.line([(x, 0), (x, BAR_H)],
                    fill=(int(124 + 72 * t), int(58 + 90 * t), int(237 + 18 * t), 255))
        gmask = Image.new("L", (fill_w, BAR_H), 0)
        ImageDraw.Draw(gmask).rounded_rectangle([0, 0, fill_w - 1, BAR_H - 1], radius=radius, fill=255)
        base.paste(grad, (bar_x0, bar_y0), gmask)

    # ---------- rounded card + border ----------
    ss = 2
    corner = 80
    mask_big = Image.new("L", (W * ss, H * ss), 0)
    ImageDraw.Draw(mask_big).rounded_rectangle([0, 0, W * ss - 1, H * ss - 1], radius=corner * ss, fill=255)
    card_mask = mask_big.resize((W, H), Image.LANCZOS)

    border_big = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    ImageDraw.Draw(border_big).rounded_rectangle(
        [3, 3, W * ss - 4, H * ss - 4], radius=corner * ss,
        outline=(139, 92, 246, 235), width=6,
    )
    base = Image.alpha_composite(base, border_big.resize((W, H), Image.LANCZOS))
    base.putalpha(card_mask)

    buf = BytesIO()
    base.save(buf, format="PNG")
    buf.seek(0)
    return buf


async def create_card_file(member: discord.abc.User, level: int, xp: int,
                           role_name: Optional[str] = None,
                           filename: str = "rezox_card.png") -> Optional[discord.File]:
    """Download the avatar, render the card in a worker thread, return a discord.File."""
    try:
        avatar_bytes = await fetch_avatar(member)
        name = getattr(member, "display_name", None) or member.name
        buf = await asyncio.to_thread(build_card_image, avatar_bytes, name, level, xp, role_name)
        return discord.File(buf, filename=filename)
    except Exception as e:
        print(f"[card] Failed to generate card: {e}")
        traceback.print_exc()
        return None


# ============================================================
# LEVEL-UP ANNOUNCEMENT
# ============================================================

async def announce_level_up(member: discord.Member, level: int, xp: int,
                            send: Callable[..., Awaitable[Any]],
                            prefix: str = "") -> None:
    role = await grant_level_roles(member, level)
    role_name = role.name if role else None

    file = await create_card_file(member, level, xp, role_name, filename="rezox_levelup.png")

    content = f"{prefix}{member.mention} reached **Level {level}**!"
    if role is not None:
        content += f" You earned the {role.mention} role!"

    kwargs: Dict[str, Any] = {
        "content": content,
        "allowed_mentions": discord.AllowedMentions(users=[member], roles=False, everyone=False),
    }
    if file is not None:
        kwargs["file"] = file

    try:
        await send(**kwargs)
    except discord.Forbidden:
        print(f"[levelup] Missing permission to send the level-up message for {member.id}")
    except discord.HTTPException as e:
        print(f"[levelup] Discord API error while sending level-up message: {e}")
    except Exception as e:
        print(f"[levelup] Unexpected error: {e}")


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def setup_hook() -> None:
    try:
        await asyncio.to_thread(init_db)
    except Exception as e:
        print(f"[db] Failed to initialise database: {e}")
        raise

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"[sync] Failed to sync slash commands: {e}")


@bot.event
async def on_ready() -> None:
    print(f"Rezox is online as {bot.user}")


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or message.guild is None:
        return

    try:
        result = await run_db(db_award_message, message.guild.id, message.author.id, time.time())
        if result["leveled_up"] and isinstance(message.author, discord.Member):
            await announce_level_up(message.author, result["level"], result["xp"], message.channel.send)
    except Exception as e:
        print(f"[xp] Error while processing message XP: {e}")
        traceback.print_exc()

    await bot.process_commands(message)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction,
                               error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need the **Manage Roles** permission to use this command."
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "This command can only be used inside a server."
    else:
        print(f"[command] Error in /{getattr(interaction.command, 'name', '?')}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        msg = "Something went wrong while running that command."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        print(f"[command] Could not send error message: {e}")


# ============================================================
# COMMANDS
# ============================================================

def _progress_bar(ratio: float, length: int = 12) -> str:
    filled = int(round(max(0.0, min(1.0, ratio)) * length))
    return "▰" * filled + "▱" * (length - filled)


@bot.tree.command(name="rank", description="Show your rank (or another member's).")
@app_commands.guild_only()
@app_commands.describe(member="The member to look up (default: you)")
async def rank(interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
    target = member or interaction.user
    data = await run_db(db_get_user, interaction.guild.id, target.id)

    level = data["level"]
    xp = data["xp"]
    embed = discord.Embed(title=f"{target.display_name}'s Rank", color=discord.Color.from_rgb(139, 92, 246))
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Level", value=str(level), inline=True)

    if level >= MAX_LEVEL:
        embed.add_field(name="XP", value="**MAX LEVEL**", inline=True)
        embed.add_field(name="Next Level", value="**MAX LEVEL**", inline=True)
        embed.add_field(name="Progress", value=_progress_bar(1.0), inline=False)
    else:
        need = xp_needed(level)
        embed.add_field(name="XP", value=f"{xp} / {need}", inline=True)
        embed.add_field(name="Next Level", value=f"{need - xp} XP needed", inline=True)
        embed.add_field(name="Progress", value=f"{_progress_bar(xp / need)} {int(xp / need * 100)}%", inline=False)

    embed.add_field(name="Messages", value=str(data["messages"]), inline=True)
    if data["position"] is not None:
        embed.add_field(name="Server Rank", value=f"#{data['position']}", inline=True)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Show the top 10 members of this server.")
@app_commands.guild_only()
async def leaderboard(interaction: discord.Interaction) -> None:
    rows = await run_db(db_leaderboard, interaction.guild.id, 10)

    if not rows:
        await interaction.response.send_message("Nobody has earned XP yet. Start chatting!", ephemeral=True)
        return

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []
    for i, row in enumerate(rows, start=1):
        member = interaction.guild.get_member(row["user_id"])
        name = discord.utils.escape_markdown(member.display_name) if member else "Former member"
        prefix = medals.get(i, f"**{i}.**")
        xp_text = "MAX" if row["level"] >= MAX_LEVEL else f"{row['xp']} XP"
        lines.append(f"{prefix} {name} — Level **{row['level']}** • {xp_text}")

    embed = discord.Embed(
        title=f"{interaction.guild.name} Leaderboard",
        description="\n".join(lines),
        color=discord.Color.from_rgb(139, 92, 246),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="levelcard", description="Generate your level card (or another member's).")
@app_commands.guild_only()
@app_commands.describe(member="The member to show (default: you)")
async def levelcard(interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
    await interaction.response.defer()
    target = member or interaction.user
    data = await run_db(db_get_user, interaction.guild.id, target.id)

    file = await create_card_file(target, data["level"], data["xp"], None, filename="rezox_levelcard.png")
    if file is None:
        await interaction.followup.send("Sorry, I couldn't generate the level card right now.", ephemeral=True)
        return
    await interaction.followup.send(file=file)


@bot.tree.command(name="test", description="Preview the level-up card for a chosen level.")
@app_commands.guild_only()
@app_commands.describe(level="Level to preview (1-50)")
async def test(interaction: discord.Interaction, level: app_commands.Range[int, 1, 50]) -> None:
    await interaction.response.defer()

    role_name: Optional[str] = None
    try:
        rows = await run_db(db_get_level_roles, interaction.guild.id)
        for lvl, role_id in rows:
            if lvl == level:
                role = interaction.guild.get_role(role_id)
                if role is not None:
                    role_name = role.name
                break
    except Exception as e:
        print(f"[test] Could not read level roles: {e}")

    preview_xp = 0 if level >= MAX_LEVEL else xp_needed(level) // 4
    file = await create_card_file(interaction.user, level, preview_xp, role_name, filename="rezox_test.png")
    if file is None:
        await interaction.followup.send("Sorry, I couldn't generate the preview right now.", ephemeral=True)
        return
    await interaction.followup.send(content=f"Preview of the level-up card for **Level {level}**:", file=file)


@bot.tree.command(name="daily", description=f"Claim your daily +{DAILY_XP} XP.")
@app_commands.guild_only()
async def daily(interaction: discord.Interaction) -> None:
    result = await run_db(db_claim_daily, interaction.guild.id, interaction.user.id, time.time())

    if not result["success"]:
        await interaction.response.send_message(
            f"You've already claimed your daily reward. Try again in about **{format_duration(result['remaining'])}**.",
            ephemeral=True,
        )
        return

    if result["leveled_up"] and isinstance(interaction.user, discord.Member):
        await interaction.response.defer()
        await announce_level_up(
            interaction.user, result["level"], result["xp"],
            interaction.followup.send,
            prefix=f"Daily reward claimed: **+{DAILY_XP} XP**!\n",
        )
        return

    if result["level"] >= MAX_LEVEL:
        text = "Daily reward claimed! You are already at **MAX LEVEL**."
    else:
        need = xp_needed(result["level"])
        text = f"Daily reward claimed: **+{DAILY_XP} XP**! You now have {result['xp']} / {need} XP."
    await interaction.response.send_message(text)


@bot.tree.command(name="setlevelrole", description="Give a role to members who reach a level.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(level="Level that grants the role (1-50)", role="The role to give")
async def setlevelrole(interaction: discord.Interaction, level: app_commands.Range[int, 1, 50],
                       role: discord.Role) -> None:
    guild = interaction.guild
    me = guild.me

    if role.is_default():
        await interaction.response.send_message("You can't use @everyone as a level role.", ephemeral=True)
        return
    if role.managed:
        await interaction.response.send_message(
            "That role is managed by an integration and can't be assigned manually.", ephemeral=True)
        return
    if me is None or not me.guild_permissions.manage_roles:
        await interaction.response.send_message(
            "I need the **Manage Roles** permission to hand out level roles.", ephemeral=True)
        return
    if role >= me.top_role:
        await interaction.response.send_message(
            f"I can't assign {role.mention} because it is higher than or equal to my highest role. "
            "Move my role above it in Server Settings > Roles.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    await run_db(db_set_level_role, guild.id, int(level), role.id)
    await interaction.response.send_message(
        f"Members who reach **Level {level}** will now receive {role.mention}.",
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.tree.command(name="removelevelrole", description="Remove the role reward for a level.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(level="Level whose role reward should be removed (1-50)")
async def removelevelrole(interaction: discord.Interaction, level: app_commands.Range[int, 1, 50]) -> None:
    removed = await run_db(db_remove_level_role, interaction.guild.id, int(level))
    if removed:
        await interaction.response.send_message(f"Removed the role reward for **Level {level}**.")
    else:
        await interaction.response.send_message(f"There is no role reward set for **Level {level}**.", ephemeral=True)


@bot.tree.command(name="levelroles", description="List all level role rewards.")
@app_commands.guild_only()
async def levelroles(interaction: discord.Interaction) -> None:
    rows = await run_db(db_get_level_roles, interaction.guild.id)
    if not rows:
        await interaction.response.send_message(
            "No level roles are configured yet. Admins can use `/setlevelrole`.", ephemeral=True)
        return

    lines = []
    for lvl, role_id in rows:
        role = interaction.guild.get_role(role_id)
        role_text = role.mention if role else f"*Deleted role* (`{role_id}`)"
        lines.append(f"**Level {lvl}** → {role_text}")

    embed = discord.Embed(
        title="Level Roles",
        description="\n".join(lines),
        color=discord.Color.from_rgb(139, 92, 246),
    )
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="help", description="Show everything Rezox can do.")
async def help_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Rezox Help",
        description=(
            f"Chat to earn **{XP_PER_MESSAGE} XP** per message (once every {XP_COOLDOWN} seconds). "
            f"Level {MAX_LEVEL} is the maximum."
        ),
        color=discord.Color.from_rgb(139, 92, 246),
    )
    embed.add_field(
        name="Members",
        value=(
            "`/rank` - View your level, XP and messages\n"
            "`/leaderboard` - Top 10 members\n"
            "`/levelcard` - Generate your level card\n"
            f"`/daily` - Claim +{DAILY_XP} XP every 24 hours\n"
            "`/levelroles` - See the role rewards\n"
            "`/help` - Show this message"
        ),
        inline=False,
    )
    embed.add_field(
        name="Admins (Manage Roles)",
        value=(
            "`/setlevelrole` - Set a role reward for a level\n"
            "`/removelevelrole` - Remove a role reward\n"
            "`/test` - Preview the level-up card"
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# STARTUP
# ============================================================

async def main() -> None:
    global http_session
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        http_session = session
        async with bot:
            await bot.start(TOKEN)


if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN is missing!")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("Rezox shut down.")
        except discord.LoginFailure:
            print("Invalid DISCORD_TOKEN - login failed.")
