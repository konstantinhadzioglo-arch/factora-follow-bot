онimport os
import sqlite3
import asyncio
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 753519761
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

DB = "factora.db"

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        points INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        url TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_tg_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        completed INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(worker_tg_id, profile_id)
    )
    """)

    conn.commit()
    conn.close()

def upsert_user(message: Message):
    u = message.from_user
    conn = db()
    conn.execute("""
    INSERT INTO users(tg_id, username, first_name)
    VALUES (?, ?, ?)
    ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
    """, (u.id, u.username, u.first_name))
    conn.commit()
    conn.close()

def valid_url(url: str):
    try:
        p = urlparse(url.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add")],
        [InlineKeyboardButton(text="🔎 Найти взаимку", callback_data="find")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating")],
        [InlineKeyboardButton(text="📖 Правила", callback_data="rules"),
         InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ])

def platforms():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Instagram", callback_data="platform:instagram")],
        [InlineKeyboardButton(text="🎵 TikTok", callback_data="platform:tiktok")],
        [InlineKeyboardButton(text="✈️ Telegram", callback_data="platform:telegram")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
    ])

def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]
    ])

dp = Dispatcher()
waiting = {}

WELCOME = """🚀 <b>FACTORA FOLLOW</b>

Взаимные подписки для Instagram, TikTok и Telegram.

Добавь свой аккаунт, находи других участников и развивай аудиторию вместе.

