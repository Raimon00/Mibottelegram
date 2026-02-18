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
TU_TOKEN = os.environ.get('TU_TOKEN', '8338582768:AAF8SR6WYxfRLGNdTiGv42lZVvKZMGWB5oI') # Usa variable de entorno para el token
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
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

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

# === CALLBACKS ===
@dp.callback_query(lambda c: c.data and c.data.startswith("config_perfil"))
async def config_perfil_callback(callback: CallbackQuery):
    num = callback.data[-1]
    if num in ["2", "3"] and not await is_premium(callback.from_user.id):
        await callback.message.answer("🔒 Solo VIP. Invita o compra.")
    else:
        await callback.message.answer(
            f"✅ Configurar Perfil {num}:\n"
            f"/perfil{num} <nombre> <teléfono> <cuenta> [crypto]\n\n"
            f"Ejemplo: /perfil{num} Juanito 512***** 92345678********",
            reply_markup=await get_main_keyboard(callback.from_user.id)
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "referral")
async def referral_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref{user_id}"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT referral_count FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    referrals = row[0] if row else 0
    days_earned = referrals * 7
    await callback.message.answer(
        f"🔗 Tu link:\n{link}\n\n"
        f"Referidos: {referrals}\n"
        f"Días VIP ganados: {days_earned} 💎\n\n"
        "Cada nuevo referido = +7 días VIP",
        reply_markup=await get_main_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "misestads")
async def estadisticas_callback(callback: CallbackQuery):
    await show_estadisticas(callback.message.answer, callback.from_user.id)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "premium")
async def premium_callback(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Contactar admin para pago", url="https://t.me/Sr_martinezz")]  # CAMBIA POR TU USERNAME
    ])
    await callback.message.answer(
        "💎 PLANES PREMIUM\n\n"
        "• VIP mensual: 100 CUP → Perfiles extra + formato premium\n"
        "• Verificado permanente: 150 CUP → Badge ✅ Verificado\n\n"
        "Gana VIP gratis invitando amigos (7 días por referido)\n\n"
        "Para comprar:\n"
        "Paga por transferencia y envía comprobante al admin.\n\n"
        "Toca el botón abajo para contactar 👇",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "ayuda")
async def ayuda_callback(callback: CallbackQuery):
    await callback.message.answer(
        "❓ Ayuda:\n\n"
        "Configura en privado → comparte con @{} en cualquier chat\n"
        "Invita amigos para VIP gratis".format(BOT_USERNAME),
        reply_markup=await get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "myid")
async def myid_callback(callback: CallbackQuery):
    await callback.message.answer(f"🆔 Tu ID: {callback.from_user.id}", reply_markup=await get_main_keyboard(callback.from_user.id))
    await callback.answer()

# === CONFIGURAR PERFILES ===
@dp.message(Command("perfil1", "perfil2", "perfil3"))
async def set_perfil(message: Message):
    if message.chat.type != "private":
        await message.answer("❌ Configura solo en privado conmigo.", reply_markup=await get_main_keyboard(message.from_user.id))
        return

    perfil_num = message.text.split()[0][7:]
    if perfil_num in ["2", "3"] and not await is_premium(message.from_user.id):
        await message.answer("🔒 Perfiles extra solo para VIP.", reply_markup=await get_main_keyboard(message.from_user.id))
        return

    args = message.text.split(maxsplit=5)
    if len(args) < 4:
        await message.answer(f"Uso: /{message.text.split()[0][1:]} <nombre> <teléfono> <cuenta> [crypto opcional]")
        return

    nombre = args[1].strip()
    telefono = args[2].strip()
    cuenta = args[3].strip()
    crypto = args[4].strip() if len(args) > 4 else None

    nombre_col = f"p{perfil_num}_nombre"
    tel_col = f"p{perfil_num}_telefono"
    cuenta_col = f"p{perfil_num}_cuenta"
    crypto_col = f"p{perfil_num}_crypto"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.execute(
            f"UPDATE users SET {nombre_col}=?, {tel_col}=?, {cuenta_col}=?, {crypto_col}=? WHERE user_id=?",
            (nombre, telefono, cuenta, crypto, message.from_user.id)
        )
        await db.commit()

    crypto_text = f"\n₿ Crypto: {crypto}" if crypto else ""
    await message.answer(
        f"✅ Perfil {perfil_num} guardado:\n"
        f"<b>{nombre}</b>\n"
        f"📱 {telefono}\n"
        f"💳 {cuenta}{crypto_text}",
        parse_mode="HTML",
        reply_markup=await get_main_keyboard(message.from_user.id)
    )

# === OTROS COMANDOS ===
@dp.message(Command("misestads"))
async def mis_estads(message: Message):
    await show_estadisticas(message.answer, message.from_user.id)

@dp.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"🆔 Tu ID: {message.from_user.id}", reply_markup=await get_main_keyboard(message.from_user.id))

# === BROADCAST (SOLO ADMIN) ===
@dp.message(Command("broadcast"))
async def broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text[len("/broadcast"):].strip()
    if not text:
        await message.answer("Uso: /broadcast <mensaje>")
        return

    await message.answer("🔄 Enviando a todos...")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()

    total = len(rows)
    success = 0
    failed = 0

    for row in rows:
        user_id = row[0]
        try:
            await bot.send_message(user_id, text)
            success += 1
        except:
            failed += 1
        await asyncio.sleep(0.034)

    await message.answer(f"✅ Completado!\nTotal: {total}\nÉxito: {success}\nFallidos: {failed}")

# === ADMIN COMMANDS ===
@dp.message(Command("activarpremium"))
async def activar_premium(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Uso: /activarpremium <user_id> <días>")
        return
    try:
        target_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("❌ Error: <user_id> y <días> deben ser números.")
        return
    await add_premium_days(target_id, days)
    await message.answer(f"Premium activado para {target_id} por {days} días")

@dp.message(Command("verificar"))
async def verificar(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Uso: /verificar <user_id>")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ Error: <user_id> debe ser número.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET verified = 1 WHERE user_id = ?", (target_id,))
        await db.commit()
    await message.answer(f"Verificado activado para {target_id}")

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
    await dp.start_polling(bot, skip_updates=True)  # Agregado skip_updates para ignorar mensajes viejos

if __name__ == "__main__":
    asyncio.run(main())
