import os
import logging
import imaplib
import email
import smtplib
import asyncio
import html
import socket
import time
from datetime import datetime
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
from email.header import decode_header
from email.message import EmailMessage
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- SOZLAMALAR ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
MAIL_USER = os.getenv("MAIL_USER")
MAIL_PASS = os.getenv("MAIL_PASS")
MAIL_TO_ADDR = os.getenv("MAIL_TO")

IMAP_SERVER = "imap.mail.ru"
SMTP_SERVER = "smtp.mail.ru"

# Bot boshlangan vaqt (Uptime uchun)
START_TIME = time.time()
stats = {"received": 0, "sent": 0, "errors": 0}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- FLASK SERVER ---
server = Flask(__name__)


@server.route('/')
def home(): return f"Admin: {ADMIN_CHAT_ID} | Uptime: {int(time.time() - START_TIME)}s"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)


# --- FUNKSIYALAR ---
def get_uptime():
    uptime_seconds = int(time.time() - START_TIME)
    minutes, seconds = divmod(uptime_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}s {minutes}m {seconds}s"


def decode_mime_words(s):
    if not s: return ""
    try:
        parts = decode_header(s)
        decoded = ""
        for word, encoding in parts:
            if isinstance(word, bytes):
                decoded += word.decode(encoding or "utf-8", errors="replace")
            else:
                decoded += word
        return decoded.replace("’", "'").replace("‘", "'").replace("`", "'").strip()
    except:
        return str(s)


# --- ADMIN PANEL KLAVIATURASI ---
def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔄 Pochtani tekshirish", callback_data="admin_check")],
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
         InlineKeyboardButton("⚙️ Sozlamalar", callback_data="admin_settings")],
        [InlineKeyboardButton("📜 Oxirgi Loglar", callback_data="admin_logs")]
    ]
    return InlineKeyboardMarkup(keyboard)


# --- HANDLERLAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    await update.message.reply_text(
        "👋 <b>NBU Mail Admin Panelga xush kelibsiz!</b>\n\n"
        "Botingiz muvaffaqiyatli ishlamoqda. Quyidagi tugmalar orqali boshqarishingiz mumkin:",
        parse_mode='HTML',
        reply_markup=get_admin_keyboard()
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    await query.answer()

    if query.data == "admin_check":
        await query.edit_message_text("🔍 Pochta tekshirilmoqda...")
        # Bu yerda check_mail funksiyasini chaqirasiz
        await query.edit_message_text("✅ Tekshiruv yakunlandi.", reply_markup=get_admin_keyboard())

    elif query.data == "admin_stats":
        msg = (f"<b>📊 Bot Statistikasi:</b>\n\n"
               f"📥 Kelgan xatlar: {stats['received']}\n"
               f"📤 Yuborilgan fayllar: {stats['sent']}\n"
               f"⚠️ Xatoliklar: {stats['errors']}\n"
               f"⏰ Uptime: {get_uptime()}")
        await query.message.reply_text(msg, parse_mode='HTML', reply_markup=get_admin_keyboard())

    elif query.data == "admin_settings":
        settings_msg = (f"<b>⚙️ Sozlamalar:</b>\n\n"
                        f"👤 Admin ID: <code>{ADMIN_CHAT_ID}</code>\n"
                        f"📧 Mail User: <code>{MAIL_USER}</code>\n"
                        f"🎯 Mail To: <code>{MAIL_TO_ADDR}</code>")
        await query.message.reply_text(settings_msg, parse_mode='HTML', reply_markup=get_admin_keyboard())

    elif query.data == "admin_logs":
        # Renderda haqiqiy log faylga kirish qiyin bo'lishi mumkin,
        # shuning uchun bu yerga tizim vaqtini va holatni qo'yamiz
        log_msg = f"📝 <b>Tizim holati:</b>\n[{datetime.now().strftime('%H:%M:%S')}] Bot polling rejimi faol."
        await query.message.reply_text(log_msg, parse_mode='HTML', reply_markup=get_admin_keyboard())


# --- MAIN ---
def main():
    Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()

    # Faqat Admin uchun filter
    admin_filter = filters.Chat(chat_id=ADMIN_CHAT_ID)

    app.add_handler(CommandHandler("start", start, filters=admin_filter))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # (Pochta monitoringi va fayl handlerlarini yuqoridagi koddan bu yerga qo'shib qo'yasiz)

    logging.info("Admin Panel bilan bot ishga tushdi.")
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()