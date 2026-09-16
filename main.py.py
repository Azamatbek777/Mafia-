"""
Telegram Movie Bot - Complete single-file implementation
Python 3.11+ | aiogram 3.x | aiosqlite | python-dotenv

Configure BOT_TOKEN, ADMIN_IDS, CHANNEL_ID, SUPPORT_USERNAME below
or via .env file.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile, BufferedInputFile
)
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramBadRequest

# ==================== CONFIGURATION ====================
# CHANGE THESE VALUES (or put them in a .env file)
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_BOT_TOKEN_HERE")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip().isdigit()]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@username")

load_dotenv()  # Load .env if present (overrides above if set)

DB_PATH = "movies.db"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                alternative_title TEXT,
                description TEXT,
                year INTEGER,
                genre TEXT,
                rating REAL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                views INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_activity TEXT DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                movie_id INTEGER NOT NULL,
                UNIQUE(telegram_id, movie_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS genres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        # Indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_movies_code ON movies(code)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(title)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_movies_genre ON movies(genre)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_movies_views ON movies(views)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_tg ON users(telegram_id)")
        await db.commit()

        # Default genres
        default_genres = [
            "Action", "Comedy", "Horror", "Romance", "Sci-Fi",
            "Fantasy", "Drama", "Thriller", "Family", "Animation"
        ]
        for g in default_genres:
            try:
                await db.execute("INSERT OR IGNORE INTO genres (name) VALUES (?)", (g,))
            except Exception:
                pass
        await db.commit()

async def get_db():
    return await aiosqlite.connect(DB_PATH)

# ==================== FSM STATES ====================
class AddMovie(StatesGroup):
    code = State()
    title = State()
    alt_title = State()
    description = State()
    year = State()
    genre = State()
    rating = State()
    channel_id = State()
    message_id = State()

class FastAddMovie(StatesGroup):
    code = State()
    title = State()
    description = State()
    year = State()
    genre = State()
    rating = State()

class EditMovie(StatesGroup):
    choose = State()
    field = State()
    value = State()

class Broadcast(StatesGroup):
    waiting = State()

class SearchCode(StatesGroup):
    waiting = State()

class SearchTitle(StatesGroup):
    waiting = State()

class AdminDelete(StatesGroup):
    confirm = State()

# ==================== KEYBOARDS ====================
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Kino qidirish"), KeyboardButton(text="🔢 Kod orqali qidirish")],
            [KeyboardButton(text="🎭 Janrlar"), KeyboardButton(text="🔥 Eng ko‘p ko‘rilgan")],
            [KeyboardButton(text="🆕 Yangi kinolar"), KeyboardButton(text="❤️ Sevimlilar")],
            [KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True
    )

def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kino qo‘shish", callback_data="admin_add")],
        [InlineKeyboardButton(text="✏️ Kino tahrirlash", callback_data="admin_edit")],
        [InlineKeyboardButton(text="🗑 Kino o‘chirish", callback_data="admin_delete")],
        [InlineKeyboardButton(text="📋 Kinolar", callback_data="admin_list")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton(text="📢 Reklama", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📢 Majburiy obuna", callback_data="admin_force_sub")],
        [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="admin_settings")],
    ])

def movie_actions_kb(movie_id: int, is_fav: bool = False) -> InlineKeyboardMarkup:
    fav_btn = InlineKeyboardButton(
        text="💔 Sevimlilardan olib tashlash" if is_fav else "❤️ Sevimlilarga qo‘shish",
        callback_data=f"fav_{movie_id}" if not is_fav else f"unfav_{movie_id}"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Kinoni ko‘rish", callback_data=f"watch_{movie_id}")],
        [fav_btn],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")],
    ])

def force_sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url=f"https://t.me/c/{str(CHANNEL_ID)[4:]}")],
        [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")],
    ])

def confirm_delete_kb(movie_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha", callback_data=f"del_yes_{movie_id}"),
            InlineKeyboardButton(text="❌ Yo‘q", callback_data="del_no"),
        ]
    ])

def genres_kb(genres: List[str]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i, g in enumerate(genres):
        row.append(InlineKeyboardButton(text=g, callback_data=f"genre_{g}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )

# ==================== HELPERS ====================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def register_user(message: Message):
    user = message.from_user
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (telegram_id, username, first_name, last_activity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_activity=excluded.last_activity,
                is_blocked=0
        """, (user.id, user.username, user.first_name, datetime.now().isoformat()))
        await db.commit()

