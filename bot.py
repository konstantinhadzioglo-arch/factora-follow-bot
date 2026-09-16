import os
import psycopg2
from psycopg2.extras import RealDictCursor
import asyncio
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 753519761
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is missing")


class DBConnection:
    def __init__(self):
        self.conn = psycopg2.connect(DATABASE_URL)

    def execute(self, query, params=None):
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        query = query.replace("?", "%s")
        cursor.execute(query, params or ())
        return cursor

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def db():
    return DBConnection()

def init_db():
    conn = db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        points INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        id SERIAL PRIMARY KEY,
        tg_id BIGINT NOT NULL,
        platform TEXT NOT NULL,
        url TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        worker_tg_id BIGINT NOT NULL,
        profile_id INTEGER NOT NULL,
        completed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(worker_tg_id, profile_id)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS promotions (
        id SERIAL PRIMARY KEY,
        tg_id BIGINT NOT NULL,
        profile_id INTEGER NOT NULL,
        promotion_type TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    ALTER TABLE promotions
    ADD COLUMN IF NOT EXISTS telegram_payment_charge_id TEXT
    """)

    conn.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_promotions_payment
    ON promotions(telegram_payment_charge_id)
    WHERE telegram_payment_charge_id IS NOT NULL
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
        [InlineKeyboardButton(text="⭐ Потратить баллы", callback_data="spend")],[InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating")],
        [InlineKeyboardButton(text="📖 Правила", callback_data="rules"),
         InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ])

def platforms():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Instagram", callback_data="platform:instagram")],
        [InlineKeyboardButton(text="🎵 TikTok", callback_data="platform:tiktok")],
        [InlineKeyboardButton(text="✈️ Telegram", callback_data="platform:telegram")],
        [InlineKeyboardButton(text="🧵 Threads", callback_data="platform:threads")],
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

    label = {
        "instagram": "Instagram",
        "tiktok": "TikTok",
        "telegram": "Telegram",
        "threads": "Threads"
    }[platform]

    await c.message.edit_text(
        f"📌 Платформа: <b>{label}</b>\n\n"
        "Отправь полную ссылку на свой профиль.\n"
        "Например: https://...",
        reply_markup=back()
    )
    await c.answer()

@dp.callback_query(F.data == "find")
async def cb_find(c:CallbackQuery):
    await show_matches(c.message, c.from_user.id)
    await c.answer()
@dp.callback_query(F.data == "spend")
async def cb_spend(c: CallbackQuery):
    tg_id = c.from_user.id

    conn = db()
    rows = conn.execute("""
    SELECT id, platform, url
    FROM profiles
    WHERE tg_id=? AND active=1
    ORDER BY id
    """, (tg_id,)).fetchall()

    user = conn.execute("""
    SELECT points
    FROM users
    WHERE tg_id=?
    """, (tg_id,)).fetchone()

    conn.close()

    points = user["points"] if user else 0

    if not rows:
        await c.message.edit_text(
            "⭐ <b>Баланс</b>\n\n"
            f"У тебя: <b>{points} ⭐</b>\n\n"
            "Сначала добавь свой аккаунт.",
            reply_markup=back()
        )
        await c.answer()
        return

    keyboard = []

    for r in rows:
        label = {
    "instagram": "📸 Instagram",
    "tiktok": "🎵 TikTok",
    "telegram": "✈️ Telegram",
    "threads": "🧵 Threads"
}.get(r["platform"], r["platform"])

        keyboard.append([
            InlineKeyboardButton(
                text=f"{label}",
                callback_data=f"promo_profile:{r['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="home"
        )
    ])

    await c.message.edit_text(
        "⭐ <b>Баланс</b>\n\n"
        f"Твой баланс: <b>{points} ⭐</b>\n\n"
        "Выбери аккаунт, который хочешь продвинуть:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

    await c.answer()


@dp.callback_query(F.data.startswith("promo_profile:"))
async def cb_promo_profile(c: CallbackQuery):
    profile_id = int(c.data.split(":", 1)[1])
    tg_id = c.from_user.id

    conn = db()

    profile = conn.execute("""
    SELECT platform, url
    FROM profiles
    WHERE id=? AND tg_id=? AND active=1
    """, (profile_id, tg_id)).fetchone()

    user = conn.execute("""
    SELECT points
    FROM users
    WHERE tg_id=?
    """, (tg_id,)).fetchone()

    conn.close()

    if not profile or not user:
        await c.answer("Аккаунт не найден", show_alert=True)
        return

    points = user["points"]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(
            text="🚀 100 ⭐ — 24 часа",
            callback_data=f"buy_promo:{profile_id}:day1:100:1"
        )
    ],
    [
        InlineKeyboardButton(
            text="🚀 250 ⭐ — 3 дня",
            callback_data=f"buy_promo:{profile_id}:day3:250:3"
        )
    ],
    [
        InlineKeyboardButton(
            text="🚀 500 ⭐ — 7 дней",
            callback_data=f"buy_promo:{profile_id}:day7:500:7"
        )
    ],
    [
        InlineKeyboardButton(
            text="💎 50 Stars — 24 часа",
            callback_data=f"buy_stars:{profile_id}:day1:50:1"
        )
    ],
    [
        InlineKeyboardButton(
            text="💎 150 Stars — 3 дня",
            callback_data=f"buy_stars:{profile_id}:day3:150:3"
        )
    ],
    [
        InlineKeyboardButton(
            text="💎 300 Stars — 7 дней",
            callback_data=f"buy_stars:{profile_id}:day7:300:7"
        )
    ],
    [
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="spend"
        )
    ]
])
 

    await c.message.edit_text(
        "⭐ <b>Продвижение аккаунта</b>\n\n"
        f"Твой баланс: <b>{points} ⭐</b>\n\n"
        "Выбери способ продвижения:",
        reply_markup=keyboard
    )

    await c.answer()


@dp.callback_query(F.data.startswith("buy_promo:"))
@dp.callback_query(F.data.startswith("buy_stars:"))
async def cb_buy_stars(c: CallbackQuery):
    parts = c.data.split(":")

    profile_id = int(parts[1])
    promo_type = parts[2]
    stars = int(parts[3])
    days = int(parts[4])

    prices = {
        "day1": 50,
        "day3": 150,
        "day7": 300
    }

    if promo_type not in prices or stars != prices[promo_type]:
        await c.answer("Ошибка тарифа", show_alert=True)
        return

    conn = db()

    profile = conn.execute("""
    SELECT id
    FROM profiles
    WHERE id=? AND tg_id=? AND active=1
    """, (profile_id, c.from_user.id)).fetchone()

    conn.close()

    if not profile:
        await c.answer("Этот аккаунт вам не принадлежит", show_alert=True)
        return

    descriptions = {
        "day1": "Продвижение аккаунта на 24 часа",
        "day3": "Продвижение аккаунта на 3 дня",
        "day7": "Продвижение аккаунта на 7 дней"
    }

    await c.bot.send_invoice(
        chat_id=c.from_user.id,
        title="🚀 Продвижение аккаунта",
        description=descriptions[promo_type],
        payload=f"promo:{profile_id}:{promo_type}:{stars}:{days}",
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Продвижение",
                amount=stars
            )
        ]
    )

    await c.answer()
@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)
@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment

    if payment.currency != "XTR":
        return

    parts = payment.invoice_payload.split(":")

    if len(parts) != 5 or parts[0] != "promo":
        return

    profile_id = int(parts[1])
    promo_type = parts[2]
    stars = int(parts[3])
    days = int(parts[4])

    prices = {
        "day1": 50,
        "day3": 150,
        "day7": 300
    }

    if promo_type not in prices:
        return

    if stars != prices[promo_type]:
        return

    if payment.total_amount != stars:
        return

    tg_id = message.from_user.id

    conn = db()

    profile = conn.execute("""
    SELECT id
    FROM profiles
    WHERE id=? AND tg_id=? AND active=1
    """, (profile_id, tg_id)).fetchone()

    if not profile:
        conn.close()
        return

    cursor = conn.execute("""
INSERT INTO promotions
(tg_id, profile_id, promotion_type, expires_at, telegram_payment_charge_id)
VALUES (?, ?, ?, CURRENT_TIMESTAMP + (? * INTERVAL '1 day'), ?)
ON CONFLICT DO NOTHING
""", (
    tg_id,
    profile_id,
    promo_type,
    days,
    payment.telegram_payment_charge_id
))

if cursor.rowcount == 0:
    conn.close()
    return
    conn.commit()
    conn.close()

    await message.answer(
        f"✅ <b>Оплата прошла успешно!</b>\n\n"
        f"🚀 Продвижение аккаунта активировано на <b>{days} дней</b>.\n"
        f"💎 Оплачено: <b>{stars} Stars</b>"
    )
async def cb_buy_promo(c: CallbackQuery):
    parts = c.data.split(":")

    profile_id = int(parts[1])
    promo_type = parts[2]
    cost = int(parts[3])
    days = int(parts[4])
    
    tg_id = c.from_user.id

    conn = db()

    profile = conn.execute("""
    SELECT id
    FROM profiles
    WHERE id=? AND tg_id=? AND active=1
    """, (profile_id, tg_id)).fetchone()

    user = conn.execute("""
    SELECT points
    FROM users
    WHERE tg_id=?
    """, (tg_id,)).fetchone()

    if not profile or not user:
        conn.close()
        await c.answer("Аккаунт не найден", show_alert=True)
        return

    if user["points"] < cost:
        conn.close()

        await c.answer(
            f"Недостаточно ⭐. Нужно {cost} ⭐",
            show_alert=True
        )
        return

    conn.execute("""
    UPDATE users
    SET points = points - ?
    WHERE tg_id=?
    """, (cost, tg_id))

    conn.execute("""
INSERT INTO promotions
(tg_id, profile_id, promotion_type, expires_at)
VALUES (?, ?, ?, CURRENT_TIMESTAMP + (? * INTERVAL '1 day'))
""", (tg_id, profile_id, promo_type, days))

    conn.commit()

    new_balance = user["points"] - cost

    conn.close()

    names = {
        "boost": "🚀 Аккаунт поднят в выдаче",
        "popular": "🔥 Аккаунт добавлен в «Популярные»",
        "pin": "📌 Аккаунт закреплён выше остальных",
        "vip": "👑 VIP-продвижение активировано на 24 часа",
        "mass": "🚀 Массовое продвижение активировано"
    }

    result = names.get(
        promo_type,
        "✅ Продвижение активировано"
    )

    await c.message.edit_text(
        f"{result}\n\n"
        f"Списано: <b>{cost} ⭐</b>\n"
        f"Осталось: <b>{new_balance} ⭐</b>\n\n"
        f"Продвижение действует <b>{days} день</b>.",
        reply_markup=back()
    )

    await c.answer("✅ Оплата прошла")

async def show_matches(message: Message, tg_id=None):
    tg_id = tg_id or message.from_user.id

    conn = db()
    rows = conn.execute("""
    SELECT p.id, p.platform, p.url, u.first_name, u.username
    FROM profiles p
    JOIN users u ON u.tg_id=p.tg_id
        LEFT JOIN promotions pr
        ON pr.profile_id=p.id
        AND pr.expires_at > CURRENT_TIMESTAMP
    WHERE p.active=1
      AND p.tg_id != ?
      AND NOT EXISTS (
          SELECT 1 FROM tasks t
          WHERE t.worker_tg_id=?
            AND t.profile_id=p.id
            AND t.completed=1
      )
        GROUP BY p.id, p.platform, p.url, u.first_name, u.username
    ORDER BY
        COALESCE(MAX(
            CASE
                WHEN pr.promotion_type = 'day7' THEN 3
                WHEN pr.promotion_type = 'day3' THEN 2
                WHEN pr.promotion_type = 'day1' THEN 1
                ELSE 0
            END
        ), 0) DESC,
        RANDOM()
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

async def show_profile(message: Message, tg_id=None):
    tg_id = tg_id or message.from_user.id
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
    await show_profile(c.message, c.from_user.id)
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

@dp.message(F.text & ~F.text.startswith("/"))
async def text_handler(message: Message):
    tg_id = message.from_user.id

    if tg_id not in waiting:
        return

    platform = waiting[tg_id]
    url = message.text.strip() if message.text else ""

    if not valid_url(url):
        await message.answer(
            "❌ Это не похоже на правильную ссылку.\n\n"
            "Отправь полную ссылку, например:\n"
            "https://instagram.com/username"
        )
        return

    conn = db()

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
        INSERT INTO profiles(tg_id, platform, url, active)
        VALUES (?, ?, ?, 1)
        """, (tg_id, platform, url))

    conn.commit()
    conn.close()

    del waiting[tg_id]

    label = {
        "instagram": "Instagram",
        "tiktok": "TikTok",
        "telegram": "Telegram"
    }.get(platform, platform)

    await message.answer(
        f"✅ <b>{label} сохранён!</b>\n\n"
        f"🔗 {url}\n\n"
        "Теперь другие участники смогут увидеть его в заданиях.",
        reply_markup=main_menu()
    )
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
    


import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Factora Follow Bot is running")

    def log_message(self, format, *args):
        pass


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


async def main():
    init_db()

    threading.Thread(target=run_web, daemon=True).start()

    bot = Bot(
        TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

