from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import random
from datetime import timedelta
from collections import Counter

# TOKENNI O'ZINGIZNIKI BILAN ALMASHTIRING!
API_TOKEN = "8034346294:AAE53a_P73UK_oXP15gnBH1hlXiB5hKUZ74"

games = {}

ROLES = {
    "Don": 1,
    "Mafia": 2,
    "Komissar": 1,
    "Shifokor": 1,
    "Tinch aholi": 6,
}

class Game:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.players = []           # [(user_id, name)]
        self.roles = {}             # user_id → role
        self.alive = set()
        self.started = False
        self.phase = "lobby"
        self.votes = {}             # user_id → voted_user_id
        self.night_actions = {"mafia_kill": None, "doctor_heal": None}
        self.mafia_voted = set()    # mafiyachilar kim ovoz berdi
        self.timer_job = None

    def add_player(self, user_id, name):
        if self.started:
            return False
        if user_id not in [p[0] for p in self.players]:
            self.players.append((user_id, name))
            return True
        return False

    def assign_roles(self):
        pool = []
        for role, count in ROLES.items():
            pool.extend([role] * count)
        while len(pool) < len(self.players):
            pool.append("Tinch aholi")
        random.shuffle(pool)
        self.roles = {uid: pool[i] for i, (uid, _) in enumerate(self.players)}
        self.alive = set(self.roles.keys())

    def alive_list(self):
        return [(uid, name) for uid, name in self.players if uid in self.alive]

    def count_votes(self):
        votes = [t for t in self.votes.values() if t in self.alive]
        if not votes:
            return None
        return Counter(votes).most_common(1)[0][0]

def get_game(user_id):
    for game in games.values():
        if user_id in [p[0] for p in game.players]:
            return game
    return None

# ==================== COMMANDS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Mafia o‘yini botiga xush kelibsiz!\n\n"
        "/join — o‘yinga qo‘shilish\n"
        "/begin — o‘yinni boshlash\n"
        "/cancel — o‘yinni bekor qilish"
    )

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in games:
        games[chat_id] = Game(chat_id)

    game = games[chat_id]

    if game.started:
        await update.message.reply_text("O‘yin allaqachon boshlangan!")
        return

    if game.add_player(user.id, user.full_name):
        await update.message.reply_text(f"{user.full_name} o‘yinga qo‘shildi! ({len(game.players)} ta)")
    else:
        await update.message.reply_text("Siz allaqachon qo‘shilgansiz!")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in games:
        if games[chat_id].timer_job:
            games[chat_id].timer_job.schedule_removal()
        del games[chat_id]
        await update.message.reply_text("O‘yin bekor qilindi.")
    else:
        await update.message.reply_text("Hozir faol o‘yin yo‘q.")

async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in games:
        await update.message.reply_text("Avval /join qiling.")
        return

    game = games[chat_id]
    if len(game.players) < 5:
        await update.message.reply_text("Kamida 5 ta o‘yinchi kerak!")
        return
    if game.started:
        await update.message.reply_text("O‘yin allaqachon boshlangan!")
        return

    game.started = True
    game.assign_roles()

    await update.message.reply_text(f"O‘yin boshlandi! {len(game.players)} ta o‘yinchi ishtirok etmoqda.")

    # Rollarni shaxsiy yuborish
    for uid, name in game.players:
        role = game.roles[uid]
        emoji = {
            "Don": "crown", "Mafia": "gun", "Komissar": "police",
            "Shifokor": "medical", "Tinch aholi": "baby"
        }.get(role, "person")
        try:
            await context.bot.send_message(
                uid,
                f"Sizning rolingiz: *{role}* {emoji}\nO‘yin boshlandi, kuting...",
                parse_mode="Markdown"
            )
        except:
            await context.bot.send_message(chat_id, f"{name} botga shaxsiy xabarda /start bosmagan!")

    await night_phase(game, context)

# ==================== NIGHT PHASE ====================
async def night_phase(game: Game, context: ContextTypes.DEFAULT_TYPE):
    game.phase = "night"
    game.night_actions = {"mafia_kill": None, "doctor_heal": None}
    game.mafia_voted.clear()

    await context.bot.send_message(game.chat_id, "KECHA BOSHLANDI (60 sekund)")

    alive = game.alive_list()

    # Mafia + Don
    for uid in game.alive:
        if game.roles[uid] in ("Mafia", "Don"):
            kb = [
                [InlineKeyboardButton(name, callback_data=f"kill:{pid}")]
                for pid, name in alive if pid != uid
            ]
            kb.append([InlineKeyboardButton("Hech kimni o‘ldirmaslik", callback_data="kill:none")])
            await context.bot.send_message(uid, "Kimni o‘ldirmoqchisiz?", reply_markup=InlineKeyboardMarkup(kb))

    # Shifokor
    for uid in game.alive:
        if game.roles[uid] == "Shifokor":
            kb = [[InlineKeyboardButton(name, callback_data=f"heal:{pid}")] for pid, name in alive]
            await context.bot.send_message(uid, "Bugun kimni davolaysiz?", reply_markup=InlineKeyboardMarkup(kb))

    # Komissar
    for uid in game.alive:
        if game.roles[uid] == "Komissar":
            kb = [
                [InlineKeyboardButton(name, callback_data=f"check:{pid}")]
                for pid, name in alive if pid != uid
            ]
            await context.bot.send_message(uid, "Kimni tekshirmoqchisiz?", reply_markup=InlineKeyboardMarkup(kb))

    # Timer
    if game.timer_job:
        game.timer_job.schedule_removal()
    game.timer_job = context.job_queue.run_once(night_timeout, timedelta(seconds=60), data=game.chat_id)

