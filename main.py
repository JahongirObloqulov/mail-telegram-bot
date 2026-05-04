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
from flask import Flask, render_template_string, jsonify, request, session, redirect, url_for
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

SECRET_KEY = os.getenv("SECRET_KEY", "standart-maxfiy-kalit-123")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "admin123")

IMAP_SERVER = "imap.mail.ru"
SMTP_SERVER = "smtp.mail.ru"

stats = {"received": 0, "sent": 0, "last_check": "Hali tekshirilmadi"}

logging.basicConfig(level=logging.INFO)
server = Flask(__name__)
server.secret_key = SECRET_KEY

# --- LOGIN SAHIFA HTML ---
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tizimga kirish</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
</head>
<body class="bg-gray-100 font-sans h-screen flex items-center justify-center">
    <div class="bg-white p-8 rounded-2xl shadow-lg w-full max-w-md border-t-4 border-indigo-600">
        <div class="text-center mb-8">
            <div class="inline-block p-4 bg-indigo-50 rounded-full mb-4 text-4xl">🔒</div>
            <h2 class="text-2xl font-bold text-gray-800">Himoyalangan tizim</h2>
            <p class="text-gray-500 text-sm mt-1">Dashboardni ko'rish uchun parolni kiriting</p>
        </div>
        {% if error %}
        <div class="bg-red-50 text-red-600 p-3 rounded-lg text-sm mb-4 flex items-center">
            ⚠️ <span class="ml-2">{{ error }}</span>
        </div>
        {% endif %}
        <form method="POST" action="/login">
            <div class="mb-6">
                <label class="block text-gray-700 text-sm font-bold mb-2" for="password">Maxfiy Parol</label>
                <input type="password" name="password" id="password" required
                    class="w-full px-4 py-3 rounded-lg bg-gray-50 border border-gray-200 focus:border-indigo-500 focus:bg-white focus:outline-none transition duration-200">
            </div>
            <button type="submit" 
                class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 px-4 rounded-lg transition duration-200 shadow-md flex justify-center items-center">
                Tizimga kirish <span class="ml-2">➔</span>
            </button>
        </form>
    </div>
