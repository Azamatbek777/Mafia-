import os
import asyncio
import logging
import sqlite3

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from dotenv import load_dotenv


# =========================================================
# ENV
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
}

CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()

FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "").strip()
FORCE_SUB_LINK = os.getenv("FORCE_SUB_LINK", "").strip()

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip()

PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN .env da topilmadi!")

if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS .env da topilmadi!")


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


# =========================================================
# BOT
# =========================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

DB_NAME = "kino_bot.db"


def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            title TEXT NOT NULL,
            alt_title TEXT,
            year TEXT,
            genre TEXT,
            rating TEXT,
            description TEXT,
            channel_message_id INTEGER,
            views INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            movie_id INTEGER,
            UNIQUE(user_id, movie_id)
        )
    """)

    conn.commit()
    conn.close()


def save_user(message: Message):
    if not message.from_user:
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO users
        (user_id, username, first_name)
        VALUES (?, ?, ?)
    """, (
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    ))

    conn.commit()
    conn.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================================================
# FORCE SUB
# =========================================================

async def check_subscription(user_id: int) -> bool:

    # Majburiy obuna o'chirilgan bo'lsa
    if not FORCE_SUB_CHANNEL:
        return True

    try:
        member = await bot.get_chat_member(
            chat_id=FORCE_SUB_CHANNEL,
            user_id=user_id
        )

        return member.status in {
            "creator",
            "administrator",
            "member"
        }

    except Exception as e:
        logger.warning(
            "Subscription check error: %s",
            e
        )

        # Agar kanal noto'g'ri sozlangan bo'lsa,
        # bot butunlay ishlamay qolmasligi uchun False qaytaramiz.
        return False


def subscription_keyboard():

    buttons = []

    if FORCE_SUB_LINK:
        buttons.append([
            InlineKeyboardButton(
                text="📢 Kanalga obuna bo‘lish",
                url=FORCE_SUB_LINK
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_sub"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def require_subscription(message: Message) -> bool:

    if is_admin(message.from_user.id):
        return True

    subscribed = await check_subscription(
        message.from_user.id
    )

    if not subscribed:

        await message.answer(
            "🔒 <b>Botdan foydalanish uchun kanalga obuna bo‘ling.</b>\n\n"
            "1️⃣ Kanalga kiring\n"
            "2️⃣ Obuna bo‘ling\n"
            "3️⃣ «Obunani tekshirish» tugmasini bosing",
            reply_markup=subscription_keyboard()
        )

        return False

    return True


# =========================================================
# KEYBOARD
# =========================================================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🔎 Kino qidirish"),
            KeyboardButton(text="🎬 Top kinolar")
        ],
        [
            KeyboardButton(text="🆕 Yangi kinolar"),
            KeyboardButton(text="📚 Janrlar")
        ],
        [
            KeyboardButton(text="❤️ Sevimlilar"),
            KeyboardButton(text="ℹ️ Yordam")
        ]
    ],
    resize_keyboard=True
)


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):

    save_user(message)

    if not await require_subscription(message):
        return

    await message.answer(
        f"🎬 <b>Assalomu alaykum, {message.from_user.first_name}!</b>\n\n"
        "Kino qidirish uchun kod yoki kino nomini yuboring.",
        reply_markup=main_keyboard
    )


# =========================================================
# CHECK SUB CALLBACK
# =========================================================

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):

    subscribed = await check_subscription(
        callback.from_user.id
    )

    if subscribed:

        await callback.message.edit_text(
            "✅ <b>Obuna tasdiqlandi!</b>\n\n"
            "Endi botdan foydalanishingiz mumkin."
        )

        await callback.message.answer(
            "🎬 Bosh menyu",
            reply_markup=main_keyboard
        )

    else:

        await callback.answer(
            "❌ Siz hali kanalga obuna bo‘lmagansiz.",
            show_alert=True
        )


# =========================================================
# SEARCH
# =========================================================

