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
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
from email.header import decode_header
from email.message import EmailMessage
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- SOZLAMALAR ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
MAIL_USER = os.getenv("MAIL_USER")
MAIL_PASS = os.getenv("MAIL_PASS")
MAIL_TO_ADDR = os.getenv("MAIL_TO")

IMAP_SERVER = "imap.mail.ru"
SMTP_SERVER = "smtp.mail.ru"

stats = {"received": 0, "sent": 0}

logging.basicConfig(level=logging.INFO)
server = Flask(__name__)


@server.route('/')
def home(): return "NBU Bot: Clean & Online"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)


# --- FUNKSIYALAR ---
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
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ["text/plain", "text/html"] and "attachment" not in str(
                    part.get("Content-Disposition")):
                try:
                    payload = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8',
                                                                   errors='ignore')
                    if part.get_content_type() == "text/html":
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

    # Disclaimer matnlarini tozalash
    patterns = [
        r"Ushbu xabar va unga qo'shimchalar.*",
        r"Настоящее сообщение и любые приложения к нему.*",
        r"This e-mail is intended only for the person.*",
        r"_{10,}"  # 10 tadan ko'p chiziqlarni o'chirish
    ]
    for p in patterns:
        body = re.sub(p, "", body, flags=re.DOTALL | re.IGNORECASE)

    return re.sub(r'\n\s*\n', '\n\n', body).strip()


# --- MONITORING ---
async def check_mail(context: ContextTypes.DEFAULT_TYPE):
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(MAIL_USER, MAIL_PASS)
        mail.select("INBOX")
        _, messages = mail.search(None, 'UNSEEN')

        if messages[0]:
            for num in messages[0].split():
                _, data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                sender = decode_mime_words(msg["From"])
                subject = decode_mime_words(msg["Subject"])
                body = get_email_body(msg)

                stats["received"] += 1
                caption = (
                    "🏦 <b>OʻZMILLIY BANK tizimidan xabar!</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>Kimdan:</b> <code>{html.escape(sender)}</code>\n"
                    f"📝 <b>Mavzu:</b> <u>{html.escape(subject)}</u>\n\n"
                    f"📄 <b>Matn:</b>\n<i>{html.escape(body[:3000]) if body else 'Xat matni boʻsh.'}</i>\n"
                    "━━━━━━━━━━━━━━━━━━"
                )
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption, parse_mode='HTML')

                for part in msg.walk():
                    if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None: continue
                    fname = decode_mime_words(part.get_filename())
                    fdata = part.get_payload(decode=True)
                    if fdata: await context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=fdata,
                                                              filename=fname or "hujjat")
                mail.store(num, '+FLAGS', '\\Seen')
    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        if mail: mail.logout()


# --- HANDLERLAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[KeyboardButton("🔄 Pochtani tekshirish")], [KeyboardButton("📊 Statistika")]]
    await update.message.reply_text("🏦 <b>NBU Mail Admin</b>", parse_mode='HTML',
                                    reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))


async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔄 Pochtani tekshirish":
        await update.message.reply_text("🔍 Tekshirilmoqda...")
        await check_mail(context)
        await update.message.reply_text("✅ Yakunlandi.")
    elif update.message.text == "📊 Statistika":
        await update.message.reply_text(f"📊 Kelgan xatlar: {stats['received']}")


async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file = await (msg.document or msg.photo[-1] or msg.video or msg.audio).get_file()
    fname = msg.document.file_name if msg.document else f"file_{int(time.time())}"
    try:
        f_bytes = await file.download_as_bytearray()
        em = EmailMessage()
        em['Subject'] = f"TG: {fname}";
        em['From'] = MAIL_USER;
        em['To'] = MAIL_TO_ADDR
        em.set_content(f"Fayl: {fname}")
        em.add_attachment(f_bytes, maintype='application', subtype='octet-stream', filename=fname)
        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as s:
            s.login(MAIL_USER, MAIL_PASS)
            s.send_message(em)
        stats["sent"] += 1
        await msg.reply_text(f"✅ Yuborildi: {MAIL_TO_ADDR}")
    except Exception as e:
        await msg.reply_text(f"❌ Xato: {e}")


# --- MAIN ---
def main():
    Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    admin_filter = filters.Chat(chat_id=ADMIN_CHAT_ID)

    app.add_handler(CommandHandler("start", start, filters=admin_filter))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & admin_filter, handle_msg))
    app.add_handler(
        MessageHandler((filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO) & admin_filter,
                       handle_files))

    if app.job_queue: app.job_queue.run_repeating(check_mail, interval=60, first=10)
    app.run_polling()


if __name__ == '__main__': main()