async def night_timeout(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    if chat_id not in games or games[chat_id].phase != "night":
        return
    await context.bot.send_message(chat_id, "Vaqt tugadi! Kechalik natija...")
    await resolve_night(games[chat_id], context)

async def handle_night_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    game = get_game(user_id)
    if not game or game.phase != "night" or user_id not in game.alive:
        return

    try:
        action, target = query.data.split(":", 1)
    except ValueError:
        return

    role = game.roles[user_id]

    if action == "kill" and role in ("Mafia", "Don"):
        game.mafia_voted.add(user_id)
        game.night_actions["mafia_kill"] = int(target) if target != "none" else None
        await query.edit_message_text("O‘ldirish tanlandi")

    elif action == "heal" and role == "Shifokor":
        game.night_actions["doctor_heal"] = int(target)
        await query.edit_message_text("Davolash tanlandi")

    elif action == "check" and role == "Komissar":
        target_id = int(target)
        is_mafia = "HA, MAFIA!" if game.roles[target_id] in ("Mafia", "Don") else "Yo‘q, tinch aholi"
        await query.edit_message_text(f"Tekshiruv natijasi:\n{is_mafia}")

    # Agar hamma harakat qilgan bo‘lsa
    mafia_count = sum(1 for u in game.alive if game.roles[u] in ("Mafia", "Don"))
    if len(game.mafia_voted) >= mafia_count and game.night_actions["doctor_heal"] is not None:
        if game.timer_job:
            game.timer_job.schedule_removal()
        await resolve_night(game, context)

async def resolve_night(game: Game, context: ContextTypes.DEFAULT_TYPE):
    kill = game.night_actions["mafia_kill"]
    heal = game.night_actions["doctor_heal"]

    died = None
    if kill and kill != heal and kill in game.alive:
        died = kill
        game.alive.remove(kill)

    if died:
        name = next(n for u, n in game.players if u == died)
        await context.bot.send_message(game.chat_id, f"Kechasi *{name}* o‘ldirildi!", parse_mode="Markdown")
    else:
        await context.bot.send_message(game.chat_id, "Kechasi hech kim o‘lmadi.")

    if await check_win(game, context):
        return

    await day_phase(game, context)

# ==================== DAY PHASE ====================
async def day_phase(game: Game, context: ContextTypes.DEFAULT_TYPE):
    game.phase = "day"
    game.votes.clear()

    await context.bot.send_message(game.chat_id, "KUN BOSHLANDI! Ovoz berish — 120 sekund")

    kb = [
        [InlineKeyboardButton(name, callback_data=f"vote:{uid}")]
        for uid, name in game.alive_list()
    ]
    kb.append([InlineKeyboardButton("Hech kimni chiqarmaslik", callback_data="vote:none")])

    await context.bot.send_message(
        game.chat_id,
        "Kimni shahardan chiqaramiz?",
        reply_markup=InlineKeyboardMarkup(kb)
    )

    if game.timer_job:
        game.timer_job.schedule_removal()
    game.timer_job = context.job_queue.run_once(day_timeout, timedelta(seconds=120), data=game.chat_id)

async def day_timeout(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    if chat_id not in games or games[chat_id].phase != "day":
        return
    await context.bot.send_message(chat_id, "Ovoz berish vaqti tugadi!")
    await resolve_day(games[chat_id], context)

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    game = get_game(user_id)
    if not game or game.phase != "day" or user_id not in game.alive:
        return

    try:
        _, target = query.data.split(":", 1)
    except ValueError:
        return

    game.votes[user_id] = int(target) if target != "none" else None
    await query.edit_message_text("Ovozingiz qabul qilindi!")

    if len(game.votes) >= len(game.alive):
        if game.timer_job:
            game.timer_job.schedule_removal()
        await resolve_day(game, context)

async def resolve_day(game: Game, context: ContextTypes.DEFAULT_TYPE):
    lynched = game.count_votes()

    if lynched and lynched in game.alive:
        game.alive.remove(lynched)
        name = next(n for u, n in game.players if u == lynched)
        role = game.roles[lynched]
        await context.bot.send_message(
            game.chat_id,
            f"{name} shahardan chiqarildi!\nU *{role}* edi.",
            parse_mode="Markdown"
        )
    else:
        await context.bot.send_message(game.chat_id, "Bugun hech kim chiqarilmadi.")

    if await check_win(game, context):
        return

    await night_phase(game, context)

# ==================== WIN CHECK ====================
async def check_win(game: Game, context: ContextTypes.DEFAULT_TYPE) -> bool:
    mafia_alive = sum(1 for u in game.alive if game.roles[u] in ("Mafia", "Don"))
    citizens_alive = len(game.alive) - mafia_alive

    if mafia_alive == 0:
        await context.bot.send_message(game.chat_id, "*TINCH AHOLI G‘ALABA QOZONDI!*")
        del games[game.chat_id]
        return True
    if mafia_alive >= citizens_alive:
        await context.bot.send_message(game.chat_id, "*MAFIA G‘ALABA QOZONDI!*")
        del games[game.chat_id]
        return True
    return False

# ==================== MAIN ====================
def main():
    app = ApplicationBuilder().token(API_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("begin", begin))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(CallbackQueryHandler(handle_night_action, pattern="^(kill|heal|check):"))
    app.add_handler(CallbackQueryHandler(handle_vote, pattern="^vote:"))

    print("Mafia bot muvaffaqiyatli ishga tushdi! Timerlar faol")
    app.run_polling()

if __name__ == "__main__":
    main()