async def search_movie(query: str):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, code, title, alt_title, year,
               genre, rating, description,
               channel_message_id, views
        FROM movies
        WHERE code = ?
           OR LOWER(title) LIKE LOWER(?)
           OR LOWER(COALESCE(alt_title, '')) LIKE LOWER(?)
        ORDER BY views DESC
        LIMIT 10
    """, (
        query,
        f"%{query}%",
        f"%{query}%"
    ))

    results = cur.fetchall()

    conn.close()

    return results


def movie_keyboard(movie_id: int):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶️ Ko‘rish",
                    callback_data=f"watch:{movie_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❤️ Sevimliga qo‘shish",
                    callback_data=f"fav:{movie_id}"
                )
            ]
        ]
    )


def movie_text(movie):

    (
        movie_id,
        code,
        title,
        alt_title,
        year,
        genre,
        rating,
        description,
        channel_message_id,
        views
    ) = movie

    text = f"🎬 <b>{title}</b>\n\n"

    if alt_title:
        text += f"🌐 Boshqa nomi: {alt_title}\n"

    if year:
        text += f"📅 Yil: {year}\n"

    if genre:
        text += f"🎭 Janr: {genre}\n"

    if rating:
        text += f"⭐ Reyting: {rating}\n"

    if description:
        text += f"\n📝 {description}\n"

    text += f"\n👁 Ko‘rishlar: {views}"

    return text


@dp.message(F.text == "🔎 Kino qidirish")
async def search_button(message: Message):

    if not await require_subscription(message):
        return

    await message.answer(
        "🔎 Kino kodi yoki nomini yuboring."
    )


@dp.message()
async def search_handler(message: Message):

    if not message.text:
        return

    if message.text.startswith("/"):
        return

    if message.text in {
        "🎬 Top kinolar",
        "🆕 Yangi kinolar",
        "📚 Janrlar",
        "❤️ Sevimlilar",
        "ℹ️ Yordam"
    }:
        return

    if not await require_subscription(message):
        return

    query = message.text.strip()

    results = await search_movie(query)

    if not results:
        await message.answer(
            "❌ Kino topilmadi.\n\n"
            "Kino kodi yoki nomini tekshirib qayta yuboring."
        )
        return

    for movie in results:

        await message.answer(
            movie_text(movie),
            reply_markup=movie_keyboard(movie[0])
        )


# =========================================================
# WATCH
# =========================================================

@dp.callback_query(F.data.startswith("watch:"))
async def watch_movie(callback: CallbackQuery):

    if not await check_subscription(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Avval kanalga obuna bo‘ling.",
            show_alert=True
        )
        return

    movie_id = int(
        callback.data.split(":")[1]
    )

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT channel_message_id
        FROM movies
        WHERE id = ?
    """, (movie_id,))

    result = cur.fetchone()

    if not result:
        conn.close()

        await callback.answer(
            "❌ Kino topilmadi.",
            show_alert=True
        )
        return

    channel_message_id = result[0]

    cur.execute("""
        UPDATE movies
        SET views = views + 1
        WHERE id = ?
    """, (movie_id,))

    conn.commit()
    conn.close()

    try:

        await bot.copy_message(
            chat_id=callback.from_user.id,
            from_chat_id=CHANNEL_ID,
            message_id=channel_message_id
        )

        await callback.answer()

    except Exception as e:

        logger.error(
            "Kino yuborishda xato: %s",
            e
        )

        await callback.answer(
            "❌ Kinoni yuborishda xatolik.",
            show_alert=True
        )


# =========================================================
# FAVORITE
# =========================================================

@dp.callback_query(F.data.startswith("fav:"))
async def favorite_movie(callback: CallbackQuery):

    movie_id = int(
        callback.data.split(":")[1]
    )

    user_id = callback.from_user.id

    conn = db()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO favorites
            (user_id, movie_id)
            VALUES (?, ?)
        """, (
            user_id,
            movie_id
        ))

        conn.commit()

        await callback.answer(
            "❤️ Sevimlilarga qo‘shildi!"
        )

    except sqlite3.IntegrityError:

        await callback.answer(
            "❤️ Bu kino allaqachon sevimlilarda."
        )

    finally:
        conn.close()


# =========================================================
# TOP
# =========================================================

@dp.message(F.text == "🎬 Top kinolar")
async def top_movies(message: Message):

    if not await require_subscription(message):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, code, title, alt_title,
               year, genre, rating,
               description, channel_message_id, views
        FROM movies
        ORDER BY views DESC
        LIMIT 10
    """)

    movies = cur.fetchall()
    conn.close()

    if not movies:

        await message.answer(
            "❌ Hozircha kinolar yo‘q."
        )
        return

    await message.answer("🎬 <b>TOP kinolar</b>")

    for movie in movies:

        await message.answer(
            movie_text(movie),
            reply_markup=movie_keyboard(movie[0])
        )


