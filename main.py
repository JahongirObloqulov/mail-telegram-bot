import os
import logging
import imaplib
import email
import smtplib
import asyncio
import html
import socket
from datetime import datetime, timedelta
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

# Statistika uchun o'zgaruvchi
stats = {"received": 0, "last_check": "Hali tekshirilmadi"}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- FLASK SERVER (Uptime uchun) ---
server = Flask(__name__)


@server.route('/')
def home(): return f"Bot Online. Last check: {stats['last_check']}"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)


# --- YORDAMCHI FUNKSIYALAR ---
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


async def notify_admin_error(context: ContextTypes.DEFAULT_TYPE, error_msg: str):
    """Xatolikni adminga yuborish"""
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ <b>Tizim xatosi:</b>\n<code>{error_msg}</code>",
                                   parse_mode='HTML')


# --- POCHTA MONITORINGI ---
async def check_mail(context: ContextTypes.DEFAULT_TYPE):
    mail = None
    stats["last_check"] = datetime.now().strftime("%H:%M:%S")
    try:
        socket.setdefaulttimeout(30)
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(MAIL_USER, MAIL_PASS)
        mail.select("INBOX")
        status, messages = mail.search(None, 'UNSEEN')

        if status == "OK" and messages[0]:
            for num in messages[0].split():
                res, msg_data = mail.fetch(num, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject = decode_mime_words(msg["Subject"])
                        sender = decode_mime_words(msg["From"])
                        stats["received"] += 1

                        text = (f"📬 <b>Yangi xat!</b>\n\n"
                                f"👤 <b>Kimdan:</b> {html.escape(sender)}\n"
                                f"📝 <b>Mavzu:</b> {html.escape(subject)}")

                        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode='HTML')

                        for part in msg.walk():
                            if part.get_content_maintype() == 'multipart' or part.get(
                                'Content-Disposition') is None: continue
                            filename = decode_mime_words(part.get_filename())
                            file_data = part.get_payload(decode=True)
                            if file_data:
                                await context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=file_data,
                                                                filename=filename or "file")
                mail.store(num, '+FLAGS', '\\Seen')
    except Exception as e:
        await notify_admin_error(context, str(e))
    finally:
        if mail:
            try:
                mail.logout()
            except:
                pass


# --- TELEGRAM HANDLERLAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔄 Yangilash", callback_data="check"),
         InlineKeyboardButton("📊 Statistika", callback_data="stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🚀 <b>NBU Mail Bot Professional</b>\nBoshqaruv tugmalaridan foydalaning:",
                                    parse_mode='HTML', reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check":
        await query.edit_message_text("🔍 Pochta tekshirilmoqda...")
        await check_mail(context)
        await query.edit_message_text("✅ Tekshiruv yakunlandi.", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔄 Qayta tekshirish", callback_data="check")]]))

    elif query.data == "stats":
        msg = f"📊 <b>Oxirgi hisobot:</b>\n\n📥 Kelgan xatlar: {stats['received']} ta\n🕒 Oxirgi tekshiruv: {stats['last_check']}"
        await query.message.reply_text(msg, parse_mode='HTML')


async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # Fayl hajmini tekshirish (20MB = 20 * 1024 * 1024 bytes)
    file_size = msg.document.file_size if msg.document else 0
    if file_size > 20 * 1024 * 1024:
        await msg.reply_text("⚠️ Fayl juda katta (max 20MB).")
        return

    file = await (msg.document or msg.photo[-1] or msg.video or msg.audio).get_file()
    file_name = msg.document.file_name if msg.document else f"file_{int(asyncio.get_event_loop().time())}"

    status = await msg.reply_text("⏳ Pochtaga yuborilmoqda...")
    try:
        file_bytes = await file.download_as_bytearray()
        email_msg = EmailMessage()
        email_msg['Subject'] = f"TG-Bot: {file_name}"
        email_msg['From'] = MAIL_USER
        email_msg['To'] = MAIL_TO_ADDR
        email_msg.set_content(f"Yuborilgan fayl: {file_name}")
        email_msg.add_attachment(file_bytes, maintype='application', subtype='octet-stream', filename=file_name)

        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as smtp:
            smtp.login(MAIL_USER, MAIL_PASS)
            smtp.send_message(email_msg)
        await status.edit_text(f"✅ Yuborildi: {MAIL_TO_ADDR}")
    except Exception as e:
        await status.edit_text(f"❌ Xato: {e}")


# --- ASOSIY QISM ---
def main():
    Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()

    # Whitelist Filter
    user_filter = filters.Chat(chat_id=ADMIN_CHAT_ID)

    app.add_handler(CommandHandler("start", start, filters=user_filter))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler((filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO) & user_filter,
                                   handle_files))

    if app.job_queue:
        app.job_queue.run_repeating(lambda ctx: check_mail(ctx), interval=60, first=10)

    logging.info("Bot ishga tushdi.")
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()