async def check_subscription(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.RESTRICTED
        )
    except Exception as e:
        logger.warning(f"Subscription check failed for {user_id}: {e}")
        # If bot cannot check (not admin), allow access to avoid locking users out
        return True

async def get_movie_by_code(code: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM movies WHERE code = ?", (code,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def get_movie_by_id(movie_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def increment_views(movie_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE movies SET views = views + 1 WHERE id = ?", (movie_id,))
        await db.commit()

async def is_favorite(telegram_id: int, movie_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM favorites WHERE telegram_id = ? AND movie_id = ?",
            (telegram_id, movie_id)
        ) as cur:
            return await cur.fetchone() is not None

def format_movie_card(movie: Dict) -> str:
    title = movie.get("title") or "Noma'lum"
    alt = movie.get("alternative_title")
    year = movie.get("year") or "—"
    genre = movie.get("genre") or "—"
    rating = movie.get("rating") or "—"
    views = movie.get("views") or 0
    desc = movie.get("description") or ""
    text = f"🎬 <b>{title}</b>"
    if alt:
        text += f"\n📌 {alt}"
    text += f"\n\n📅 {year}\n🎭 {genre}\n⭐ {rating}\n👀 {views:,}\n"
    if desc:
        text += f"\n📝 {desc}"
    return text

# ==================== ROUTERS ====================
router = Router()

# ---------- START / HELP ----------
@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await register_user(message)
    if not await check_subscription(bot, message.from_user.id):
        await message.answer(
            "📢 Botdan foydalanish uchun kanalimizga obuna bo‘ling.\n\n"
            "Obuna bo‘lgandan keyin «✅ Tekshirish» tugmasini bosing.",
            reply_markup=force_sub_kb()
        )
        return
    await message.answer(
        "🎬 <b>Kino Bot</b>\n\n"
        "Kerakli kinoni kod yoki nom orqali tez toping.",
        reply_markup=main_menu_kb(),
        parse_mode=ParseMode.HTML
    )

@router.message(Command("help"))
@router.message(F.text == "ℹ️ Yordam")
async def cmd_help(message: Message):
    await register_user(message)
    text = (
        "ℹ️ <b>Yordam</b>\n\n"
        "🔢 <b>Kod orqali</b> — kino kodini yuboring\n"
        "🔎 <b>Nom orqali</b> — kino nomini yozing\n"
        "🎭 <b>Janr</b> — janr bo‘yicha qidirish\n"
        "🔥 <b>Mashhur</b> — eng ko‘p ko‘rilganlar\n"
        "❤️ <b>Sevimlilar</b> — o‘zingiz tanlaganlar\n\n"
        f"Savollar: {SUPPORT_USERNAME}"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery, bot: Bot):
    if await check_subscription(bot, callback.from_user.id):
        await callback.message.edit_text("✅ Obuna tasdiqlandi!")
        await callback.message.answer(
            "🎬 <b>Kino Bot</b>\n\nKerakli kinoni kod yoki nom orqali tez toping.",
            reply_markup=main_menu_kb(),
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer("❌ Siz hali kanalga obuna bo‘lmagansiz.", show_alert=True)
    await callback.answer()

@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🎬 Asosiy menyu",
        reply_markup=main_menu_kb()
    )
    await callback.answer()