# =========================================================
# NEW
# =========================================================

@dp.message(F.text == "🆕 Yangi kinolar")
async def new_movies(message: Message):

    if not await require_subscription(message):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, code, title, alt_title,
               year, genre, rating,
               description, channel_message_id, views
        FROM movies
        ORDER BY id DESC
        LIMIT 10
    """)

    movies = cur.fetchall()
    conn.close()

    if not movies:

        await message.answer(
            "❌ Hozircha kinolar yo‘q."
        )
        return

    await message.answer("🆕 <b>Yangi kinolar</b>")

    for movie in movies:

        await message.answer(
            movie_text(movie),
            reply_markup=movie_keyboard(movie[0])
        )


# =========================================================
# GENRES
# =========================================================

@dp.message(F.text == "📚 Janrlar")
async def genres(message: Message):

    if not await require_subscription(message):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT genre
        FROM movies
        WHERE genre IS NOT NULL
        AND genre != ''
        ORDER BY genre
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:

        await message.answer(
            "❌ Janrlar hali mavjud emas."
        )
        return

    buttons = []

    for row in rows:

        genre = row[0]

        buttons.append([
            InlineKeyboardButton(
                text=f"🎭 {genre}",
                callback_data=f"genre:{genre}"
            )
        ])

    await message.answer(
        "📚 <b>Janrlar:</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@dp.callback_query(F.data.startswith("genre:"))
async def genre_callback(callback: CallbackQuery):

    genre = callback.data.split(":", 1)[1]

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, code, title, alt_title,
               year, genre, rating,
               description, channel_message_id, views
        FROM movies
        WHERE genre = ?
        ORDER BY id DESC
    """, (genre,))

    movies = cur.fetchall()
    conn.close()

    if not movies:

        await callback.answer(
            "Bu janrda kino yo‘q.",
            show_alert=True
        )
        return

    await callback.message.answer(
        f"🎭 <b>{genre}</b>"
    )

    for movie in movies:

        await callback.message.answer(
            movie_text(movie),
            reply_markup=movie_keyboard(movie[0])
        )

    await callback.answer()


# =========================================================
# FAVORITES
# =========================================================