Выбирай действие ниже 👇"""

@dp.message(Command("start"))
async def start(message: Message):
    upsert_user(message)
    await message.answer(WELCOME, reply_markup=main_menu())

@dp.message(Command("add"))
async def add_cmd(message: Message):
    upsert_user(message)
    await message.answer("Выбери платформу:", reply_markup=platforms())

@dp.message(Command("find"))
async def find_cmd(message: Message):
    upsert_user(message)
    await show_matches(message)

@dp.message(Command("profile"))
async def profile_cmd(message: Message):
    upsert_user(message)
    await show_profile(message)

@dp.message(Command("rating"))
async def rating_cmd(message: Message):
    conn = db()
    rows = conn.execute("SELECT first_name, username, points FROM users ORDER BY points DESC LIMIT 10").fetchall()
    conn.close()
    text = "🏆 <b>Рейтинг Factora Follow</b>\n\n"
    if not rows:
        text += "Пока здесь пусто."
    else:
        for i, r in enumerate(rows, 1):
            name = ("@" + r["username"]) if r["username"] else r["first_name"] or "Участник"
            text += f"{i}. {name} — {r['points']} ⭐\n"
    await message.answer(text, reply_markup=back())

@dp.message(Command("rules"))
async def rules_cmd(message: Message):
    await message.answer(
        "📖 <b>Правила</b>\n\n"
        "1. Добавляй только свой аккаунт.\n"
        "2. Не размещай запрещённый или мошеннический контент.\n"
        "3. Не спамь и не создавай несколько профилей.\n"
        "4. Взаимность основана на честном подтверждении участника.\n"
        "5. За жалобы и злоупотребления профиль может быть скрыт.",
        reply_markup=back()
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "❓ <b>Как пользоваться</b>\n\n"
        "➕ Добавь аккаунт.\n"
        "🔎 Найди подходящий профиль.\n"
        "🤝 Подпишись и попроси взаимную подписку.\n"
        "👤 Управляй своими профилями через «Мой профиль».",
        reply_markup=back()
    )

@dp.callback_query(F.data == "home")
async def cb_home(c: CallbackQuery):
    await c.message.edit_text(WELCOME, reply_markup=main_menu())
    await c.answer()

@dp.callback_query(F.data == "add")
async def cb_add(c: CallbackQuery):
    await c.message.edit_text("Выбери платформу:", reply_markup=platforms())
    await c.answer()

@dp.callback_query(F.data.startswith("platform:"))
async def cb_platform(c: CallbackQuery):
    platform = c.data.split(":", 1)[1]
    waiting[c.from_user.id] = platform
    label = {"instagram":"Instagram", "tiktok":"TikTok", "telegram":"Telegram"}[platform]
    await c.message.edit_text(
        f"📌 Платформа: <b>{label}</b>\n\n"
        "Отправь полную ссылку на свой профиль.\n"
        "Например: https://...",
        reply_markup=back()
    )
    await c.answer()

@dp.callback_query(F.data == "find")
async def cb_find(c: CallbackQuery):
    await show_matches(c.message, c.from_user.id)
    await c.answer()

async def show_matches(message: Message, tg_id=None):
    tg_id = tg_id or message.from_user.id

    conn = db()
    rows = conn.execute("""
    SELECT p.id, p.platform, p.url, u.first_name, u.username
    FROM profiles p
    JOIN users u ON u.tg_id=p.tg_id
    WHERE p.active=1
      AND p.tg_id != ?
      AND NOT EXISTS (
          SELECT 1 FROM tasks t
          WHERE t.worker_tg_id=?
            AND t.profile_id=p.id
            AND t.completed=1
      )
    ORDER BY RANDOM()
    LIMIT 5
    """, (tg_id, tg_id)).fetchall()
    conn.close()

    if not rows:
        await message.answer(
            "🔎 Пока нет новых заданий.\n\n"
            "Добавь свой аккаунт или попробуй позже.",
            reply_markup=back()
        )
        return

    for r in rows:
        name = ("@" + r["username"]) if r["username"] else r["first_name"] or "Участник"

        label = {
            "instagram": "Instagram",
            "tiktok": "TikTok",
            "telegram": "Telegram"
        }.get(r["platform"], r["platform"].title())

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"👉 Перейти в {label}",
                    url=r["url"]
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Я подписался",
                    callback_data=f"done:{r['id']}"
                )
            ]
        ])

        await message.answer(
            f"👤 <b>{name}</b>\n"
            f"📱 Платформа: <b>{label}</b>\n\n"
            "1️⃣ Перейди на аккаунт\n"
            "2️⃣ Подпишись\n"
            "3️⃣ Нажми «Я подписался»\n\n"
            "⭐ За выполнение: +1 балл",
            reply_markup=keyboard
        )

    await message.answer(
        "🔎 Готово! Выполняй задания и получай ⭐",
        reply_markup=back()
    )
    

@dp.callback_query(F.data.startswith("done:"))
async def cb_done(c: CallbackQuery):
    profile_id = int(c.data.split(":", 1)[1])
    worker_id = c.from_user.id

    conn = db()

    row = conn.execute("""
    SELECT tg_id, platform, url
    FROM profiles
    WHERE id=? AND active=1
    """, (profile_id,)).fetchone()

    if not row or row["tg_id"] == worker_id:
        conn.close()
        await c.answer(
            "❌ Это задание недоступно.",
            show_alert=True
        )
        return

    existing = conn.execute("""
    SELECT id, completed
    FROM tasks
    WHERE worker_tg_id=? AND profile_id=?
    """, (worker_id, profile_id)).fetchone()

    if existing and existing["completed"]:
        conn.close()
        await c.answer(
            "Это задание уже выполнено.",
            show_alert=True
        )
        return

    if existing:
        conn.execute("""
        UPDATE tasks
        SET completed=1
        WHERE id=?
        """, (existing["id"],))
    else:
        conn.execute("""
        INSERT INTO tasks(worker_tg_id, profile_id, completed)
        VALUES (?, ?, 1)
        """, (worker_id, profile_id))

    conn.execute(
        "UPDATE users SET points=points+1 WHERE tg_id=?",
        (worker_id,)
    )

    conn.execute(
        "UPDATE users SET points=points+1 WHERE tg_id=?",
        (row["tg_id"],)
    )

    conn.commit()
    conn.close()

    await c.answer(
        "✅ Подписка отмечена! +1 ⭐",
        show_alert=True
    )

    await c.message.answer(
        "🔥 <b>Задание выполнено!</b>\n\n"
        "Ты получил: <b>+1 ⭐</b>\n"
        "Владелец аккаунта тоже получил: <b>+1 ⭐</b>\n\n"
        "🔎 Нажми «Найти взаимку», чтобы получить следующее задание.",
        reply_markup=main_menu()
    )

async def show_profile(message: Message):
    tg_id = message.from_user.id

    conn = db()

    profiles = conn.execute("""
    SELECT platform, url
    FROM profiles
    WHERE tg_id=? AND active=1
    """, (tg_id,)).fetchall()

    user = conn.execute("""
    SELECT points
    FROM users
    WHERE tg_id=?
    """, (tg_id,)).fetchone()

    completed = conn.execute("""
    SELECT COUNT(*) AS count
    FROM tasks
    WHERE worker_tg_id=? AND completed=1
    """, (tg_id,)).fetchone()

    received = conn.execute("""
    SELECT COUNT(*) AS count
    FROM tasks t
    JOIN profiles p ON p.id=t.profile_id
    WHERE p.tg_id=? AND t.completed=1
    """, (tg_id,)).fetchone()

    points = user["points"] if user else 0

    rank = conn.execute("""
    SELECT COUNT(*) + 1 AS rank
    FROM users
    WHERE points > ?
    """, (points,)).fetchone()

    conn.close()

    text = "👤 <b>Мой профиль</b>\n\n"

    text += f"⭐ <b>Баллы:</b> {points}\n"
    text += f"🏆 <b>Место в рейтинге:</b> #{rank['rank']}\n"
    text += f"✅ <b>Выполнено заданий:</b> {completed['count']}\n"
    text += f"👥 <b>Получено подписок:</b> {received['count']}\n\n"

    text += "📱 <b>Мои аккаунты:</b>\n\n"

    if not profiles:
        text += "Пока нет добавленных аккаунтов."
    else:
        for p in profiles:
            label = {
                "instagram": "📸 Instagram",
                "tiktok": "🎵 TikTok",
                "telegram": "✈️ Telegram"
            }.get(p["platform"], p["platform"].title())

            text += f"{label}\n"
            text += f"{p['url']}\n\n"

    await message.answer(
        text,
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "profile")
async def cb_profile(c: CallbackQuery):
    await show_profile(c.message)
    await c.answer()

@dp.callback_query(F.data == "rating")
async def cb_rating(c: CallbackQuery):
    await rating_cmd(c.message)
    await c.answer()

@dp.callback_query(F.data == "rules")
async def cb_rules(c: CallbackQuery):
    await rules_cmd(c.message)
    await c.answer()

@dp.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery):
    await help_cmd(c.message)
    await c.answer()

@dp.message(Command("users")) 
async def users_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = db()

    rows = conn.execute("""
    SELECT username, first_name, points
    FROM users
    ORDER BY points DESC
    """).fetchall()

    conn.close()

    text = "👥 <b>Участники бота</b>\n\n"

    for i, r in enumerate(rows, 1):
        name = f"@{r['username']}" if r["username"] else (r["first_name"] or "Без имени")
        text += f"{i}. {name} — ⭐ {r['points']}\n"

    text += f"\n<b>Всего участников:</b> {len(rows)}"

    await message.answer(text)


@dp.message()
async def text_handler(message: Message):
    upsert_user(message)

    tg_id = message.from_user.id

    if tg_id in waiting:
        platform = waiting.pop(tg_id)
        url = message.text.strip()

        if not valid_url(url):
            waiting[tg_id] = platform
            await message.answer(
                "❌ Нужна полная ссылка, например https://instagram.com/username"
            )
            return

        conn = db()

        try:
            existing = conn.execute("""
            SELECT id
            FROM profiles
            WHERE tg_id=? AND platform=?
            """, (tg_id, platform)).fetchone()

            if existing:
                conn.execute("""
                UPDATE profiles
                SET url=?, active=1
                WHERE id=?
                """, (url, existing["id"]))
            else:
                conn.execute("""
                INSERT INTO profiles(tg_id, platform, url)
                VALUES (?, ?, ?)
                """, (tg_id, platform, url))

            conn.commit()

        finally:
            conn.close()

        await message.answer(
            f"✅ <b>{platform.title()}</b> аккаунт сохранён!\n\n{url}",
            reply_markup=main_menu()
        )

        return

    await message.answer(
        "Выбери действие в меню 👇",
        reply_markup=main_menu()
    )


@dp.message()
async def text_handler(message: Message):
    upsert_user(message)

    tg_id = message.from_user.id

    if tg_id in waiting:
        platform = waiting.pop(tg_id)
        url = message.text.strip()

        if not valid_url(url):
            waiting[tg_id] = platform
            await message.answer(
                "❌ Нужна полная ссылка, например https://instagram.com/username"
            )
            return

        conn = db()

        try:
            conn.execute("""
            INSERT INTO profiles(tg_id, platform, url)
            VALUES (?, ?, ?)
            ON CONFLICT(tg_id, platform) DO UPDATE SET
                url=excluded.url,
                active=1
            """, (tg_id, platform, url))

            conn.commit()

        finally:
            conn.close()

        await message.answer(
            f"✅ <b>{platform.title()}</b> аккаунт сохранён!\n\n{url}",
            reply_markup=main_menu()
        )

        return

    await message.answer(
        "Выбери действие в меню 👇",
        reply_markup=main_menu()
    )


async def main():
    init_db()
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Factora Follow Bot is running!")

    def log_message(self, format, *args):
        pass


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


threading.Thread(target=run_web, daemon=True).start()


if __name__ == "__main__":
    asyncio.run(main())
