import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage


# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = "7923870040:AAFAaupf6uqqN78JNLZroUId7ic_5j4u4-k"

# O'zingizning Telegram ID'ingiz
ADMIN_IDS = {
    6698039974
}

# Kino joylashtiriladigan kanal ID'si
# Masalan: -1001234567890
CHANNEL_ID = -2674674304

# Majburiy obuna kanali
FORCE_SUB_CHANNEL = "@Digital_UzIT"

# Majburiy obuna kanaliga havola
FORCE_SUB_LINK = "https://t.me/Digital_UzIT"

# Yordam uchun username
SUPPORT_USERNAME = "@azamat_x007"


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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


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
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            alt_title TEXT DEFAULT '',
            year INTEGER DEFAULT 0,
            genre TEXT DEFAULT '',
            rating TEXT DEFAULT '',
            description TEXT DEFAULT '',
            channel_message_id INTEGER NOT NULL,
            views INTEGER DEFAULT 0,
            created_at TEXT
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


# =========================================================
# USER
# =========================================================

def save_user(message: Message):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO users
        (id, username, first_name, joined_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.first_name or "",
            datetime.now().isoformat()
        )
    )

    cur.execute(
        """
        UPDATE users
        SET username = ?, first_name = ?
        WHERE id = ?
        """,
        (
            message.from_user.username or "",
            message.from_user.first_name or "",
            message.from_user.id
        )
    )

    conn.commit()
    conn.close()


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id: int):
    return user_id in ADMIN_IDS


# =========================================================
# FORCE SUBSCRIPTION
# =========================================================

async def check_subscription(user_id: int):
    try:
        member = await bot.get_chat_member(
            FORCE_SUB_CHANNEL,
            user_id
        )

        return member.status in [
            "member",
            "administrator",
            "creator"
        ]

    except Exception as e:
        logger.warning(f"Subscription check error: {e}")
        return False


def subscription_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Kanalga obuna bo‘lish",
                    url=FORCE_SUB_LINK
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Tekshirish",
                    callback_data="check_sub"
                )
            ]
        ]
    )


# =========================================================
# MAIN KEYBOARD
# =========================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
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

@dp.message(Command("start"))
async def start_handler(message: Message):

    save_user(message)

    subscribed = await check_subscription(
        message.from_user.id
    )

    if not subscribed:

        await message.answer(
            "🎬 <b>Kino botiga xush kelibsiz!</b>\n\n"
            "Botdan foydalanish uchun kanalimizga "
            "obuna bo‘ling.",
            reply_markup=subscription_keyboard(),
            parse_mode="HTML"
        )

        return

    await message.answer(
        f"👋 Salom, <b>{message.from_user.first_name}</b>!\n\n"
        "🎬 Kino qidirish botiga xush kelibsiz.\n\n"
        "🔢 Kino kodini yuboring yoki kino nomini yozing.",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )


# =========================================================
# CHECK SUB
# =========================================================

@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(callback: CallbackQuery):

    subscribed = await check_subscription(
        callback.from_user.id
    )

    if subscribed:

        await callback.message.edit_text(
            "✅ Obuna tasdiqlandi!\n\n"
            "Endi botdan foydalanishingiz mumkin."
        )

        await callback.message.answer(
            "🎬 Asosiy menyu:",
            reply_markup=main_keyboard()
        )

    else:

        await callback.answer(
            "❌ Siz hali kanalga obuna bo‘lmagansiz.",
            show_alert=True
        )


# =========================================================
# MOVIE SEARCH
# =========================================================

def search_movies(query):

    conn = db()
    cur = conn.cursor()

    q = f"%{query}%"

    cur.execute(
        """
        SELECT id, code, title, year, genre, rating, views
        FROM movies
        WHERE code = ?
           OR title LIKE ?
           OR alt_title LIKE ?
        ORDER BY views DESC
        LIMIT 10
        """,
        (query, q, q)
    )

    results = cur.fetchall()

    conn.close()

    return results


# =========================================================
# MOVIE CARD
# =========================================================

def movie_keyboard(movie_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶️ KINONI KO‘RISH",
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
        views,
        created_at
    ) = movie

    text = f"""
🎬 <b>{title}</b>

🔢 Kod: <code>{code}</code>
📅 Yil: {year}
🎭 Janr: {genre}
⭐ Reyting: {rating}
👁 Ko‘rishlar: {views}

"""

    if alt_title:
        text += f"🌐 Boshqa nomi: {alt_title}\n"

    if description:
        text += f"\n📝 {description}"

    return text