</body>
</html>
"""

# --- DASHBOARD HTML ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NBU Mail Bot - Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    <style>
        .animate-pulse-custom { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
        .loader { border: 3px solid #f3f3f3; border-top: 3px solid #4f46e5; border-radius: 50%; width: 20px; height: 20px; animation: spin 1s linear infinite; display: inline-block; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
        .storage-bg { background-color: #f1f3f4; }
        .storage-blue { background-color: #1a73e8; }
        .dot-blue { background-color: #1a73e8; }
        .dot-green { background-color: #81c995; }
    </style>
</head>
<body class="bg-gray-100 font-sans text-gray-800">
    <nav class="bg-indigo-900 text-white shadow-lg">
        <div class="max-w-7xl mx-auto px-4 py-4">
            <div class="flex items-center justify-between">
                <div class="text-xl font-bold flex items-center gap-2">🏦 NBU Monitoring</div>
                <div class="flex items-center gap-4">
                    <div class="hidden sm:flex text-sm bg-indigo-800 px-3 py-1 rounded-full items-center shadow-inner">
                        <span class="w-2 h-2 rounded-full bg-green-400 mr-2 animate-pulse-custom"></span>Tizim faol
                    </div>
                    <a href="/logout" class="text-sm bg-red-500 hover:bg-red-600 px-4 py-2 rounded-lg font-semibold transition flex items-center">
                        🚪 Chiqish
                    </a>
                </div>
            </div>
        </div>
    </nav>

    <div class="max-w-7xl mx-auto px-4 py-8">
        
        <h2 class="text-2xl font-bold text-gray-700 mb-6 border-b-2 border-indigo-100 pb-2">📊 Umumiy Statistika</h2>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div class="bg-white rounded-xl shadow-sm hover:shadow-md p-6 border-l-4 border-blue-500 flex justify-between items-center">
                <div>
                    <p class="text-sm text-gray-500 font-semibold uppercase tracking-wider mb-1">Bot o'qigan xatlar</p>
                    <h1 class="text-4xl font-extrabold text-gray-800" id="received_count">{{ stats.received }}</h1>
                </div>
                <div class="p-3 bg-blue-50 rounded-full text-blue-500 text-3xl">📥</div>
            </div>
            <div class="bg-white rounded-xl shadow-sm hover:shadow-md p-6 border-l-4 border-green-500 flex justify-between items-center">
                <div>
                    <p class="text-sm text-gray-500 font-semibold uppercase tracking-wider mb-1">Yuborilgan fayllar</p>
                    <h1 class="text-4xl font-extrabold text-gray-800" id="sent_count">{{ stats.sent }}</h1>
                </div>
                <div class="p-3 bg-green-50 rounded-full text-green-500 text-3xl">📤</div>
            </div>
            <div class="bg-white rounded-xl shadow-sm hover:shadow-md p-6 border-l-4 border-yellow-400 flex justify-between items-center">
                <div>
                    <p class="text-sm text-gray-500 font-semibold uppercase tracking-wider mb-1">So'nggi tekshiruv</p>
                    <h3 class="text-xl font-bold text-green-500 mt-1">✅ Onlayn</h3>
                    <p class="text-xs text-gray-400 mt-1 font-mono" id="last_check">{{ stats.last_check }}</p>
                </div>
                <div class="p-3 bg-yellow-50 rounded-full text-yellow-500 text-3xl">🔄</div>
            </div>
        </div>

        <h2 class="text-2xl font-bold text-gray-700 mb-6 border-b-2 border-indigo-100 pb-2 mt-10">🗄️ Pochta Xotirasi va Boshqaruv</h2>
        <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-8">
            
            <div class="mb-8 border-b border-gray-100 pb-8">
                <div class="flex justify-between items-center mb-3">
                    <h3 class="text-xl text-gray-800" style="font-weight: 400; font-family: Arial, sans-serif;" id="quota_title">Ma'lumot yuklanmoqda...</h3>
                    <button class="text-gray-400 hover:text-gray-600 focus:outline-none font-bold text-xl">⋮</button>
                </div>
                <div class="w-full storage-bg rounded-full h-3 mb-4 overflow-hidden">
                    <div id="quota_bar" class="storage-blue h-3 rounded-full transition-all duration-1000" style="width: 0%"></div>
                </div>
                <div class="flex gap-8">
                    <div class="flex items-center">
                        <span class="w-3 h-3 rounded-full dot-blue mr-2"></span>
                        <span class="text-sm text-gray-600" style="font-family: Arial, sans-serif;" id="quota_mail">Почта 0 ГБ</span>
                    </div>
                    <div class="flex items-center">
                        <span class="w-3 h-3 rounded-full dot-green mr-2"></span>
                        <span class="text-sm text-gray-600" style="font-family: Arial, sans-serif;">Облако 0 байт</span>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
                <div>
                    <h3 class="text-lg font-bold text-gray-700 mb-4">Xatlar soni holati</h3>
                    <div class="flex gap-4 mb-4">
                        <div class="bg-indigo-50 p-4 rounded-lg w-1/2 text-center border border-indigo-100">
                            <p class="text-sm text-indigo-500 font-semibold mb-1">Jami xatlar</p>
                            <h2 class="text-3xl font-bold text-indigo-700" id="mb_total">--</h2>
                        </div>
                        <div class="bg-red-50 p-4 rounded-lg w-1/2 text-center border border-red-100">
                            <p class="text-sm text-red-500 font-semibold mb-1">O'qilmagan (Yangi)</p>
                            <h2 class="text-3xl font-bold text-red-700" id="mb_unread">--</h2>
                        </div>
                    </div>
                    <button onclick="fetchMailboxInfo()" id="btn_refresh_mb" class="text-sm text-indigo-600 font-semibold hover:underline flex items-center">
                        <span id="refresh_icon">🔄</span> <span class="ml-1">Ma'lumotlarni yangilash</span>
                    </button>
                </div>

                <div class="border-t md:border-t-0 md:border-l border-gray-100 pt-6 md:pt-0 md:pl-8">
                    <h3 class="text-lg font-bold text-gray-700 mb-4">Xotirani tozalash</h3>
                    <p class="text-sm text-gray-500 mb-4">Pochta to'lib qolmasligi uchun keraksiz xatlarni o'chiring. Bu jarayon Mail.ru serveridan xatlarni butunlay o'chiradi.</p>
                    
                    <div class="flex flex-col gap-3">
                        <button onclick="clearMailbox('read')" id="btn_clear_read" class="w-full bg-blue-50 hover:bg-blue-100 text-blue-700 font-semibold py-3 px-4 border border-blue-200 rounded-lg transition text-left flex justify-between items-center">
                            <span>O'qilgan xatlarni o'chirish (Xavfsiz)</span>
                            <span id="loader_read" class="loader hidden"></span>
                        </button>
                        
                        <button onclick="clearMailbox('all')" id="btn_clear_all" class="w-full bg-red-50 hover:bg-red-100 text-red-700 font-semibold py-3 px-4 border border-red-200 rounded-lg transition text-left flex justify-between items-center">
                            <span>Barcha xatlarni o'chirish (To'liq tozalash)</span>
                            <span id="loader_all" class="loader hidden" style="border-top-color:#dc2626;"></span>
                        </button>
                    </div>
                    <p id="clear_msg" class="text-sm mt-3 font-semibold hidden"></p>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-xl shadow-sm overflow-hidden border border-gray-100">
            <div class="bg-gray-50 px-6 py-4 border-b border-gray-100">
                <h5 class="text-lg font-bold text-gray-700">⚙️ Konfiguratsiya</h5>
            </div>
            <div class="p-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div class="bg-gray-50 p-4 rounded-lg border border-gray-100">
                    <p class="text-xs text-gray-500 font-semibold mb-1 uppercase">Admin Chat ID</p>
                    <p class="font-mono text-gray-800 font-medium">{{ admin_id }}</p>
                </div>
                <div class="bg-gray-50 p-4 rounded-lg border border-gray-100">
                    <p class="text-xs text-gray-500 font-semibold mb-1 uppercase">Mail User</p>
                    <p class="font-mono text-gray-800 font-medium">{{ mail_user }}</p>
                </div>
                <div class="bg-gray-50 p-4 rounded-lg border border-gray-100">
                    <p class="text-xs text-gray-500 font-semibold mb-1 uppercase">Qabul qiluvchi pochta</p>
                    <p class="font-mono text-gray-800 font-medium">{{ mail_to }}</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        function formatGB(kb) {
            if (!kb || kb === 0) return "0 ГБ";
            let gb = kb / (1024 * 1024);
            if (gb < 0.1) {
                let mb = kb / 1024;
                return mb.toFixed(1).replace('.0', '') + " МБ";
            }
            return gb.toFixed(1).replace('.0', '') + " ГБ";
        }

        setInterval(async () => {
            try {
                const res = await fetch('/api/stats');
                if (res.status === 401) { window.location.href = "/login"; return; }
                const data = await res.json();
                document.getElementById('received_count').innerText = data.received;
                document.getElementById('sent_count').innerText = data.sent;
                document.getElementById('last_check').innerText = data.last_check;
            } catch (e) { }
        }, 5000);

        async function fetchMailboxInfo() {
            const btn = document.getElementById('btn_refresh_mb');
            const icon = document.getElementById('refresh_icon');
            icon.classList.add('loader', 'border-indigo-600'); icon.innerText = '';
            btn.disabled = true;

            try {
                // Xatlar sonini olish
                const res = await fetch('/api/mailbox/status');
                const data = await res.json();
                if(data.success) {
                    document.getElementById('mb_total').innerText = data.total;
                    document.getElementById('mb_unread').innerText = data.unread;
                } else {
                    document.getElementById('mb_total').innerText = "Xato";
                    document.getElementById('mb_unread').innerText = "Xato";
                }

                // Xotira hajmini (Kvota) olish
                const quotaRes = await fetch('/api/mailbox/quota');
                const quotaData = await quotaRes.json();
                
                if(quotaData.success) {
                    let usedText = formatGB(quotaData.used_kb);
                    let totalText = formatGB(quotaData.total_kb);
                    let percent = quotaData.total_kb > 0 ? (quotaData.used_kb / quotaData.total_kb) * 100 : 0;
                    if(percent > 100) percent = 100;
                    
                    document.getElementById('quota_title').innerText = `Занято ${usedText} из ${totalText}`;
                    document.getElementById('quota_mail').innerText = `Почта ${usedText}`;
                    document.getElementById('quota_bar').style.width = `${percent}%`;
                } else {
                    document.getElementById('quota_title').innerText = `Xotira hajmini aniqlab bo'lmadi`;
                }

            } catch (e) { 
                console.error("Xatolik:", e);
                document.getElementById('quota_title').innerText = `Server bilan ulanish xatosi`;
            }
            
            icon.classList.remove('loader', 'border-indigo-600'); icon.innerText = '🔄';
            btn.disabled = false;
        }

        async function clearMailbox(type) {
            let msg = type === 'read' ? "Faqat o'qilgan xatlar o'chirib tashlansinmi?" : "DIQQAT! Pochtadagi barcha xatlar butunlay o'chirib tashlanadi. Tasdiqlaysizmi?";
            if (!confirm(msg)) return;

            const btnId = type === 'read' ? 'btn_clear_read' : 'btn_clear_all';
            const loaderId = type === 'read' ? 'loader_read' : 'loader_all';
            const msgEl = document.getElementById('clear_msg');
            
            document.getElementById(btnId).disabled = true;
            document.getElementById(loaderId).classList.remove('hidden');
            msgEl.className = "text-sm mt-3 font-semibold text-blue-600";
            msgEl.innerText = "Tozalanmoqda, kuting... (Pochta hajmiga qarab vaqt olishi mumkin)";
            msgEl.classList.remove('hidden');

            try {
                const res = await fetch('/api/mailbox/clear', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: type })
                });
                const data = await res.json();
                
                if(data.success) {
                    msgEl.className = "text-sm mt-3 font-semibold text-green-600";
                    msgEl.innerText = `✅ Muaffaqiyatli: ${data.deleted_count} ta xat o'chirildi!`;
                    fetchMailboxInfo();
                } else {
                    msgEl.className = "text-sm mt-3 font-semibold text-red-600";
                    msgEl.innerText = `❌ Xatolik: ${data.error}`;
                }
            } catch (e) {
                msgEl.className = "text-sm mt-3 font-semibold text-red-600";
                msgEl.innerText = "❌ Server ulanishida xatolik yuz berdi.";
            }

            document.getElementById(btnId).disabled = false;
            document.getElementById(loaderId).classList.add('hidden');
            setTimeout(() => { msgEl.classList.add('hidden'); }, 8000);
        }

        window.onload = () => { fetchMailboxInfo(); };
    </script>
</body>
</html>
"""