@dp.message(F.text == "❤️ Sevimlilar")
async def favorites(message: Message):

    if not await require_subscription(message):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT m.id, m.code, m.title,
               m.alt_title, m.year, m.genre,
               m.rating, m.description,
               m.channel_message_id, m.views
        FROM movies m
        INNER JOIN favorites f
        ON m.id = f.movie_id
        WHERE f.user_id = ?
        ORDER BY m.id DESC
    """, (
        message.from_user.id,
    ))

    movies = cur.fetchall()
    conn.close()

    if not movies:

        await message.answer(
            "❤️ Sevimlilar ro‘yxati bo‘sh."
        )
        return

    for movie in movies:

        await message.answer(
            movie_text(movie),
            reply_markup=movie_keyboard(movie[0])
        )


# =========================================================
# HELP
# =========================================================

@dp.message(F.text == "ℹ️ Yordam")
async def help_handler(message: Message):

    text = (
        "ℹ️ <b>Botdan foydalanish</b>\n\n"
        "🔎 Kino kodi yoki nomini yuboring.\n"
        "🎬 TOP — eng ko‘p ko‘rilgan kinolar.\n"
        "🆕 Yangi — yangi qo‘shilgan kinolar.\n"
        "📚 Janrlar — janr bo‘yicha qidirish.\n"
        "❤️ Sevimlilar — saqlangan kinolar."
    )

    if SUPPORT_USERNAME:
        text += f"\n\n💬 Yordam: {SUPPORT_USERNAME}"

    await message.answer(text)


# =========================================================
# ADMIN PANEL
# =========================================================

class AddMovie(StatesGroup):
    code = State()
    title = State()
    alt_title = State()
    year = State()
    genre = State()
    rating = State()
    description = State()
    channel_message_id = State()


class Broadcast(StatesGroup):
    message = State()


def admin_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Kino qo‘shish",
                    callback_data="admin_add"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Statistika",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎬 Kinolar",
                    callback_data="admin_movies"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Reklama yuborish",
                    callback_data="admin_broadcast"
                )
            ]
        ]
    )


@dp.message(Command("admin"))
@dp.message(Command("panel"))
async def admin_panel(message: Message):

    if not is_admin(message.from_user.id):
        await message.answer("❌ Siz admin emassiz.")
        return

    await message.answer(
        "⚙️ <b>Admin panel</b>",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADD MOVIE
# =========================================================

@dp.callback_query(F.data == "admin_add")
async def admin_add(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user.id):
        return

    await state.set_state(AddMovie.code)

    await callback.message.answer(
        "➕ Kino kodi:"
    )

    await callback.answer()


@dp.message(AddMovie.code)
async def add_code(message: Message, state: FSMContext):

    await state.update_data(
        code=message.text.strip()
    )

    await state.set_state(AddMovie.title)

    await message.answer(
        "🎬 Kino nomi:"
    )


@dp.message(AddMovie.title)
async def add_title(message: Message, state: FSMContext):

    await state.update_data(
        title=message.text.strip()
    )

    await state.set_state(AddMovie.alt_title)

    await message.answer(
        "🌐 Boshqa nomi:\n"
        "Agar bo‘lmasa: -"
    )


@dp.message(AddMovie.alt_title)
async def add_alt_title(message: Message, state: FSMContext):

    value = message.text.strip()

    if value == "-":
        value = ""

    await state.update_data(
        alt_title=value
    )

    await state.set_state(AddMovie.year)

    await message.answer(
        "📅 Yili:"
    )


@dp.message(AddMovie.year)
async def add_year(message: Message, state: FSMContext):

    await state.update_data(
        year=message.text.strip()
    )

    await state.set_state(AddMovie.genre)

    await message.answer(
        "🎭 Janri:"
    )


@dp.message(AddMovie.genre)
async def add_genre(message: Message, state: FSMContext):

    await state.update_data(
        genre=message.text.strip()
    )

    await state.set_state(AddMovie.rating)

    await message.answer(
        "⭐ Reytingi:"
    )


@dp.message(AddMovie.rating)
async def add_rating(message: Message, state: FSMContext):

    await state.update_data(
        rating=message.text.strip()
    )

    await state.set_state(AddMovie.description)

    await message.answer(
        "📝 Tavsifi:"
    )


@dp.message(AddMovie.description)
async def add_description(message: Message, state: FSMContext):

    await state.update_data(
        description=message.text.strip()
    )

    await state.set_state(
        AddMovie.channel_message_id
    )

    await message.answer(
        "📨 Kanal postining Message ID sini yuboring.\n\n"
        "Masalan: 125"
    )


@dp.message(AddMovie.channel_message_id)
async def add_channel_message_id(
    message: Message,
    state: FSMContext
):

    try:
        channel_message_id = int(
            message.text.strip()
        )
    except ValueError:

        await message.answer(
            "❌ Faqat raqam yuboring."
        )
        return

    data = await state.get_data()

    conn = db()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO movies
            (
                code,
                title,
                alt_title,
                year,
                genre,
                rating,
                description,
                channel_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["code"],
            data["title"],
            data["alt_title"],
            data["year"],
            data["genre"],
            data["rating"],
            data["description"],
            channel_message_id
        ))

        conn.commit()

        await message.answer(
            "✅ <b>Kino muvaffaqiyatli qo‘shildi!</b>"
        )

    except sqlite3.IntegrityError:

        await message.answer(
            "❌ Bu kino kodi allaqachon mavjud."
        )

    finally:

        conn.close()
        await state.clear()


# =========================================================
# STATS
# =========================================================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM movies")
    movies = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(views), 0)
        FROM movies
    """)

    views = cur.fetchone()[0]

    conn.close()

    await callback.message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users}</b>\n"
        f"🎬 Kinolar: <b>{movies}</b>\n"
        f"👁 Ko‘rishlar: <b>{views}</b>"
    )

    await callback.answer()