def get_movie(movie_id):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            code,
            title,
            alt_title,
            year,
            genre,
            rating,
            description,
            channel_message_id,
            views,
            created_at
        FROM movies
        WHERE id = ?
        """,
        (movie_id,)
    )

    movie = cur.fetchone()

    conn.close()

    return movie


# =========================================================
# SEARCH MESSAGE
# =========================================================

@dp.message(F.text)
async def text_handler(message: Message):

    if message.text.startswith("/"):
        return

    save_user(message)

    subscribed = await check_subscription(
        message.from_user.id
    )

    if not subscribed:

        await message.answer(
            "❗ Avval kanalga obuna bo‘ling.",
            reply_markup=subscription_keyboard()
        )

        return

    text = message.text.strip()

    # Tugmalar
    if text == "🔎 Kino qidirish":

        await message.answer(
            "🔎 Kino nomi yoki kodini yuboring:"
        )

        return

    if text == "🎬 Top kinolar":

        await show_top_movies(message)

        return

    if text == "🆕 Yangi kinolar":

        await show_new_movies(message)

        return

    if text == "📚 Janrlar":

        await show_genres(message)

        return

    if text == "❤️ Sevimlilar":

        await show_favorites(message)

        return

    if text == "ℹ️ Yordam":

        await help_handler(message)

        return

    results = search_movies(text)

    if not results:

        await message.answer(
            "❌ Kino topilmadi.\n\n"
            "Kino kodi yoki nomini tekshirib qayta yuboring."
        )

        return

    for row in results:

        movie_id = row[0]

        movie = get_movie(movie_id)

        if movie:

            await message.answer(
                movie_text(movie),
                parse_mode="HTML",
                reply_markup=movie_keyboard(movie_id)
            )


# =========================================================
# WATCH MOVIE
# =========================================================

@dp.callback_query(F.data.startswith("watch:"))
async def watch_movie(callback: CallbackQuery):

    movie_id = int(
        callback.data.split(":")[1]
    )

    movie = get_movie(movie_id)

    if not movie:

        await callback.answer(
            "❌ Kino topilmadi.",
            show_alert=True
        )

        return

    message_id = movie[8]

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE movies
        SET views = views + 1
        WHERE id = ?
        """,
        (movie_id,)
    )

    conn.commit()
    conn.close()

    try:

        await bot.copy_message(
            chat_id=callback.from_user.id,
            from_chat_id=CHANNEL_ID,
            message_id=message_id
        )

        await callback.answer(
            "🎬 Kino yuborildi!"
        )

    except Exception as e:

        logger.error(e)

        await callback.answer(
            "❌ Kinoni yuborishda xatolik.",
            show_alert=True
        )


# =========================================================
# FAVORITE
# =========================================================