# --- FLASK YO'LLARI (ROUTES) ---
@server.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        parol = request.form.get('password')
        if parol == DASHBOARD_PASS:
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            error = "Parol noto'g'ri kiritildi!"
    return render_template_string(LOGIN_HTML, error=error)

@server.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@server.route('/')
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template_string(DASHBOARD_HTML, stats=stats, admin_id=ADMIN_CHAT_ID, mail_user=MAIL_USER, mail_to=MAIL_TO_ADDR)

@server.route('/api/stats')
def get_stats():
    if not session.get('logged_in'): return jsonify({"error": "Ruxsat etilmagan"}), 401
    return jsonify(stats)

@server.route('/api/mailbox/status')
def get_mailbox_status():
    if not session.get('logged_in'): return jsonify({"error": "Ruxsat etilmagan"}), 401
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(MAIL_USER, MAIL_PASS)
        status, response = mail.status("INBOX", "(MESSAGES UNSEEN)")
        if status == 'OK':
            res_str = response[0].decode('utf-8')
            total = re.search(r'MESSAGES (\d+)', res_str)
            unread = re.search(r'UNSEEN (\d+)', res_str)
            return jsonify({
                "success": True,
                "total": int(total.group(1)) if total else 0,
                "unread": int(unread.group(1)) if unread else 0
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        if mail:
            try: mail.logout()
            except: pass

@server.route('/api/mailbox/quota')
def get_mailbox_quota():
    if not session.get('logged_in'): return jsonify({"error": "Ruxsat etilmagan"}), 401
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(MAIL_USER, MAIL_PASS)
        
        used_kb = 0
        total_kb = 8388608 # Mail.ru standart pochtalari uchun 8GB
        
        # 1-USUL: Serverdan to'g'ridan-to'g'ri o'qishga urinish
        try:
            status, response = mail.getquotaroot("INBOX")
            if status == 'OK':
                res_str = str(response)
                match = re.search(r'STORAGE\D+(\d+)\D+(\d+)', res_str, re.IGNORECASE)
                if match:
                    return jsonify({"success": True, "used_kb": int(match.group(1)), "total_kb": int(match.group(2))})
        except:
            pass # Agar Mail.ru bu funksiyani bloklasa (keng tarqalgan holat), pastdagi 2-usulga o'tadi
            
        # 2-USUL (FALLBACK): Xatlar hajmini "tezkor formatda" bittalab yig'ish 
        try:
            mail.select("INBOX", readonly=True)
            status, data = mail.search(None, 'ALL')
            if status == 'OK' and data[0]:
                # Faqat xatlarning "hajmini" (RFC822.SIZE) chaqiramiz (Bu sekundning kichik qismida ishlaydi)
                status, fetch_res = mail.fetch("1:*", "(RFC822.SIZE)")
                if status == 'OK':
                    total_bytes = 0
                    for item in fetch_res:
                        item_str = ""
                        if isinstance(item, tuple):
                            item_str = item[0].decode('utf-8', errors='ignore')
                        elif isinstance(item, bytes):
                            item_str = item.decode('utf-8', errors='ignore')
                        
                        match = re.search(r'SIZE\s+(\d+)', item_str)
                        if match:
                            total_bytes += int(match.group(1))
                    
                    used_kb = total_bytes // 1024
        except Exception as fallback_err:
            logging.error(f"Fallback Size Error: {fallback_err}")
            pass

        return jsonify({"success": True, "used_kb": used_kb, "total_kb": total_kb})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        if mail:
            try: mail.logout()
            except: pass

@server.route('/api/mailbox/clear', methods=['POST'])
def clear_mailbox():
    if not session.get('logged_in'): return jsonify({"error": "Ruxsat etilmagan"}), 401
    
    data = request.json
    clear_type = data.get('type')
    
    mail = None
    deleted_count = 0
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(MAIL_USER, MAIL_PASS)
        mail.select("INBOX")
        
        search_criteria = 'SEEN' if clear_type == 'read' else 'ALL'
        status, messages = mail.search(None, search_criteria)
        
        if status == 'OK' and messages[0]:
            msg_nums = messages[0].split()
            deleted_count = len(msg_nums)
            for num in msg_nums:
                mail.store(num, '+FLAGS', '\\Deleted')
            
            mail.expunge()
            
        return jsonify({"success": True, "deleted_count": deleted_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        if mail:
            try: mail.logout()
            except: pass

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

# --- POCHTA VA TELEGRAM FUNKSIYALARI ---
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
                    payload = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                    if part.get_content_type() == "text/html":
                        payload = re.sub(r'<[^>]+>', '', payload)
                        payload = html.unescape(payload)
                    body += payload + "\n"
                except: pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
            if msg.get_content_type() == "text/html":
                body = re.sub(r'<[^>]+>', '', body)
                body = html.unescape(body)
        except: pass

    patterns = [ r"Ushbu xabar va unga qo'shimchalar.*", r"Настоящее сообщение и любые приложения к нему.*", r"This e-mail is intended only for the person.*", r"_{10,}" ]
    for p in patterns: body = re.sub(p, "", body, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r'\n\s*\n', '\n\n', body).strip()

async def check_mail(context: ContextTypes.DEFAULT_TYPE):
    mail = None
    stats["last_check"] = time.strftime('%Y-%m-%d %H:%M:%S')
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
                    if fdata: await context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=fdata, filename=fname or "hujjat")
                mail.store(num, '+FLAGS', '\\Seen')
    except Exception as e: logging.error(f"Error: {e}")
    finally:
        if mail:
            try: mail.logout()
            except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[KeyboardButton("🔄 Pochtani tekshirish")], [KeyboardButton("📊 Statistika")]]
    await update.message.reply_text("🏦 <b>NBU Mail Admin</b>\n🌐 Web Panel ishlashni davom etmoqda.", 
                                    parse_mode='HTML', reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔄 Pochtani tekshirish":
        await update.message.reply_text("🔍 Tekshirilmoqda...")
        await check_mail(context)
        await update.message.reply_text("✅ Yakunlandi.")
    elif update.message.text == "📊 Statistika":
        await update.message.reply_text(f"📊 Kelgan xatlar: {stats['received']}\n📤 Yuborilgan fayllar: {stats['sent']}")

async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file = await (msg.document or msg.photo[-1] or msg.video or msg.audio).get_file()
    fname = msg.document.file_name if msg.document else f"file_{int(time.time())}"
    try:
        f_bytes = await file.download_as_bytearray()
        em = EmailMessage()
        em['Subject'] = f"TG: {fname}"; em['From'] = MAIL_USER; em['To'] = MAIL_TO_ADDR
        em.set_content(f"Fayl: {fname}")
        em.add_attachment(f_bytes, maintype='application', subtype='octet-stream', filename=fname)
        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as s:
            s.login(MAIL_USER, MAIL_PASS)
            s.send_message(em)
        stats["sent"] += 1
        await msg.reply_text(f"✅ Yuborildi: {MAIL_TO_ADDR}")
    except Exception as e:
        await msg.reply_text(f"❌ Xato: {e}")

def main():
    Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    admin_filter = filters.Chat(chat_id=ADMIN_CHAT_ID)
    
    app.add_handler(CommandHandler("start", start, filters=admin_filter))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & admin_filter, handle_msg))
    app.add_handler(MessageHandler((filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO) & admin_filter, handle_files))
    
    if app.job_queue: app.job_queue.run_repeating(check_mail, interval=60, first=10)
    
    logging.info("Bot va Web Panel ishga tushdi...")
    app.run_polling()

if __name__ == '__main__': 
    main()