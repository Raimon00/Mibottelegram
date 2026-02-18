import asyncio
import datetime
import aiosqlite
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineQueryResultsButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

# === CONFIGURACIÓN ===
TU_TOKEN = '8338582768:AAHwDhHCHOj6ec8FJT04RR5B3BBLpbXtCqI'  # CAMBIA POR TU TOKEN REAL
ADMIN_ID = 971041541  # TU USER_ID REAL
BOT_USERNAME = "BrainQVA_bot"  # USERNAME SIN @
DB_PATH = 'users.db'

bot = Bot(token=TU_TOKEN)
dp = Dispatcher()

# === MINI SERVIDOR HTTP PARA KEEP-ALIVE (Render free) ===
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive! 🚀")

def run_keep_alive_server():
    port = int(os.environ.get("PORT", 10000))  # Render asigna PORT automáticamente
    server_address = ('', port)
    httpd = HTTPServer(server_address, SimpleHandler)
    print(f"Keep-alive server iniciado en puerto {port}")
    httpd.serve_forever()

# Inicia el servidor en un hilo separado (no bloquea el bot)
threading.Thread(target=run_keep_alive_server, daemon=True).start()

# === INICIALIZACIÓN DB ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            verified INTEGER DEFAULT 0,
            premium_until TEXT,
            views INTEGER DEFAULT 0,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            p1_nombre TEXT DEFAULT 'Mi Perfil',
            p1_telefono TEXT,
            p1_cuenta TEXT,
            p1_crypto TEXT,
            p2_nombre TEXT DEFAULT 'Perfil 2',
            p2_telefono TEXT,
            p2_cuenta TEXT,
            p2_crypto TEXT,
            p3_nombre TEXT DEFAULT 'Perfil 3',
            p3_telefono TEXT,
            p3_cuenta TEXT,
            p3_crypto TEXT
        )
        ''')
        # Migración segura
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass
        await db.commit()

# === UTILIDADES ===
async def is_premium(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    if not row or not row[0]:
        return False
    try:
        expiry = datetime.datetime.strptime(row[0], "%Y-%m-%d").date()
        return datetime.datetime.now().date() <= expiry
    except ValueError:
        return False

async def add_premium_days(user_id, days):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        current_expiry = datetime.date.today()
        if row and row[0]:
            try:
                current_expiry = datetime.datetime.strptime(row[0], "%Y-%m-%d").date()
            except:
                pass
        new_expiry = current_expiry + datetime.timedelta(days=days)
        await db.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (new_expiry.strftime("%Y-%m-%d"), user_id))
        await db.commit()

async def add_referral(referrer_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?", (referrer_id,))
        await db.commit()
    await add_premium_days(referrer_id, 7)

async def add_views(user_id, count=1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, views) VALUES (?, 0)", (user_id,))
        await db.execute("UPDATE users SET views = views + ? WHERE user_id = ?", (count, user_id))
        await db.commit()

async def get_main_keyboard(user_id):
    buttons = [
        [InlineKeyboardButton(text="🔧 Configurar Perfil 1", callback_data="config_perfil1")]
    ]
    if await is_premium(user_id):
        buttons.append([InlineKeyboardButton(text="🔧 Configurar Perfil 2", callback_data="config_perfil2")])
        buttons.append([InlineKeyboardButton(text="🔧 Configurar Perfil 3", callback_data="config_perfil3")])
    buttons += [
        [InlineKeyboardButton(text="🔗 Invitar amigos (ganar VIP)", callback_data="referral")],
        [InlineKeyboardButton(text="📊 Mis Estadísticas", callback_data="misestads")],
        [InlineKeyboardButton(text="💎 VIP y Verificado", callback_data="premium")],
        [InlineKeyboardButton(text="❓ Ayuda", callback_data="ayuda")],
        [InlineKeyboardButton(text="🆔 Mi ID", callback_data="myid")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def show_estadisticas(responder, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT views, referral_count FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    views = row[0] if row else 0
    referrals = row[1] if row else 0
    days_earned = referrals * 7
    premium_text = "Sí 💎" if await is_premium(user_id) else "No"
    
    await responder(
        f"📊 Tus estadísticas:\n\n"
        f"Vistas en tus perfiles: {views} veces\n"
        f"Referidos: {referrals} personas\n"
        f"Días VIP ganados: {days_earned}\n"
        f"VIP activo: {premium_text}",
        reply_markup=await get_main_keyboard(user_id)
    )

# === COMANDOS USUARIO ===
@dp.message(Command("start"))
async def start(message: Message):
    parts = message.text.split()
    user_id = message.from_user.id
    referrer_id = None

    if len(parts) > 1:
        payload = parts[1]
        if payload.startswith("ref"):
            try:
                referrer_id = int(payload[3:])
            except:
                pass

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            existing = await cursor.fetchone()
        
        if not existing:
            await db.execute("INSERT INTO users (user_id, referred_by) VALUES (?, ?)", (user_id, referrer_id))
            await db.commit()
            if referrer_id and referrer_id != user_id:
                await add_referral(referrer_id)
                try:
                    await bot.send_message(referrer_id, "🎉 ¡Nuevo referido! Ganaste 7 días VIP +1 referral 💎")
                except:
                    pass
        else:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()

    keyboard = await get_main_keyboard(user_id)

    if len(parts) > 1 and parts[1] == "config":
        await message.answer("⚙️ Configura con los botones 👇", reply_markup=keyboard)
        return

    await message.answer(
        "🚀 ¡Bienvenido a BrainQVA! 🚀\n\n"
        "Comparte datos fácilmente:\n"
        "• Teléfono 📱 • Cuenta 💳 • Crypto ₿\n\n"
        "Invita amigos → 7 días VIP por cada uno\n\n"
        "Botones 👇",
        reply_markup=keyboard
    )

# (el resto de tus handlers siguen iguales: config_perfil_callback, referral_callback, etc.)
# ... copia y pega aquí todos los @dp.callback_query y @dp.message que faltan ...

# === MODO INLINE ===
@dp.inline_query()
async def inline_query_handler(inline_query: InlineQuery):
    user_id = inline_query.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()
        await add_views(user_id)

        async with db.execute("""
            SELECT verified, p1_nombre, p1_telefono, p1_cuenta, p1_crypto,
                   p2_nombre, p2_telefono, p2_cuenta, p2_crypto,
                   p3_nombre, p3_telefono, p3_cuenta, p3_crypto
            FROM users WHERE user_id = ?
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()

    if not row:
        results = [InlineQueryResultArticle(
            id="no_info",
            title="Sin perfiles configurados",
            description="Configura en privado",
            input_message_content=InputTextMessageContent(
                message_text="❌ Este usuario no ha configurado su información."
            )
        )]
    else:
        verified = row[0]
        badge = " ✅ Verificado" if verified else ""
        is_prem = await is_premium(user_id)

        p1_nombre, p1_tel, p1_cuenta, p1_crypto = row[1], row[2], row[3], row[4]
        p2_nombre, p2_tel, p2_cuenta, p2_crypto = row[5], row[6], row[7], row[8]
        p3_nombre, p3_tel, p3_cuenta, p3_crypto = row[9], row[10], row[11], row[12]

        results = []

        def add_profile(num, nombre, tel, cuenta, crypto):
            tel = tel or "No guardado"
            cuenta = cuenta or "No guardado"
            crypto_line = f"\n₿ <b>Crypto:</b> {crypto}" if crypto else ""

            if is_prem:
                full_text = (
                    f"<b>{nombre}{badge}</b>\n"
                    f"📱 <b>Teléfono:</b> {tel}\n"
                    f"💳 <b>Cuenta:</b> {cuenta}{crypto_line}\n\n"
                    "¡Listo para transferencia! 🚀"
                )
                description = f"VIP 💎 | Tel: {tel} | Cuenta: {cuenta}"
            else:
                full_text = (
                    f"<b>{nombre}{badge}</b>\n"
                    f"📱 <b>Teléfono:</b> {tel}\n"
                    f"💳 <b>Cuenta:</b> {cuenta}{crypto_line}\n\n"
                    "¡Contacto rápido!"
                )
                description = f"Tel: {tel} | Cuenta: {cuenta}"

            results.append(InlineQueryResultArticle(
                id=f"profile_{num}",
                title=f"{nombre}{badge}",
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=full_text,
                    parse_mode="HTML"
                )
            ))

        add_profile(1, p1_nombre or "Mi Perfil", p1_tel, p1_cuenta, p1_crypto)
        if is_prem:
            add_profile(2, p2_nombre or "Perfil 2", p2_tel, p2_cuenta, p2_crypto)
            add_profile(3, p3_nombre or "Perfil 3", p3_tel, p3_cuenta, p3_crypto)

        if not results:
            results = [InlineQueryResultArticle(
                id="no_info",
                title="Sin perfiles configurados",
                description="Configura en privado",
                input_message_content=InputTextMessageContent(
                    message_text="❌ Este usuario no ha configurado su información."
                )
            )]

    button = InlineQueryResultsButton(text="⚙️ Configurar perfiles", start_parameter="config")
    await inline_query.answer(results, cache_time=1, button=button)

# === MAIN ===
async def main():
    await init_db()
    print("Bot iniciado correctamente 🚀")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