@dp.callback_query(F.data.startswith("fav:"))
async def favorite_handler(callback: CallbackQuery):

    movie_id = int(
        callback.data.split(":")[1]
    )

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 1
        FROM favorites
        WHERE user_id = ? AND movie_id = ?
        """,
        (
            callback.from_user.id,
            movie_id
        )
    )

    exists = cur.fetchone()

    if exists:

        cur.execute(
            """
            DELETE FROM favorites
            WHERE user_id = ? AND movie_id = ?
            """,
            (
                callback.from_user.id,
                movie_id
            )
        )

        text = "❌ Sevimlilardan olib tashlandi."

    else:

        cur.execute(
            """
            INSERT OR IGNORE INTO favorites
            VALUES (?, ?)
            """,
            (
                callback.from_user.id,
                movie_id
            )
        )

        text = "❤️ Sevimlilarga qo‘shildi."

    conn.commit()
    conn.close()

    await callback.answer(text)


# =========================================================
# TOP MOVIES
# =========================================================

async def show_top_movies(message):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, title, code, year, genre, views
        FROM movies
        ORDER BY views DESC
        LIMIT 10
        """
    )

    movies = cur.fetchall()

    conn.close()

    if not movies:

        await message.answer(
            "Hozircha kinolar mavjud emas."
        )

        return

    text = "🔥 <b>TOP KINOLAR</b>\n\n"

    for i, movie in enumerate(movies, 1):

        movie_id, title, code, year, genre, views = movie

        text += (
            f"{i}. <b>{title}</b>\n"
            f"🔢 {code} | 📅 {year} | 👁 {views}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# NEW MOVIES
# =========================================================

async def show_new_movies(message):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, title, code, year, genre
        FROM movies
        ORDER BY id DESC
        LIMIT 10
        """
    )

    movies = cur.fetchall()

    conn.close()

    if not movies:

        await message.answer(
            "Hozircha kinolar mavjud emas."
        )

        return

    text = "🆕 <b>YANGI KINOLAR</b>\n\n"

    for i, movie in enumerate(movies, 1):

        movie_id, title, code, year, genre = movie

        text += (
            f"{i}. <b>{title}</b>\n"
            f"🔢 {code} | 📅 {year} | 🎭 {genre}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# GENRES
# =========================================================

async def show_genres(message):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT DISTINCT genre
        FROM movies
        WHERE genre != ''
        ORDER BY genre
        """
    )

    genres = cur.fetchall()

    conn.close()

    if not genres:

        await message.answer(
            "❌ Hozircha janrlar mavjud emas."
        )

        return

    keyboard = []

    for genre in genres:

        name = genre[0]

        keyboard.append([
            InlineKeyboardButton(
                text=f"🎭 {name}",
                callback_data=f"genre:{name[:50]}"
            )
        ])

    await message.answer(
        "📚 <b>Janrlar:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


@dp.callback_query(F.data.startswith("genre:"))
async def genre_handler(callback: CallbackQuery):

    genre = callback.data.split(":", 1)[1]

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, title, code, year, genre, views
        FROM movies
        WHERE genre = ?
        ORDER BY views DESC
        LIMIT 20
        """,
        (genre,)
    )

    movies = cur.fetchall()

    conn.close()

    if not movies:

        await callback.answer(
            "Bu janrda kino topilmadi.",
            show_alert=True
        )

        return

    text = f"🎭 <b>{genre}</b>\n\n"

    for movie in movies:

        movie_id, title, code, year, genre, views = movie

        text += (
            f"🎬 <b>{title}</b>\n"
            f"🔢 {code} | 📅 {year} | 👁 {views}\n\n"
        )

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# FAVORITES LIST
# =========================================================

async def show_favorites(message):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT m.id, m.title, m.code, m.year
        FROM favorites f
        JOIN movies m ON m.id = f.movie_id
        WHERE f.user_id = ?
        ORDER BY m.id DESC
        """,
        (message.from_user.id,)
    )

    movies = cur.fetchall()

    conn.close()

    if not movies:

        await message.answer(
            "❤️ Sizda hali sevimli kinolar yo‘q."
        )

        return

    text = "❤️ <b>SEVIMLI KINOLAR</b>\n\n"

    for movie in movies:

        movie_id, title, code, year = movie

        text += (
            f"🎬 <b>{title}</b>\n"
            f"🔢 {code} | 📅 {year}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# HELP
# =========================================================

async def help_handler(message):

    await message.answer(
        "ℹ️ <b>YORDAM</b>\n\n"
        "🔢 Kino kodini yuboring — kino chiqadi.\n"
        "🔎 Kino nomini yuboring — qidiriladi.\n"
        "❤️ Kino kartasidagi tugma orqali sevimliga qo‘shing.\n\n"
        f"👨‍💻 Yordam: {SUPPORT_USERNAME}",
        parse_mode="HTML"
    )


# =========================================================
# ADMIN PANEL
# =========================================================

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
async def admin_handler(message: Message):

    if not is_admin(message.from_user.id):

        await message.answer(
            "❌ Siz admin emassiz."
        )

        return

    await message.answer(
        "⚙️ <b>ADMIN PANEL</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN STATS
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

    cur.execute(
        "SELECT COALESCE(SUM(views), 0) FROM movies"
    )

    views = cur.fetchone()[0]

    conn.close()

    await callback.message.answer(
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users}</b>\n"
        f"🎬 Kinolar: <b>{movies}</b>\n"
        f"👁 Umumiy ko‘rishlar: <b>{views}</b>",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN MOVIES
# =========================================================

@dp.callback_query(F.data == "admin_movies")
async def admin_movies(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, code, title, year, views
        FROM movies
        ORDER BY id DESC
        LIMIT 30
        """
    )

    movies = cur.fetchall()

    conn.close()

    if not movies:

        await callback.message.answer(
            "🎬 Kinolar mavjud emas."
        )

        return

    text = "🎬 <b>KINOLAR</b>\n\n"

    for movie in movies:

        movie_id, code, title, year, views = movie

        text += (
            f"ID: <code>{movie_id}</code>\n"
            f"🔢 {code}\n"
            f"🎬 {title}\n"
            f"📅 {year}\n"
            f"👁 {views}\n\n"
        )

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADD MOVIE STATE
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


# =========================================================
# ADMIN ADD
# =========================================================

@dp.callback_query(F.data == "admin_add")
async def admin_add_start(
    callback: CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):
        return

    await state.set_state(AddMovie.code)

    await callback.message.answer(
        "➕ <b>KINO QO‘SHISH</b>\n\n"
        "1️⃣ Kino kodini yuboring:",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(AddMovie.code)
async def add_code(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        code=message.text.strip()
    )

    await state.set_state(AddMovie.title)

    await message.answer(
        "2️⃣ Kino nomini yuboring:"
    )


@dp.message(AddMovie.title)
async def add_title(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        title=message.text.strip()
    )

    await state.set_state(AddMovie.alt_title)

    await message.answer(
        "3️⃣ Boshqa nomi bo‘lsa yozing.\n"
        "Bo‘lmasa <code>-</code> yuboring.",
        parse_mode="HTML"
    )


@dp.message(AddMovie.alt_title)
async def add_alt_title(
    message: Message,
    state: FSMContext
):

    value = message.text.strip()

    if value == "-":
        value = ""

    await state.update_data(
        alt_title=value
    )

    await state.set_state(AddMovie.year)

    await message.answer(
        "4️⃣ Kino yilini yuboring:"
    )


@dp.message(AddMovie.year)
async def add_year(
    message: Message,
    state: FSMContext
):

    try:

        year = int(message.text.strip())

    except ValueError:

        await message.answer(
            "❌ Yil raqam bo‘lishi kerak."
        )

        return

    await state.update_data(
        year=year
    )

    await state.set_state(AddMovie.genre)

    await message.answer(
        "5️⃣ Janrini yuboring:\n"
        "Masalan: Action, Drama"
    )


@dp.message(AddMovie.genre)
async def add_genre(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        genre=message.text.strip()
    )

    await state.set_state(AddMovie.rating)

    await message.answer(
        "6️⃣ Reytingini yuboring:\n"
        "Masalan: 8.5"
    )


@dp.message(AddMovie.rating)
async def add_rating(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        rating=message.text.strip()
    )

    await state.set_state(AddMovie.description)

    await message.answer(
        "7️⃣ Kino haqida qisqa ma'lumot yuboring.\n"
        "Bo‘lmasa <code>-</code> yuboring.",
        parse_mode="HTML"
    )


@dp.message(AddMovie.description)
async def add_description(
    message: Message,
    state: FSMContext
):

    value = message.text.strip()

    if value == "-":
        value = ""

    await state.update_data(
        description=value
    )

    await state.set_state(
        AddMovie.channel_message_id
    )

    await message.answer(
        "8️⃣ Kanal postining Message ID'sini yuboring.\n\n"
        "Masalan: <code>152</code>",
        parse_mode="HTML"
    )


@dp.message(AddMovie.channel_message_id)
async def add_channel_message_id(
    message: Message,
    state: FSMContext
):

    try:

        message_id = int(
            message.text.strip()
        )

    except ValueError:

        await message.answer(
            "❌ Message ID raqam bo‘lishi kerak."
        )

        return

    data = await state.get_data()

    conn = db()
    cur = conn.cursor()

    try:

        cur.execute(
            """
            INSERT INTO movies (
                code,
                title,
                alt_title,
                year,
                genre,
                rating,
                description,
                channel_message_id,
                views,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                data["code"],
                data["title"],
                data["alt_title"],
                data["year"],
                data["genre"],
                data["rating"],
                data["description"],
                message_id,
                datetime.now().isoformat()
            )
        )

        conn.commit()

        await message.answer(
            "✅ <b>KINO MUVAFFAQIYATLI QO‘SHILDI!</b>\n\n"
            f"🎬 {data['title']}\n"
            f"🔢 Kod: {data['code']}",
            parse_mode="HTML",
            reply_markup=admin_keyboard()
        )

    except sqlite3.IntegrityError:

        await message.answer(
            "❌ Bu kino kodi allaqachon mavjud."
        )

    finally:

        conn.close()

    await state.clear()


# =========================================================
# QUICK ADD
# =========================================================

@dp.message(Command("add"))
async def quick_add_info(message: Message):

    if not is_admin(message.from_user.id):

        await message.answer(
            "❌ Siz admin emassiz."
        )

        return

    await message.answer(
        "⚡ <b>Tezkor kino qo‘shish</b>\n\n"
        "Kino kanalga joylashtirilgandan keyin "
        "admin paneldagi «Kino qo‘shish» orqali "
        "kino ma'lumotlarini kiriting.\n\n"
        f"📌 Kanal ID: <code>{CHANNEL_ID}</code>",
        parse_mode="HTML"
    )


# =========================================================
# DELETE MOVIE
# =========================================================

@dp.message(Command("delmovie"))
async def delete_movie_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    args = message.text.split()

    if len(args) < 2:

        await message.answer(
            "Foydalanish:\n"
            "<code>/delmovie ID</code>",
            parse_mode="HTML"
        )

        return

    try:

        movie_id = int(args[1])

    except ValueError:

        await message.answer(
            "❌ ID noto‘g‘ri."
        )

        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM movies WHERE id = ?",
        (movie_id,)
    )

    conn.commit()

    deleted = cur.rowcount

    conn.close()

    if deleted:

        await message.answer(
            "✅ Kino o‘chirildi."
        )

    else:

        await message.answer(
            "❌ Kino topilmadi."
        )


# =========================================================
# USERS
# =========================================================

@dp.message(Command("users"))
async def users_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM users"
    )

    count = cur.fetchone()[0]

    conn.close()

    await message.answer(
        f"👥 Foydalanuvchilar: <b>{count}</b>",
        parse_mode="HTML"
    )