# ---------- SEARCH BY CODE ----------
@router.message(F.text == "🔢 Kod orqali qidirish")
async def search_by_code_start(message: Message, state: FSMContext, bot: Bot):
    await register_user(message)
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("📢 Kanalga obuna bo‘ling.", reply_markup=force_sub_kb())
        return
    await state.set_state(SearchCode.waiting)
    await message.answer("Kino kodini yuboring:", reply_markup=cancel_kb())

@router.message(SearchCode.waiting)
async def search_by_code_process(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    code = message.text.strip()
    movie = await get_movie_by_code(code)
    if not movie:
        await message.answer("❌ Kino topilmadi. Boshqa kod yuboring yoki bekor qiling.")
        return
    await state.clear()
    is_fav = await is_favorite(message.from_user.id, movie["id"])
    await message.answer(
        format_movie_card(movie),
        reply_markup=movie_actions_kb(movie["id"], is_fav),
        parse_mode=ParseMode.HTML
    )

# ---------- SEARCH BY TITLE ----------
@router.message(F.text == "🎬 Kino qidirish")
async def search_by_title_start(message: Message, state: FSMContext, bot: Bot):
    await register_user(message)
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("📢 Kanalga obuna bo‘ling.", reply_markup=force_sub_kb())
        return
    await state.set_state(SearchTitle.waiting)
    await message.answer("Kino nomini yozing:", reply_markup=cancel_kb())

@router.message(SearchTitle.waiting)
async def search_by_title_process(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    query = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM movies
               WHERE title LIKE ? OR alternative_title LIKE ?
               ORDER BY views DESC LIMIT 20""",
            (f"%{query}%", f"%{query}%")
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("❌ Hech narsa topilmadi. Boshqa nom yuboring.")
        return
    await state.clear()
    if len(rows) == 1:
        movie = dict(rows[0])
        is_fav = await is_favorite(message.from_user.id, movie["id"])
        await message.answer(
            format_movie_card(movie),
            reply_markup=movie_actions_kb(movie["id"], is_fav),
            parse_mode=ParseMode.HTML
        )
    else:
        text = "🔍 Topilgan kinolar:\n\n"
        buttons = []
        for r in rows:
            text += f"🎬 {r['title']} ({r['year'] or '—'})\n"
            buttons.append([InlineKeyboardButton(
                text=f"{r['title'][:30]}",
                callback_data=f"movie_{r['id']}"
            )])
        buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")])
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("movie_"))
async def show_movie_callback(callback: CallbackQuery):
    movie_id = int(callback.data.split("_")[1])
    movie = await get_movie_by_id(movie_id)
    if not movie:
        await callback.answer("Kino topilmadi", show_alert=True)
        return
    is_fav = await is_favorite(callback.from_user.id, movie_id)
    await callback.message.answer(
        format_movie_card(movie),
        reply_markup=movie_actions_kb(movie_id, is_fav),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

# ---------- WATCH MOVIE ----------
@router.callback_query(F.data.startswith("watch_"))
async def watch_movie(callback: CallbackQuery, bot: Bot):
    movie_id = int(callback.data.split("_")[1])
    movie = await get_movie_by_id(movie_id)
    if not movie:
        await callback.answer("Kino topilmadi", show_alert=True)
        return
    await increment_views(movie_id)
    try:
        await bot.copy_message(
            chat_id=callback.from_user.id,
            from_chat_id=movie["channel_id"],
            message_id=movie["message_id"]
        )
        await callback.answer("Kino yuborildi ✅")
    except TelegramForbiddenError:
        await callback.answer("Botni bloklagansiz yoki xato", show_alert=True)
    except TelegramBadRequest as e:
        logger.error(f"Copy message error: {e}")
        await callback.answer("Kino xabari topilmadi yoki o‘chirilgan", show_alert=True)
    except Exception as e:
        logger.error(f"Watch error: {e}")
        await callback.answer("Xatolik yuz berdi", show_alert=True)

# ---------- FAVORITES ----------
@router.callback_query(F.data.startswith("fav_"))
async def add_favorite(callback: CallbackQuery):
    movie_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT OR IGNORE INTO favorites (telegram_id, movie_id) VALUES (?, ?)",
                (callback.from_user.id, movie_id)
            )
            await db.commit()
            await callback.answer("❤️ Sevimlilarga qo‘shildi")
        except Exception:
            await callback.answer("Xato", show_alert=True)
    # Refresh keyboard
    is_fav = True
    movie = await get_movie_by_id(movie_id)
    if movie:
        await callback.message.edit_reply_markup(reply_markup=movie_actions_kb(movie_id, is_fav))

@router.callback_query(F.data.startswith("unfav_"))
async def remove_favorite(callback: CallbackQuery):
    movie_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM favorites WHERE telegram_id = ? AND movie_id = ?",
            (callback.from_user.id, movie_id)
        )
        await db.commit()
    await callback.answer("💔 Olib tashlandi")
    movie = await get_movie_by_id(movie_id)
    if movie:
        await callback.message.edit_reply_markup(reply_markup=movie_actions_kb(movie_id, False))

@router.message(F.text == "❤️ Sevimlilar")
async def show_favorites(message: Message, bot: Bot):
    await register_user(message)
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("📢 Kanalga obuna bo‘ling.", reply_markup=force_sub_kb())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT m.* FROM movies m
            JOIN favorites f ON m.id = f.movie_id
            WHERE f.telegram_id = ?
            ORDER BY m.title
        """, (message.from_user.id,)) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("❤️ Sevimlilar bo‘sh.", reply_markup=main_menu_kb())
        return
    text = "❤️ <b>Sevimlilaringiz:</b>\n\n"
    buttons = []
    for r in rows:
        text += f"🎬 {r['title']}\n"
        buttons.append([InlineKeyboardButton(text=r["title"][:40], callback_data=f"movie_{r['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)

# ---------- GENRES ----------
@router.message(F.text == "🎭 Janrlar")
async def show_genres(message: Message, bot: Bot):
    await register_user(message)
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("📢 Kanalga obuna bo‘ling.", reply_markup=force_sub_kb())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM genres ORDER BY name") as cur:
            genres = [row[0] for row in await cur.fetchall()]
    if not genres:
        await message.answer("Janrlar yo‘q.")
        return
    await message.answer("🎭 Janrni tanlang:", reply_markup=genres_kb(genres))

@router.callback_query(F.data.startswith("genre_"))
async def genre_movies(callback: CallbackQuery):
    genre = callback.data[6:]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM movies WHERE genre LIKE ? ORDER BY views DESC LIMIT 30",
            (f"%{genre}%",)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await callback.answer("Bu janrda kino yo‘q", show_alert=True)
        return
    text = f"🎭 <b>{genre}</b>\n\n"
    buttons = []
    for r in rows:
        text += f"🎬 {r['title']} ({r['year'] or '—'})\n"
        buttons.append([InlineKeyboardButton(text=r["title"][:35], callback_data=f"movie_{r['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")])
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    await callback.answer()

# ---------- POPULAR & NEW ----------
@router.message(F.text == "🔥 Eng ko‘p ko‘rilgan")
async def popular_movies(message: Message, bot: Bot):
    await register_user(message)
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("📢 Kanalga obuna bo‘ling.", reply_markup=force_sub_kb())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM movies ORDER BY views DESC LIMIT 10"
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("Hali kino yo‘q.")
        return
    text = "🔥 <b>TOP 10</b>\n\n"
    buttons = []
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r['title']} — {r['views']:,} views\n"
        buttons.append([InlineKeyboardButton(text=f"{i}. {r['title'][:30]}", callback_data=f"movie_{r['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)

@router.message(F.text == "🆕 Yangi kinolar")
async def new_movies(message: Message, bot: Bot):
    await register_user(message)
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("📢 Kanalga obuna bo‘ling.", reply_markup=force_sub_kb())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM movies ORDER BY created_at DESC LIMIT 15"
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("Hali kino yo‘q.")
        return
    text = "🆕 <b>Yangi kinolar</b>\n\n"
    buttons = []
    for r in rows:
        text += f"🎬 {r['title']} ({r['year'] or '—'})\n"
        buttons.append([InlineKeyboardButton(text=r["title"][:35], callback_data=f"movie_{r['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)

# ==================== ADMIN ====================
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👨‍💻 <b>ADMIN PANEL</b>", reply_markup=admin_menu_kb(), parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "admin_add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddMovie.code)
    await callback.message.answer("1️⃣ Kino kodini yuboring:", reply_markup=cancel_kb())
    await callback.answer()

@router.message(AddMovie.code)
async def add_code(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    code = message.text.strip()
    if await get_movie_by_code(code):
        await message.answer("❌ Bu kod allaqachon mavjud. Boshqa kod yuboring.")
        return
    await state.update_data(code=code)
    await state.set_state(AddMovie.title)
    await message.answer("2️⃣ Kino nomini yuboring:")

@router.message(AddMovie.title)
async def add_title(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(AddMovie.alt_title)
    await message.answer("3️⃣ Muqobil nomini yuboring (yoki «-»):")

@router.message(AddMovie.alt_title)
async def add_alt(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    alt = message.text.strip() if message.text.strip() != "-" else None
    await state.update_data(alternative_title=alt)
    await state.set_state(AddMovie.description)
    await message.answer("4️⃣ Tavsifni yuboring (yoki «-»):")

@router.message(AddMovie.description)
async def add_desc(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    desc = message.text.strip() if message.text.strip() != "-" else None
    await state.update_data(description=desc)
    await state.set_state(AddMovie.year)
    await message.answer("5️⃣ Yilini yuboring (masalan 2022 yoki «-»):")

@router.message(AddMovie.year)
async def add_year(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    year = None
    if message.text.strip() != "-":
        try:
            year = int(message.text.strip())
        except ValueError:
            await message.answer("Noto‘g‘ri yil. Raqam yuboring yoki «-»:")
            return
    await state.update_data(year=year)
    await state.set_state(AddMovie.genre)
    await message.answer("6️⃣ Janrini yuboring (masalan Action, Comedy...):")

@router.message(AddMovie.genre)
async def add_genre(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    await state.update_data(genre=message.text.strip())
    await state.set_state(AddMovie.rating)
    await message.answer("7️⃣ Reytingini yuboring (masalan 8.5 yoki «-»):")

@router.message(AddMovie.rating)
async def add_rating(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    rating = None
    if message.text.strip() != "-":
        try:
            rating = float(message.text.strip().replace(",", "."))
        except ValueError:
            await message.answer("Noto‘g‘ri reyting. Raqam yuboring yoki «-»:")
            return
    await state.update_data(rating=rating)
    await state.set_state(AddMovie.channel_id)
    await message.answer("8️⃣ Channel ID yuboring (masalan -1001234567890):")

@router.message(AddMovie.channel_id)
async def add_channel(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    try:
        ch_id = int(message.text.strip())
    except ValueError:
        await message.answer("Noto‘g‘ri Channel ID. Raqam yuboring:")
        return
    await state.update_data(channel_id=ch_id)
    await state.set_state(AddMovie.message_id)
    await message.answer("9️⃣ Message ID yuboring (masalan 532):")

@router.message(AddMovie.message_id)
async def add_message_id(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    try:
        msg_id = int(message.text.strip())
    except ValueError:
        await message.answer("Noto‘g‘ri Message ID. Raqam yuboring:")
        return
    data = await state.get_data()
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("""
                INSERT INTO movies (code, title, alternative_title, description, year, genre, rating, channel_id, message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["code"], data["title"], data.get("alternative_title"),
                data.get("description"), data.get("year"), data.get("genre"),
                data.get("rating"), data["channel_id"], msg_id
            ))
            await db.commit()
            await message.answer(
                f"✅ Kino qo‘shildi!\n\nKod: {data['code']}\nNomi: {data['title']}",
                reply_markup=main_menu_kb()
            )
        except aiosqlite.IntegrityError:
            await message.answer("❌ Bu kod allaqachon mavjud.", reply_markup=main_menu_kb())
        except Exception as e:
            logger.error(e)
            await message.answer("❌ Xatolik yuz berdi.", reply_markup=main_menu_kb())

# Fast add via reply to channel message
@router.message(Command("add"))
async def fast_add_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.reply_to_message:
        await message.answer(
            "Kanal xabariga reply qilib /add yuboring.\n"
            "Keyin faqat kod, nom, tavsif, yil, janr, reyting so‘raladi."
        )
        return
    replied = message.reply_to_message
    chat_id = replied.chat.id
    msg_id = replied.message_id
    await state.update_data(channel_id=chat_id, message_id=msg_id)
    await state.set_state(FastAddMovie.code)
    await message.answer("1️⃣ Kino kodini yuboring:", reply_markup=cancel_kb())

@router.message(FastAddMovie.code)
async def fast_code(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    code = message.text.strip()
    if await get_movie_by_code(code):
        await message.answer("❌ Bu kod allaqachon mavjud.")
        return
    await state.update_data(code=code)
    await state.set_state(FastAddMovie.title)
    await message.answer("2️⃣ Kino nomini yuboring:")

@router.message(FastAddMovie.title)
async def fast_title(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(FastAddMovie.description)
    await message.answer("3️⃣ Tavsifni yuboring (yoki «-»):")

@router.message(FastAddMovie.description)
async def fast_desc(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    desc = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(description=desc)
    await state.set_state(FastAddMovie.year)
    await message.answer("4️⃣ Yilini yuboring (yoki «-»):")

@router.message(FastAddMovie.year)
async def fast_year(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    year = None
    if message.text.strip() != "-":
        try:
            year = int(message.text.strip())
        except ValueError:
            await message.answer("Noto‘g‘ri yil.")
            return
    await state.update_data(year=year)
    await state.set_state(FastAddMovie.genre)
    await message.answer("5️⃣ Janrini yuboring:")

@router.message(FastAddMovie.genre)
async def fast_genre(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    await state.update_data(genre=message.text.strip())
    await state.set_state(FastAddMovie.rating)
    await message.answer("6️⃣ Reytingini yuboring (yoki «-»):")

@router.message(FastAddMovie.rating)
async def fast_rating(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())
        return
    rating = None
    if message.text.strip() != "-":
        try:
            rating = float(message.text.strip().replace(",", "."))
        except ValueError:
            await message.answer("Noto‘g‘ri reyting.")
            return
    data = await state.get_data()
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("""
                INSERT INTO movies (code, title, description, year, genre, rating, channel_id, message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["code"], data["title"], data.get("description"),
                data.get("year"), data.get("genre"), rating,
                data["channel_id"], data["message_id"]
            ))
            await db.commit()
            await message.answer(
                f"✅ Kino tez qo‘shildi!\nKod: {data['code']}\nNomi: {data['title']}",
                reply_markup=main_menu_kb()
            )
        except Exception as e:
            logger.error(e)
            await message.answer("❌ Xatolik.", reply_markup=main_menu_kb())

# Admin list / stats / users / delete / broadcast
@router.callback_query(F.data == "admin_list")
@router.message(Command("movies"))
async def admin_list(event: Message | CallbackQuery):
    user_id = event.from_user.id if isinstance(event, Message) else event.from_user.id
    if not is_admin(user_id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, code, title, views FROM movies ORDER BY id DESC LIMIT 50") as cur:
            rows = await cur.fetchall()
    text = "📋 <b>Kinolar (oxirgi 50)</b>\n\n"
    for r in rows:
        text += f"#{r['id']} | {r['code']} | {r['title']} | 👀 {r['views']}\n"
    if isinstance(event, CallbackQuery):
        await event.message.answer(text or "Bo‘sh", parse_mode=ParseMode.HTML)
        await event.answer()
    else:
        await event.answer(text or "Bo‘sh", parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "admin_stats")
@router.message(Command("stats"))
async def admin_stats(event: Message | CallbackQuery):
    user_id = event.from_user.id if isinstance(event, Message) else event.from_user.id
    if not is_admin(user_id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            users = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM movies") as cur:
            movies = (await cur.fetchone())[0]
        async with db.execute("SELECT SUM(views) FROM movies") as cur:
            views = (await cur.fetchone())[0] or 0
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE date(last_activity) = date('now')"
        ) as cur:
            today = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT title, views FROM movies ORDER BY views DESC LIMIT 1"
        ) as cur:
            top = await cur.fetchone()
    top_text = f"{top[0]} ({top[1]} views)" if top else "—"
    text = (
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Jami foydalanuvchilar: {users}\n"
        f"🎬 Jami kinolar: {movies}\n"
        f"👀 Jami ko‘rishlar: {views:,}\n"
        f"🟢 Bugungi faol: {today}\n"
        f"🔥 Eng ko‘p ko‘rilgan: {top_text}"
    )
    if isinstance(event, CallbackQuery):
        await event.message.answer(text, parse_mode=ParseMode.HTML)
        await event.answer()
    else:
        await event.answer(text, parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "admin_users")
@router.message(Command("users"))
async def admin_users(event: Message | CallbackQuery):
    user_id = event.from_user.id if isinstance(event, Message) else event.from_user.id
    if not is_admin(user_id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1") as cur:
            blocked = (await cur.fetchone())[0]
    text = f"👥 Foydalanuvchilar: {total}\n🚫 Bloklagan: {blocked}"
    if isinstance(event, CallbackQuery):
        await event.message.answer(text)
        await event.answer()
    else:
        await event.answer(text)

@router.callback_query(F.data == "admin_delete")
async def admin_delete_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer("O‘chirmoqchi bo‘lgan kino kodini yuboring:")
    await state.set_state(AdminDelete.confirm)
    await callback.answer()

@router.message(AdminDelete.confirm)
async def admin_delete_confirm(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip()
    movie = await get_movie_by_code(code)
    if not movie:
        await message.answer("Kino topilmadi.")
        await state.clear()
        return
    await state.update_data(movie_id=movie["id"])
    await message.answer(
        f"⚠️ Rostdan ham o‘chirmoqchimisiz?\n\n🎬 {movie['title']} (kod: {code})",
        reply_markup=confirm_delete_kb(movie["id"])
    )

@router.callback_query(F.data.startswith("del_yes_"))
async def del_yes(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    movie_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM favorites WHERE movie_id = ?", (movie_id,))
        await db.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
        await db.commit()
    await state.clear()
    await callback.message.edit_text("✅ Kino o‘chirildi.")
    await callback.answer()

@router.callback_query(F.data == "del_no")
async def del_no(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Bekor qilindi.")
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
@router.message(Command("broadcast"))
async def broadcast_start(event: Message | CallbackQuery, state: FSMContext):
    user_id = event.from_user.id if isinstance(event, Message) else event.from_user.id
    if not is_admin(user_id):
        return
    await state.set_state(Broadcast.waiting)
    text = "📢 Reklama xabarini yuboring (matn, rasm, video...).\nBekor qilish uchun /cancel"
    if isinstance(event, CallbackQuery):
        await event.message.answer(text)
        await event.answer()
    else:
        await event.answer(text)

@router.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=main_menu_kb())

@router.message(Broadcast.waiting)
async def broadcast_process(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM users WHERE is_blocked = 0") as cur:
            users = [row[0] for row in await cur.fetchall()]
    success = 0
    failed = 0
    blocked = 0
    for uid in users:
        try:
            if message.photo:
                await bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                await bot.send_video(uid, message.video.file_id, caption=message.caption)
            elif message.document:
                await bot.send_document(uid, message.document.file_id, caption=message.caption)
            else:
                await bot.send_message(uid, message.text or message.caption or "")
            success += 1
            await asyncio.sleep(0.05)  # soft rate limit
        except TelegramForbiddenError:
            blocked += 1
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE telegram_id = ?", (uid,))
                await db.commit()
        except Exception as e:
            failed += 1
            logger.warning(f"Broadcast fail {uid}: {e}")
    await message.answer(
        f"📢 Reklama yakunlandi\n\n"
        f"✅ Yuborildi: {success}\n"
        f"❌ Xatolik: {failed}\n"
        f"🚫 Bloklagan: {blocked}"
    )

@router.callback_query(F.data == "admin_force_sub")
async def admin_force_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer(
        f"📢 Majburiy obuna kanali: {CHANNEL_ID}\n\n"
        "Bot ushbu kanalning administratorida bo‘lishi kerak "
        "(a'zolarni ko‘rish huquqi bilan), aks holda tekshiruv ishlamaydi."
    )
    await callback.answer()

@router.callback_query(F.data == "admin_settings")
async def admin_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer(
        f"⚙️ Sozlamalar\n\n"
        f"BOT_TOKEN: {'sozlangan' if BOT_TOKEN != 'PUT_BOT_TOKEN_HERE' else 'sozlanmagan'}\n"
        f"ADMIN_IDS: {ADMIN_IDS}\n"
        f"CHANNEL_ID: {CHANNEL_ID}\n"
        f"SUPPORT: {SUPPORT_USERNAME}"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_edit")
async def admin_edit_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer(
        "✏️ Tahrirlash uchun:\n"
        "1. /movies bilan kodni toping\n"
        "2. Hozircha oddiy tahrirlash: o‘chirib qayta qo‘shing yoki /add orqali yangilang.\n"
        "(To‘liq interaktiv tahrirlash keyingi versiyada kengaytirilishi mumkin)"
    )
    await callback.answer()

# Catch-all for unknown text when not in state (optional search)
@router.message(F.text)
async def fallback_text(message: Message, state: FSMContext, bot: Bot):
    current = await state.get_state()
    if current is not None:
        return
    await register_user(message)
    if not await check_subscription(bot, message.from_user.id):
        await message.answer("📢 Kanalga obuna bo‘ling.", reply_markup=force_sub_kb())
        return
    # Treat as title search
    query = message.text.strip()
    if len(query) < 2:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM movies
               WHERE title LIKE ? OR alternative_title LIKE ? OR code = ?
               ORDER BY views DESC LIMIT 15""",
            (f"%{query}%", f"%{query}%", query)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("Hech narsa topilmadi. Menyudan foydalaning.", reply_markup=main_menu_kb())
        return
    if len(rows) == 1:
        movie = dict(rows[0])
        is_fav = await is_favorite(message.from_user.id, movie["id"])
        await message.answer(
            format_movie_card(movie),
            reply_markup=movie_actions_kb(movie["id"], is_fav),
            parse_mode=ParseMode.HTML
        )
    else:
        text = "🔍 Natijalar:\n\n"
        buttons = []
        for r in rows:
            text += f"🎬 {r['title']}\n"
            buttons.append([InlineKeyboardButton(text=r["title"][:35], callback_data=f"movie_{r['id']}")])
        buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")])
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# ==================== MAIN ====================
async def main():
    if BOT_TOKEN == "PUT_BOT_TOKEN_HERE" or not BOT_TOKEN:
        print("=" * 60)
        print("ERROR: BOT_TOKEN is not set!")
        print("1. Open main.py and replace PUT_BOT_TOKEN_HERE")
        print("2. Or create .env file with: BOT_TOKEN=your_token")
        print("3. Also set ADMIN_IDS and CHANNEL_ID")
        print("=" * 60)
        return

    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
