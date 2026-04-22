import os
import logging
import imaplib
import email
import smtplib
import asyncio
import html
import socket
import time
import re
from datetime import datetime
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
from email.header import decode_header
from email.message import EmailMessage
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- SOZLAMALARNI YUKLASH ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
MAIL_USER = os.getenv("MAIL_USER")
MAIL_PASS = os.getenv("MAIL_PASS")
MAIL_TO_ADDR = os.getenv("MAIL_TO")

IMAP_SERVER = "imap.mail.ru"
SMTP_SERVER = "smtp.mail.ru"

# Statistika va Uptime uchun
START_TIME = time.time()
stats = {"received": 0, "sent": 0, "errors": 0}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- FLASK SERVER (Render/Uptime uchun) ---
server = Flask(__name__)


@server.route('/')
def home():
    uptime = int(time.time() - START_TIME)
    return f"NBU Bot Online. Uptime: {uptime}s | Received: {stats['received']}"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- YORDAMCHI FUNKSIYALAR ---
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


def get_email_body(msg):
    """Xat matnini har qanday formatdan (HTML yoki Plain) tozalab ajratib olish"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type in ["text/plain", "text/html"] and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8',
                                                                   errors='ignore')
                    if content_type == "text/html":
                        # HTML teglarni tozalash
                        payload = re.sub(r'<[^>]+>', '', payload)
                        payload = html.unescape(payload)
                    body += payload + "\n"
                except:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
            if msg.get_content_type() == "text/html":
                body = re.sub(r'<[^>]+>', '', body)
                body = html.unescape(body)
        except:
            pass

    # Ortiqcha bo'sh qatorlarni qisqartirish
    body = re.sub(r'\n\s*\n', '\n\n', body)
    return body.strip()


# --- 1. MAIL.RU -> TELEGRAM (Monitoring) ---
async def check_mail_loop(context: ContextTypes.DEFAULT_TYPE):
    mail = None
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
                        raw_body = get_email_body(msg)

                        # Forward qilingan xabarlarning faqat o'ta uzun zanjirlarini kesish
                        cut_keywords = ["--------- Forwarded message ---------",
                                        "---------- Пересылаемое сообщение ----------"]
                        for word in cut_keywords:
                            if word in raw_body: raw_body = raw_body.split(word)[0]

                        stats["received"] += 1
                        clean_body = raw_body.strip()
                        if len(clean_body) > 3000: clean_body = clean_body[:3000] + "..."

                        caption = (
                            "🏦 <b>OʻZMILLIY BANK tizimidan xabar!</b>\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            f"👤 <b>Kimdan:</b> <code>{html.escape(sender)}</code>\n"
                            f"📝 <b>Mavzu:</b> <u>{html.escape(subject)}</u>\n\n"
                            f"📄 <b>Matn:</b>\n<i>{html.escape(clean_body) if clean_body else 'Xat matni faqat rasmlardan iborat yoki boʻsh.'}</i>\n"
                            "━━━━━━━━━━━━━━━━━━"
                        )

                        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption, parse_mode='HTML')

                        # Fayllarni yuborish
                        for part in msg.walk():
                            if part.get_content_maintype() == 'multipart' or part.get(
                                'Content-Disposition') is None: continue
                            filename = decode_mime_words(part.get_filename())
                            file_data = part.get_payload(decode=True)
                            if file_data:
                                await context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=file_data,
                                                                filename=filename or "hujjat")
                mail.store(num, '+FLAGS', '\\Seen')
    except Exception as e:
        logging.error(f"Pochta monitoringida xato: {e}")
        stats["errors"] += 1
    finally:
        if mail:
            try:
                mail.logout()
            except:
                pass


# --- 2. TELEGRAM -> MAIL.RU (Yuborish) ---
async def handle_files_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    msg = update.message

    if msg.document:
        file = await msg.document.get_file()
        file_name = msg.document.file_name
    elif msg.photo:
        file = await msg.photo[-1].get_file()
        file_name = f"photo_{int(time.time())}.jpg"
    elif msg.video:
        file = await msg.video.get_file()
        file_name = msg.video.file_name or f"video_{int(time.time())}.mp4"
    elif msg.audio:
        file = await msg.audio.get_file()
        file_name = msg.audio.file_name or f"audio_{int(time.time())}.mp3"
    else:
        return

    status_msg = await msg.reply_text("⏳ Pochtaga yuborilmoqda...")
    try:
        file_bytes = await file.download_as_bytearray()
        email_msg = EmailMessage()
        email_msg['Subject'] = f"NBU Mail Bot: {file_name}"
        email_msg['From'] = MAIL_USER
        email_msg['To'] = MAIL_TO_ADDR
        email_msg.set_content(f"Ilova qilingan fayl: {file_name}\n\nUshbu xabar Telegram bot orqali yuborildi.")
        email_msg.add_attachment(file_bytes, maintype='application', subtype='octet-stream', filename=file_name)

        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as smtp:
            smtp.login(MAIL_USER, MAIL_PASS)
            smtp.send_message(email_msg)

        stats["sent"] += 1
        await status_msg.edit_text(f"✅ Muvaffaqiyatli yuborildi:\n<code>{MAIL_TO_ADDR}</code>", parse_mode='HTML')
    except Exception as e:
        await status_msg.edit_text(f"❌ Xato: {e}")
        stats["errors"] += 1


# --- 3. ADMIN PANEL ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    keyboard = [[KeyboardButton("🔄 Pochtani tekshirish")],
                [KeyboardButton("📊 Statistika"), KeyboardButton("⚙️ Sozlamalar")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🏦 <b>NBU Mail Admin Panel</b>\nMenyudan foydalaning:", parse_mode='HTML',
                                    reply_markup=reply_markup)


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    text = update.message.text
    if text == "🔄 Pochtani tekshirish":
        await update.message.reply_text("🔍 Tekshirilmoqda...")
        await check_mail_loop(context)
        await update.message.reply_text("✅ Tugallandi.")
    elif text == "📊 Statistika":
        await update.message.reply_text(
            f"📊 <b>Statistika:</b>\n\n📥 Kelgan: {stats['received']}\n📤 Yuborilgan: {stats['sent']}\n⚠️ Xatolar: {stats['errors']}\n⏰ Uptime: {get_uptime()}",
            parse_mode='HTML')
    elif text == "⚙️ Sozlamalar":
        await update.message.reply_text(
            f"⚙️ <b>Sozlamalar:</b>\n\n📧 Mail: <code>{MAIL_USER}</code>\n🎯 To: <code>{MAIL_TO_ADDR}</code>",
            parse_mode='HTML')


# --- ASOSIY ---
def main():
    keep_alive()
    application = Application.builder().token(BOT_TOKEN).build()
    admin_filter = filters.Chat(chat_id=ADMIN_CHAT_ID)

    application.add_handler(CommandHandler("start", start, filters=admin_filter))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & admin_filter, handle_menu_text))
    application.add_handler(
        MessageHandler((filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO) & admin_filter,
                       handle_files_upload))

    if application.job_queue:
        application.job_queue.run_repeating(check_mail_loop, interval=60, first=10)

    logging.info("Bot polling boshlandi...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()