# =========================================================
# MOVIES COMMAND
# =========================================================

@dp.message(Command("movies"))
async def movies_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM movies"
    )

    count = cur.fetchone()[0]

    conn.close()

    await message.answer(
        f"🎬 Kinolar soni: <b>{count}</b>",
        parse_mode="HTML"
    )


# =========================================================
# STATS COMMAND
# =========================================================

@dp.message(Command("stats"))
async def stats_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM users"
    )
    users = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM movies"
    )
    movies = cur.fetchone()[0]

    cur.execute(
        "SELECT COALESCE(SUM(views), 0) FROM movies"
    )
    views = cur.fetchone()[0]

    conn.close()

    await message.answer(
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Users: {users}\n"
        f"🎬 Movies: {movies}\n"
        f"👁 Views: {views}",
        parse_mode="HTML"
    )


# =========================================================
# BROADCAST
# =========================================================

class BroadcastState(StatesGroup):
    text = State()


@dp.callback_query(F.data == "admin_broadcast")
async def broadcast_start(
    callback: CallbackQuery,
    state: FSMContext
):

    if not is_admin(callback.from_user.id):
        return

    await state.set_state(
        BroadcastState.text
    )

    await callback.message.answer(
        "📢 Barcha foydalanuvchilarga yuboriladigan "
        "xabarni yuboring:"
    )

    await callback.answer()


@dp.message(BroadcastState.text)
async def broadcast_send(
    message: Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM users"
    )

    users = cur.fetchall()

    conn.close()

    success = 0
    failed = 0

    await message.answer(
        f"📢 Xabar {len(users)} ta foydalanuvchiga yuborilmoqda..."
    )

    for user in users:

        user_id = user[0]

        try:

            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )

            success += 1

            await asyncio.sleep(0.05)

        except Exception:

            failed += 1

    await message.answer(
        "✅ <b>Tarqatish tugadi!</b>\n\n"
        f"✅ Yuborildi: {success}\n"
        f"❌ Xatolik: {failed}",
        parse_mode="HTML"
    )

    await state.clear()


# =========================================================
# ADMIN COMMANDS
# =========================================================

@dp.message(Command("panel"))
async def panel_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "⚙️ <b>ADMIN PANEL</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def main():

    init_db()

    logger.info("Bot ishga tushmoqda...")

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    await dp.start_polling(bot)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info("Bot to‘xtatildi.")