# =========================================================
# MOVIES ADMIN
# =========================================================

@dp.callback_query(F.data == "admin_movies")
async def admin_movies(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, code, title, views
        FROM movies
        ORDER BY id DESC
    """)

    movies = cur.fetchall()
    conn.close()

    if not movies:

        await callback.message.answer(
            "🎬 Kinolar yo‘q."
        )
        return

    text = "🎬 <b>Kinolar:</b>\n\n"

    for movie_id, code, title, views in movies:

        text += (
            f"ID: <code>{movie_id}</code>\n"
            f"🔑 Kod: <code>{code}</code>\n"
            f"🎬 {title}\n"
            f"👁 {views}\n\n"
        )

    await callback.message.answer(text)
    await callback.answer()


# =========================================================
# COMMANDS
# =========================================================

@dp.message(Command("users"))
async def users_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]

    conn.close()

    await message.answer(
        f"👥 Foydalanuvchilar: <b>{count}</b>"
    )


@dp.message(Command("movies"))
async def movies_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM movies")
    count = cur.fetchone()[0]

    conn.close()

    await message.answer(
        f"🎬 Kinolar: <b>{count}</b>"
    )


@dp.message(Command("stats"))
async def stats_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM movies")
    movies = cur.fetchone()[0]

    cur.execute(
        "SELECT COALESCE(SUM(views), 0) FROM movies"
    )

    views = cur.fetchone()[0]

    conn.close()

    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Users: {users}\n"
        f"🎬 Movies: {movies}\n"
        f"👁 Views: {views}"
    )


@dp.message(Command("delmovie"))
async def delete_movie(message: Message):

    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "❌ Foydalanish:\n"
            "<code>/delmovie ID</code>"
        )
        return

    try:
        movie_id = int(parts[1])
    except ValueError:

        await message.answer(
            "❌ ID raqam bo‘lishi kerak."
        )
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM movies WHERE id = ?",
        (movie_id,)
    )

    deleted = cur.rowcount

    conn.commit()
    conn.close()

    if deleted:
        await message.answer(
            "✅ Kino o‘chirildi."
        )
    else:
        await message.answer(
            "❌ Bunday ID topilmadi."
        )


# =========================================================
# BROADCAST
# =========================================================

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(
    callback: CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):
        return

    await state.set_state(
        Broadcast.message
    )

    await callback.message.answer(
        "📢 Barcha foydalanuvchilarga yuboriladigan "
        "xabarni yuboring."
    )

    await callback.answer()


@dp.message(Broadcast.message)
async def broadcast_message(
    message: Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users"
    )

    users = cur.fetchall()
    conn.close()

    success = 0
    failed = 0

    for (user_id,) in users:

        try:

            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )

            success += 1

        except Exception:

            failed += 1

        await asyncio.sleep(0.05)

    await state.clear()

    await message.answer(
        f"📢 <b>Reklama tugadi</b>\n\n"
        f"✅ Yuborildi: {success}\n"
        f"❌ Xatolik: {failed}"
    )


# =========================================================
# HTTP SERVER
# =========================================================

async def health(request):

    return web.Response(
        text="Kino bot is running!"
    )


async def start_http_server():

    app = web.Application()

    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    logger.info(
        "HTTP server started on port %s",
        PORT
    )

    return runner


# =========================================================
# MAIN
# =========================================================

async def main():

    logger.info(
        "Bot ishga tushmoqda..."
    )

    init_db()

    http_runner = await start_http_server()

    try:

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )

    finally:

        await bot.session.close()

        await http_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
