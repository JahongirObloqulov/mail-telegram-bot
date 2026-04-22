import os
import logging
import imaplib
import email
import smtplib
import asyncio
import html
import socket
import re
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
from email.header import decode_header
from email.message import EmailMessage
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- SOZLAMALARNI YUKLASH ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
MAIL_USER = os.getenv("MAIL_USER")
MAIL_PASS = os.getenv("MAIL_PASS")
MAIL_TO_ADDR = os.getenv("MAIL_TO")
IMAP_SERVER = "imap.mail.ru"
SMTP_SERVER = "smtp.mail.ru"

# Ruxsat berilgan foydalanuvchi
ALLOWED_USERS = {str(ADMIN_CHAT_ID): MAIL_TO_ADDR}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- FLASK SERVER (Render/Uptime uchun) ---
server = Flask(__name__)


@server.route('/')
def home():
    return "Bot status: Online"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- YORDAMCHI FUNKSIYALAR ---
def decode_mime_words(s):
    """Fayl nomlari va mavzulardagi o'zbekcha belgilarni to'g'ri dekodlash"""
    if not s: return ""
    try:
        parts = decode_header(s)
        decoded_string = ""
        for word, encoding in parts:
            if isinstance(word, bytes):
                # O'zbekcha tutuq belgilarini saqlash uchun utf-8 yoki latin-1 ishlatamiz
                decoded_string += word.decode(encoding or "utf-8", errors="replace")
            else:
                decoded_string += word

        # O'zbek tilidagi turli ko'rinishdagi tutuq belgilarini standartlashtirish
        decoded_string = decoded_string.replace("’", "'").replace("‘", "'").replace("`", "'")
        # Ortiqcha probellar va qator ko'chishlarini tozalash
        decoded_string = " ".join(decoded_string.split())
        return decoded_string.strip()
    except Exception as e:
        logging.error(f"Decoding xatosi: {e}")
        return str(s)


def safe_html(text):
    """HTML xabarlar uchun belgilarni xavfsiz holatga keltirish"""
    if not text: return ""
    return html.escape(text)


def get_email_body(msg):
    """Xat matnini olish"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                except:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
        except:
            pass
    return ""


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
                        # Mavzu va yuboruvchini dekodlash
                        subject = safe_html(decode_mime_words(msg["Subject"]))
                        sender = safe_html(decode_mime_words(msg["From"]))
                        raw_body = get_email_body(msg).strip()

                        # Eskicha yozishmalarni qirqish (zanjirni qisqartirish)
                        if "From:" in raw_body:
                            raw_body = raw_body.split("From:")[0]

                        clean_body = safe_html(raw_body[:3000]) if raw_body else "<i>Xat matni bo'sh.</i>"

                        caption = (f"📬 <b>Yangi xat keldi!</b>\n\n"
                                   f"👤 <b>Kimdan:</b> {sender}\n"
                                   f"📝 <b>Mavzu:</b> {subject}\n\n"
                                   f"📄 <b>Matn:</b>\n{clean_body}")

                        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption, parse_mode='HTML')

                        # Fayllarni yuborish
                        for part in msg.walk():
                            if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None:
                                continue

                            # Fayl nomini to'g'ri dekodlash (tutuq belgisi va nuqtalar saqlanadi)
                            filename = decode_mime_words(part.get_filename())
                            file_data = part.get_payload(decode=True)

                            if file_data:
                                # Telegramga faylni yuborish
                                await context.bot.send_document(
                                    chat_id=ADMIN_CHAT_ID,
                                    document=file_data,
                                    filename=filename or "hujjat.dat"
                                )
                # Xatni "o'qildi" deb belgilash
                mail.store(num, '+FLAGS', '\\Seen')
    except Exception as e:
        logging.error(f"Pochta monitoringida xato: {e}")
    finally:
        if mail:
            try:
                mail.logout()
            except:
                pass


# --- 2. TELEGRAM -> MAIL.RU (Fayl yuborish) ---
async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id not in ALLOWED_USERS:
        return

    recipient = ALLOWED_USERS[chat_id]
    msg = update.message

    # Fayl turi va nomini aniqlash
    if msg.document:
        file = await msg.document.get_file()
        file_name = msg.document.file_name
    elif msg.photo:
        file = await msg.photo[-1].get_file()
        file_name = f"rasm_{int(asyncio.get_event_loop().time())}.jpg"
    else:
        return

    status_msg = await msg.reply_text(f"⏳ Fayl pochtaga yuborilmoqda...")
    try:
        file_bytes = await file.download_as_bytearray()

        # Email xabarini shakllantirish
        email_msg = EmailMessage()
        email_msg['Subject'] = f"NBU Mail Bot orqali yuborildi: {file_name}"
        email_msg['From'] = MAIL_USER
        email_msg['To'] = recipient
        email_msg.set_content(
            f"Ilova qilingan fayl: {file_name}\n\nUshbu xabar avtomatik ravishda NBU Mail bot orqali yuborildi.")

        # Faylni biriktirish
        email_msg.add_attachment(
            file_bytes,
            maintype='application',
            subtype='octet-stream',
            filename=file_name
        )

        # SMTP orqali yuborish
        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as smtp:
            smtp.login(MAIL_USER, MAIL_PASS)
            smtp.send_message(email_msg)

        await status_msg.edit_text(f"✅ Fayl muvaffaqiyatli yuborildi!\n📧 Qabul qiluvchi: {recipient}")
    except Exception as e:
        await status_msg.edit_text(f"❌ Yuborishda xato: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    await update.message.reply_text(f"🚀 Bot ishga tushdi!\nSizning ID: <code>{user_id}</code>", parse_mode='HTML')


# --- ASOSIY QISM ---
def main():
    # Flaskni fonda ishga tushirish
    keep_alive()

    # Telegram botni sozlash
    application = Application.builder().token(BOT_TOKEN).build()

    # Har 60 soniyada pochtani tekshirish
    if application.job_queue:
        application.job_queue.run_repeating(check_mail_loop, interval=60, first=10)

    # Handlerlarni qo'shish
    application.add_handler(CommandHandler("start", start))
    # Hujjatlar va rasmlarni qabul qilish
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_files))

    logging.info("Bot polling rejimi boshlandi...")
    # drop_pending_updates=True conflict xatolarini oldini olishga yordam beradi
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()