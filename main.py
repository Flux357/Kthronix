"""
Kthronix — медиа-бот v7.0
Скачивание + конвертер + Premium/Pro/Family + баланс + QR + убрать фон
Без зеркал
"""

import asyncio, csv, io, os, random, re, secrets, sqlite3, tempfile, zipfile
from datetime import date, datetime, timedelta
from io import BytesIO

import requests
import yt_dlp
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile, CallbackQuery, FSInputFile,
    InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

# ============================== НАСТРОЙКИ ==============================
BOT_TOKEN = "8980559953:AAF0-dMjVH68zMMhwjMHoEgaiJ4tYNVw8Ug"
ADMIN_IDS = [8093996396]
DB_PATH = "bot.db"
FREE_DAILY_LIMIT = 3
PREMIUM_DAYS = 30
CARD_NUMBER = "2202 2088 8566 3253"
CARD_BANK = "Сбербанк"
CARD_HOLDER = "Получатель"
SUPPORT_CONTACT = "@m_Amazonka"
BOT_USERNAME = "Kthronix_bot"
TRIAL_DAYS = 1
CHANNEL_ID = "@gitbotx"
CHANNEL_URL = "https://t.me/gitbotx"
CHANNEL_NAME = "GitBot - проекты"

GIGACHAT_CLIENT_ID = "ВАШ_CLIENT_ID"
GIGACHAT_CLIENT_SECRET = "ВАШ_CLIENT_SECRET"
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"

TARIFFS = {
    "1m":      {"days": 30,  "price": 150,  "title": "⭐ Premium 1 месяц", "level": "premium"},
    "3m":      {"days": 90,  "price": 400,  "title": "⭐ Premium 3 месяца (-11%)", "level": "premium"},
    "12m":     {"days": 365, "price": 1200, "title": "⭐ Premium 1 год (-33%)", "level": "premium"},
    "family":  {"days": 30,  "price": 300,  "title": "👨‍👩‍👧 Family — себе + 2 кода", "level": "premium"},
    "pro_1m":  {"days": 30,  "price": 400,  "title": "💎 Pro 1 месяц", "level": "pro"},
    "pro_3m":  {"days": 90,  "price": 1000, "title": "💎 Pro 3 месяца (-17%)", "level": "pro"},
}

FREE_LIMITS = {
    "pdf_to_txt": 1, "txt_to_pdf": 1, "txt_to_docx": 1, "docx_to_txt": 1,
    "ocr": 0, "audio_to_text": 0, "yt_transcript": 0, "tts": 0,
    "video_to_gif": 0, "compress": 0, "playlist": 0, "pdf_merge": 0,
    "qr": 3, "remove_bg": 0, "photo_pdf": 2, "resize_photo": 2, "summarize": 0,
}
PREMIUM_LIMITS = {
    "pdf_to_txt": 10, "txt_to_pdf": 10, "txt_to_docx": 10, "docx_to_txt": 10,
    "ocr": 5, "audio_to_text": 3, "yt_transcript": 5, "tts": 5,
    "video_to_gif": 3, "compress": 3, "playlist": 1, "pdf_merge": 3,
    "qr": 20, "remove_bg": 5, "photo_pdf": 10, "resize_photo": 10, "summarize": 10,
}

# ============================== БАЗА ==============================
def _con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with _con() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, is_premium INTEGER DEFAULT 0,
            is_pro INTEGER DEFAULT 0, premium_until TEXT, used_today INTEGER DEFAULT 0,
            last_date TEXT, bonus_downloads INTEGER DEFAULT 0, trial_used INTEGER DEFAULT 0,
            referrer_id INTEGER, ref_count INTEGER DEFAULT 0,
            last_daily_bonus TEXT, notify_sent TEXT, partner_balance INTEGER DEFAULT 0,
            captcha_passed INTEGER DEFAULT 0, auto_renew INTEGER DEFAULT 0)""")
        con.execute("""CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
            days INTEGER, level TEXT DEFAULT 'premium', status TEXT, file_id TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        con.execute("""CREATE TABLE IF NOT EXISTS promos (
            code TEXT PRIMARY KEY, discount INTEGER, uses_left INTEGER, active INTEGER DEFAULT 1)""")
        con.execute("""CREATE TABLE IF NOT EXISTS gifts (
            code TEXT PRIMARY KEY, from_user INTEGER, days INTEGER,
            used INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))""")
        con.execute("""CREATE TABLE IF NOT EXISTS user_discounts (
            user_id INTEGER PRIMARY KEY, discount INTEGER DEFAULT 0,
            promo_code TEXT, created_at TEXT DEFAULT (datetime('now')))""")
        con.execute("""CREATE TABLE IF NOT EXISTS balance_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, from_user INTEGER, to_user INTEGER,
            amount INTEGER, created_at TEXT DEFAULT (datetime('now')))""")
        con.execute("""CREATE TABLE IF NOT EXISTS feature_usage (
            user_id INTEGER, feature TEXT, used_date TEXT, count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, feature, used_date))""")
        con.commit()

def get_user(user_id):
    with _con() as con:
        row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            con.execute("INSERT INTO users(user_id, last_date) VALUES(?,?)",
                        (user_id, str(date.today())))
            con.commit()
            row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        u = dict(row)
        if u["last_date"] != str(date.today()):
            con.execute("UPDATE users SET used_today=0, last_date=? WHERE user_id=?",
                        (str(date.today()), user_id))
            con.commit()
            u["used_today"] = 0
        if u["is_premium"] and u["premium_until"]:
            if date.fromisoformat(u["premium_until"]) < date.today():
                con.execute("UPDATE users SET is_premium=0, is_pro=0 WHERE user_id=?", (user_id,))
                con.commit()
                u["is_premium"] = 0; u["is_pro"] = 0
        return u

def is_premium(uid): return bool(get_user(uid)["is_premium"])
def is_pro(uid): return bool(get_user(uid).get("is_pro"))

def inc_usage(uid):
    with _con() as con:
        u = con.execute("SELECT bonus_downloads FROM users WHERE user_id=?", (uid,)).fetchone()
        if u and u["bonus_downloads"] > 0:
            con.execute("UPDATE users SET bonus_downloads=bonus_downloads-1 WHERE user_id=?", (uid,))
        else:
            con.execute("UPDATE users SET used_today=used_today+1 WHERE user_id=?", (uid,))
        con.commit()

def can_download(uid, quality="360"):
    u = get_user(uid)
    if quality in ("720", "1080", "mp3") and not u["is_premium"]:
        return False, "🔒 HD и mp3 — только для Premium"
    if u["is_premium"] or u.get("is_pro"): return True, ""
    if u["used_today"] >= FREE_DAILY_LIMIT and u["bonus_downloads"] == 0:
        return False, f"❌ Лимит {FREE_DAILY_LIMIT} скачиваний. Оформите Premium."
    return True, ""

def set_premium(uid, days, level="premium"):
    u = get_user(uid)
    base = date.today()
    if u["is_premium"] and u["premium_until"]:
        base = max(base, date.fromisoformat(u["premium_until"]))
    until = (base + timedelta(days=days)).isoformat()
    with _con() as con:
        if level == "pro":
            con.execute("UPDATE users SET is_premium=1, is_pro=1, premium_until=?, notify_sent=NULL WHERE user_id=?",
                        (until, uid))
        else:
            con.execute("UPDATE users SET is_premium=1, premium_until=?, notify_sent=NULL WHERE user_id=?",
                        (until, uid))
        con.commit()

def revoke_premium(uid):
    with _con() as con:
        con.execute("UPDATE users SET is_premium=0, is_pro=0, premium_until=NULL WHERE user_id=?", (uid,))
        con.commit()

def set_trial_used(uid):
    with _con() as con:
        con.execute("UPDATE users SET trial_used=1 WHERE user_id=?", (uid,))
        con.commit()

def set_referrer(uid, ref):
    with _con() as con:
        con.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (ref, uid))
        con.execute("UPDATE users SET ref_count=ref_count+1 WHERE user_id=?", (ref,))
        con.commit()

def claim_daily_bonus(uid):
    u = get_user(uid)
    if u["last_daily_bonus"] == str(date.today()):
        return False, "Сегодня бонус уже получен!"
    with _con() as con:
        con.execute("UPDATE users SET bonus_downloads=bonus_downloads+1, last_daily_bonus=? WHERE user_id=?",
                    (str(date.today()), uid))
        con.commit()
    return True, "+1 скачивание!"

def create_payment(uid, amount, days, file_id, level="premium"):
    with _con() as con:
        cur = con.execute(
            "INSERT INTO payments(user_id, amount, days, level, status, file_id) VALUES(?,?,?,?,?,?)",
            (uid, amount, days, level, "pending", file_id))
        con.commit()
        return cur.lastrowid

def get_payment(pid):
    with _con() as con:
        row = con.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None

def set_payment_status(pid, status):
    with _con() as con:
        con.execute("UPDATE payments SET status=? WHERE id=?", (status, pid))
        con.commit()

def add_partner_balance(uid, amount):
    with _con() as con:
        con.execute("UPDATE users SET partner_balance=partner_balance+? WHERE user_id=?", (amount, uid))
        con.commit()

def transfer_balance(frm, to, amount):
    if frm == to: return False, "Нельзя себе"
    if amount <= 0: return False, "Сумма > 0"
    if get_user(frm)["partner_balance"] < amount: return False, "Мало средств"
    get_user(to)
    with _con() as con:
        con.execute("UPDATE users SET partner_balance=partner_balance-? WHERE user_id=?", (amount, frm))
        con.execute("UPDATE users SET partner_balance=partner_balance+? WHERE user_id=?", (amount, to))
        con.execute("INSERT INTO balance_transfers(from_user, to_user, amount) VALUES(?,?,?)", (frm, to, amount))
        con.commit()
    return True, "OK"

def set_captcha_passed(uid):
    with _con() as con:
        con.execute("UPDATE users SET captcha_passed=1 WHERE user_id=?", (uid,))
        con.commit()

def set_auto_renew(uid, value):
    with _con() as con:
        con.execute("UPDATE users SET auto_renew=? WHERE user_id=?", (value, uid))
        con.commit()

def check_feature_limit(uid, feature):
    u = get_user(uid)
    if u.get("is_pro"): return True, ""
    if u["is_premium"]:
        limits = PREMIUM_LIMITS; plan = "Premium"
    else:
        limits = FREE_LIMITS; plan = "Free"
    limit = limits.get(feature, 0)
    if limit == 0:
        return False, f"🔒 Только для Premium."
    today = str(date.today())
    with _con() as con:
        row = con.execute("SELECT count FROM feature_usage WHERE user_id=? AND feature=? AND used_date=?",
                          (uid, feature, today)).fetchone()
        used = row["count"] if row else 0
    if used >= limit:
        return False, f"❌ Лимит ({used}/{limit}, {plan})."
    return True, ""

def use_feature(uid, feature):
    today = str(date.today())
    with _con() as con:
        con.execute("INSERT INTO feature_usage(user_id, feature, used_date, count) VALUES(?,?,?,1) "
                    "ON CONFLICT(user_id, feature, used_date) DO UPDATE SET count=count+1",
                    (uid, feature, today))
        con.commit()

def apply_promo(code):
    with _con() as con:
        row = con.execute("SELECT * FROM promos WHERE code=? AND active=1", (code.upper(),)).fetchone()
        if not row: return False, 0, "Не найден"
        if row["uses_left"] <= 0: return False, 0, "Исчерпан"
        con.execute("UPDATE promos SET uses_left=uses_left-1 WHERE code=?", (code.upper(),))
        con.commit()
        return True, row["discount"], f"-{row['discount']}%"

def add_promo(code, discount, uses):
    with _con() as con:
        con.execute("INSERT OR REPLACE INTO promos(code, discount, uses_left, active) VALUES(?,?,?,1)",
                    (code.upper(), discount, uses))
        con.commit()

def list_promos():
    with _con() as con:
        return [dict(r) for r in con.execute("SELECT * FROM promos ORDER BY code").fetchall()]

def delete_promo(code):
    with _con() as con:
        con.execute("DELETE FROM promos WHERE code=?", (code.upper(),))
        con.commit()

def toggle_promo(code, active):
    with _con() as con:
        con.execute("UPDATE promos SET active=? WHERE code=?", (active, code.upper()))
        con.commit()

def set_user_discount(uid, discount, code):
    with _con() as con:
        con.execute("INSERT OR REPLACE INTO user_discounts(user_id, discount, promo_code) VALUES(?,?,?)",
                    (uid, discount, code))
        con.commit()

def get_user_discount(uid):
    with _con() as con:
        row = con.execute("SELECT discount, promo_code FROM user_discounts WHERE user_id=?", (uid,)).fetchone()
        if not row: return 0, ""
        return row["discount"], row["promo_code"] or ""

def clear_user_discount(uid):
    with _con() as con:
        con.execute("DELETE FROM user_discounts WHERE user_id=?", (uid,))
        con.commit()

def calc_price(price, uid):
    discount, _ = get_user_discount(uid)
    if discount <= 0: return price
    return max(1, int(price * (100 - discount) / 100))

def create_gift(from_user, days):
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
    with _con() as con:
        con.execute("INSERT INTO gifts(code, from_user, days) VALUES(?,?,?)", (code, from_user, days))
        con.commit()
    return code

def create_multiple_gifts(from_user, days, count):
    codes = []
    with _con() as con:
        for _ in range(count):
            code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
            con.execute("INSERT INTO gifts(code, from_user, days) VALUES(?,?,?)",
                        (code, from_user, days))
            codes.append(code)
        con.commit()
    return codes

def use_gift(code, uid):
    code = (code or "").strip().upper()
    if not code:
        return False, 0, "Пустой код"
    with _con() as con:
        row = con.execute("SELECT * FROM gifts WHERE UPPER(code)=? AND used=0", (code,)).fetchone()
        if not row:
            used_row = con.execute("SELECT * FROM gifts WHERE UPPER(code)=?", (code,)).fetchone()
            if used_row:
                return False, 0, "Код уже использован"
            return False, 0, "Код не найден"
        con.execute("UPDATE gifts SET used=1 WHERE code=?", (row["code"],))
        con.commit()
        return True, row["days"], "Активирован!"

# ============================== СКАЧИВАНИЕ ==============================
QUALITY_FORMATS = {
    "360": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best",
    "720": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
    "mp3": "bestaudio/best",
}

def download_tiktok_nowm(url, outdir):
    r = requests.get("https://www.tikwm.com/api/", params={"url": url, "hd": 1}, timeout=20)
    data = r.json()
    if data.get("code") != 0: raise Exception(f"tikwm: {data.get('msg', 'ошибка')}")
    vp = data["data"]["play"]
    if not vp.startswith("http"): vp = "https://www.tikwm.com" + vp
    title = re.sub(r"[^\w\s-]", "", data["data"].get("title", "tiktok"))[:60].strip()
    out = os.path.join(outdir, f"{title or 'tiktok'}.mp4")
    with requests.get(vp, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(out, "wb") as f:
            for chunk in resp.iter_content(8192): f.write(chunk)
    return out

def download_ytdlp_nowm(url, quality, outdir):
    is_audio = quality == "mp3"
    opts = {
        "outtmpl": os.path.join(outdir, "%(title).80s.%(ext)s"),
        "format": QUALITY_FORMATS[quality], "quiet": True, "noplaylist": True,
        "max_filesize": 50 * 1024 * 1024,
        "postprocessor_args": {"ffmpeg": ["-map_metadata", "-1"]},
    }
    if is_audio:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        opts["merge_output_format"] = "mp4"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
    if is_audio: path = os.path.splitext(path)[0] + ".mp3"
    elif not path.endswith(".mp4"): path = os.path.splitext(path)[0] + ".mp4"
    return path

def smart_download(url, quality, outdir):
    ul = url.lower()
    if "tiktok.com" in ul or "douyin.com" in ul:
        try: return download_tiktok_nowm(url, outdir)
        except Exception as e: print(f"[tikwm err] {e}")
    return download_ytdlp_nowm(url, quality, outdir)

# ============================== КОНВЕРТЕРЫ ==============================
def pdf_to_text(path):
    from pypdf import PdfReader
    return "\n\n".join((p.extract_text() or "") for p in PdfReader(path).pages)

def docx_to_text(path):
    from docx import Document
    return "\n".join(p.text for p in Document(path).paragraphs)

def txt_to_pdf(text, outdir, title="Документ"):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    font_name = "Helvetica"
    for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "/System/Library/Fonts/Supplemental/Arial.ttf",
               "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/DejaVuSans.ttf"]:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("CustomFont", fp)); font_name = "CustomFont"; break
            except Exception: continue
    out = os.path.join(outdir, "document.pdf")
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["Normal"], fontName=font_name, fontSize=12, leading=16)
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontName=font_name,
                                  fontSize=18, leading=22, spaceAfter=16)
    story = [Paragraph(title, title_style), Spacer(1, 0.5*cm)]
    for line in text.split("\n"):
        if line.strip():
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe, body))
            story.append(Spacer(1, 0.2*cm))
        else: story.append(Spacer(1, 0.4*cm))
    doc.build(story)
    return out

def txt_to_docx(text, outdir, title="Документ"):
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    doc = Document()
    h = doc.add_heading(title, level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for line in text.split("\n"):
        p = doc.add_paragraph(line)
        for run in p.runs: run.font.size = Pt(12)
    out = os.path.join(outdir, "document.docx")
    doc.save(out)
    return out

def image_to_text(path):
    import easyocr
    return "\n".join(easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
                     .readtext(path, detail=0, paragraph=True))

def audio_to_text(path):
    from faster_whisper import WhisperModel
    m = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(path, language="ru")
    return " ".join(s.text.strip() for s in segs)

def youtube_transcript(url):
    from youtube_transcript_api import YouTubeTranscriptApi
    vid = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    if not vid: raise ValueError("Не найден ID")
    t = YouTubeTranscriptApi.get_transcript(vid.group(1), languages=["ru", "en"])
    return " ".join(x["text"] for x in t)

def video_to_gif(path, outdir):
    out = os.path.join(outdir, "result.gif")
    os.system(f'ffmpeg -y -i "{path}" -vf "fps=10,scale=480:-1" -t 10 "{out}" -loglevel quiet')
    return out

def compress_video(path, outdir):
    out = os.path.join(outdir, "compressed.mp4")
    os.system(f'ffmpeg -y -i "{path}" -vcodec libx264 -crf 28 -preset fast -acodec aac -b:a 96k "{out}" -loglevel quiet')
    return out

def merge_pdfs(paths, outdir):
    from pypdf import PdfWriter
    w = PdfWriter()
    for p in paths: w.append(p)
    out = os.path.join(outdir, "merged.pdf")
    with open(out, "wb") as f: w.write(f)
    return out

def photos_to_pdf(paths, outdir):
    from PIL import Image
    out = os.path.join(outdir, "photos.pdf")
    images = []
    for p in paths:
        img = Image.open(p)
        if img.mode != "RGB": img = img.convert("RGB")
        images.append(img)
    if not images: raise Exception("Нет фото")
    first, rest = images[0], images[1:]
    first.save(out, "PDF", save_all=True, append_images=rest, resolution=100)
    return out

def resize_photo(path, outdir, max_size):
    from PIL import Image
    img = Image.open(path)
    w, h = img.size
    if max(w, h) > max_size:
        if w > h:
            new_w, new_h = max_size, int(h * max_size / w)
        else:
            new_h, new_w = max_size, int(w * max_size / h)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    out = os.path.join(outdir, "resized.jpg")
    if img.mode != "RGB": img = img.convert("RGB")
    img.save(out, "JPEG", quality=95)
    return out

def download_playlist(url, quality, outdir):
    opts = {
        "outtmpl": os.path.join(outdir, "%(playlist_index)s_%(title).60s.%(ext)s"),
        "format": QUALITY_FORMATS[quality], "quiet": True, "noplaylist": False,
        "max_filesize": 30 * 1024 * 1024, "ignoreerrors": True,
        "postprocessor_args": {"ffmpeg": ["-map_metadata", "-1"]},
    }
    if quality == "mp3":
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else: opts["merge_output_format"] = "mp4"
    with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
    zp = os.path.join(outdir, "playlist.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in os.listdir(outdir):
            if f != "playlist.zip": z.write(os.path.join(outdir, f), f)
    return zp

async def text_to_speech(text, outdir):
    import edge_tts
    out = os.path.join(outdir, "voice.mp3")
    c = edge_tts.Communicate(text[:3000], "ru-RU-SvetlanaNeural")
    await c.save(out)
    return out

def make_qr(text, outdir):
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(text); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    out = os.path.join(outdir, "qr.png")
    img.save(out)
    return out

def remove_bg(path, outdir):
    from rembg import remove
    out = os.path.join(outdir, "no_bg.png")
    with open(path, "rb") as f: data = f.read()
    result = remove(data)
    with open(out, "wb") as f: f.write(result)
    return out

async def summarize_text(text):
    from gigachat import GigaChat
    text = text[:8000]
    prompt = ("Сделай краткое содержание текста в виде 5-7 пунктов списка. "
              "Каждый пункт — одно короткое предложение. Пиши по-русски.\n\n"
              f"Текст:\n{text}")
    giga = GigaChat(credentials=f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}",
                    scope=GIGACHAT_SCOPE, verify_ssl_certs=False)
    response = giga.chat(prompt)
    return response.choices[0].message.content

# ============================== БОТ ==============================
bot = Bot(BOT_TOKEN)
router = Router()
URL_RE = re.compile(r"https?://\S+")

class PayFlow(StatesGroup): waiting_receipt = State()
class PromoFlow(StatesGroup): waiting_code = State()
class PromoNewFlow(StatesGroup): waiting_data = State()
class ConvertFlow(StatesGroup): waiting_file = State()
class TxtConvertFlow(StatesGroup): waiting_text = State()
class QRFlow(StatesGroup): waiting_text = State()
class RemoveBGFlow(StatesGroup): waiting_photo = State()
class PhotoPDFFlow(StatesGroup): collecting = State()
class ResizeFlow(StatesGroup): waiting_photo = State(); waiting_size = State()
class SummarizeFlow(StatesGroup): waiting_text = State()
class GrantFlow(StatesGroup): waiting_data = State()
class RevokeFlow(StatesGroup): waiting_id = State()
class FindFlow(StatesGroup): waiting_id = State()
class TTSFlow(StatesGroup): waiting_text = State()
class GiftUseFlow(StatesGroup): waiting_code = State()
class PDFMergeFlow(StatesGroup): collecting = State()
class TransferFlow(StatesGroup): waiting_user = State(); waiting_amount = State()

# ============================== ПОДПИСКА ==============================
async def check_subscription(uid, channel_id=None):
    cid = channel_id or CHANNEL_ID
    try:
        m = await bot.get_chat_member(cid, uid)
        return m.status in ("member", "administrator", "creator")
    except Exception as e:
        print(f"[SUB ERR] {e}")
        return False

def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Подписаться на {CHANNEL_NAME}", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]])

async def show_sub_screen(ev, edit=False):
    text = (f"🔒 <b>Доступ только для подписчиков</b>\n\n"
            f"Подпишитесь на канал:\n👉 <b>{CHANNEL_NAME}</b>\n\n"
            f"После подписки нажмите «✅ Я подписался».")
    if edit and isinstance(ev, CallbackQuery):
        try:
            await ev.message.edit_text(text, parse_mode="HTML", reply_markup=subscribe_kb())
            return
        except Exception: pass
    if isinstance(ev, CallbackQuery):
        await ev.message.answer(text, parse_mode="HTML", reply_markup=subscribe_kb())
    else:
        await ev.answer(text, parse_mode="HTML", reply_markup=subscribe_kb())

def make_captcha_kb(correct):
    nums = [correct]
    while len(nums) < 6:
        n = random.randint(1, 20)
        if n not in nums: nums.append(n)
    random.shuffle(nums)
    rows = []
    for i in range(0, 6, 3):
        rows.append([InlineKeyboardButton(text=str(n), callback_data=f"captcha_{n}_{correct}")
                     for n in nums[i:i+3]])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def send_captcha(ev):
    correct = random.randint(1, 20)
    text = f"🤖 <b>Проверка</b>\n\nНажмите на кнопку с числом <b>{correct}</b>"
    kb = make_captcha_kb(correct)
    if isinstance(ev, CallbackQuery):
        try: await ev.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception: await ev.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await ev.answer(text, parse_mode="HTML", reply_markup=kb)

class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, channel_id=None):
        self.channel_id = channel_id
        super().__init__()
    async def __call__(self, handler, event, data):
        uid = None
        if isinstance(event, Message): uid = event.from_user.id
        elif isinstance(event, CallbackQuery): uid = event.from_user.id
        if uid and uid in ADMIN_IDS: return await handler(event, data)
        if isinstance(event, CallbackQuery):
            if event.data == "check_sub" or event.data.startswith("captcha_"):
                return await handler(event, data)
        if uid and not await check_subscription(uid, self.channel_id):
            if isinstance(event, Message): await show_sub_screen(event)
            else:
                await event.answer("🔒 Подпишитесь!", show_alert=True)
                await show_sub_screen(event, edit=True)
            return
        if uid:
            u = get_user(uid)
            if not u["captcha_passed"]:
                if isinstance(event, Message):
                    await send_captcha(event); return
                else:
                    await event.answer("🤖 Проверка", show_alert=True)
                    await send_captcha(event); return
        return await handler(event, data)

# ============================== КЛАВИАТУРЫ ==============================
def main_menu_kb(uid):
    u = get_user(uid)
    rows = [
        [InlineKeyboardButton(text="📥 Скачать видео", callback_data="help_download")],
        [InlineKeyboardButton(text="📝 Текст → TXT", callback_data="help_txt")],
        [InlineKeyboardButton(text="🔄 Конвертер файлов", callback_data="converter")],
        [InlineKeyboardButton(text="🔊 Озвучить текст", callback_data="tts")],
    ]
    if u.get("is_pro"):
        rows.append([InlineKeyboardButton(text=f"💎 Pro до {u['premium_until']}", callback_data="premium_info")])
    elif u["is_premium"]:
        rows.append([InlineKeyboardButton(text=f"⭐ Premium до {u['premium_until']}", callback_data="premium_info")])
    else:
        rows.append([InlineKeyboardButton(text="⭐ Оформить Premium — 150 ₽", callback_data="buy")])
    rows += [
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🎁 Бонус дня", callback_data="daily_bonus")],
        [InlineKeyboardButton(text="🤝 Пригласить", callback_data="referral"),
         InlineKeyboardButton(text="💼 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="❓ Поддержка", url=f"https://t.me/{SUPPORT_CONTACT[1:]}")],
    ]
    if uid in ADMIN_IDS:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def converter_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 PDF → TXT", callback_data="cv:pdf")],
        [InlineKeyboardButton(text="📄 TXT → PDF", callback_data="cv:txt_to_pdf")],
        [InlineKeyboardButton(text="📝 DOCX → TXT", callback_data="cv:docx")],
        [InlineKeyboardButton(text="📝 TXT → DOCX", callback_data="cv:txt_to_docx")],
        [InlineKeyboardButton(text="📎 Объединить PDF", callback_data="cv:pdf_merge")],
        [InlineKeyboardButton(text="📸 Фото → PDF", callback_data="cv:photo_pdf")],
        [InlineKeyboardButton(text="🖼 Фото → TXT (OCR)", callback_data="cv:ocr")],
        [InlineKeyboardButton(text="🎙 Голос/аудио → TXT", callback_data="cv:audio")],
        [InlineKeyboardButton(text="📺 YouTube → транскрипт", callback_data="cv:yt_tr")],
        [InlineKeyboardButton(text="🎬 Видео → GIF", callback_data="cv:gif")],
        [InlineKeyboardButton(text="📦 Сжать видео", callback_data="cv:compress")],
        [InlineKeyboardButton(text="📚 Плейлист → ZIP", callback_data="cv:playlist")],
        [InlineKeyboardButton(text="🔲 QR-код", callback_data="qr")],
        [InlineKeyboardButton(text="🎨 Убрать фон", callback_data="remove_bg")],
        [InlineKeyboardButton(text="🎨 Сменить размер фото", callback_data="resize_photo")],
        [InlineKeyboardButton(text="📝 Суммаризация AI", callback_data="summarize")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])

def quality_kb(premium, url):
    s = url[:50]
    rows = [[InlineKeyboardButton(text="📱 360p", callback_data=f"q:360:{s}")]]
    if premium:
        rows += [
            [InlineKeyboardButton(text="🎥 720p", callback_data=f"q:720:{s}")],
            [InlineKeyboardButton(text="🎬 1080p", callback_data=f"q:1080:{s}")],
            [InlineKeyboardButton(text="🎵 Только mp3", callback_data=f"q:mp3:{s}")]]
    else:
        rows += [
            [InlineKeyboardButton(text="🔒 720p", callback_data="locked")],
            [InlineKeyboardButton(text="🔒 1080p", callback_data="locked")],
            [InlineKeyboardButton(text="🔒 mp3", callback_data="locked")]]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def tariff_kb(uid):
    discount, code = get_user_discount(uid)
    rows = []
    for key, t in TARIFFS.items():
        price = calc_price(t["price"], uid)
        label = f"{t['title']} — {price} ₽" + (f" (было {t['price']})" if discount else "")
        rows.append([InlineKeyboardButton(text=label, callback_data=f"tariff:{key}")])
    if not get_user(uid)["trial_used"] and not is_premium(uid):
        rows.append([InlineKeyboardButton(text=f"🎁 Пробный на {TRIAL_DAYS} день", callback_data="trial")])
    if discount:
        rows.append([InlineKeyboardButton(text=f"🎟 {code} (-{discount}%) ❌", callback_data="promo_reset")])
    else:
        rows.append([InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="promo")])
    rows.append([InlineKeyboardButton(text="🎁 Активировать код Premium", callback_data="gift")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def pay_kb(key):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Отправить чек", callback_data=f"receipt:{key}")],
        [InlineKeyboardButton(text="⬅️ К тарифам", callback_data="buy")]])

def after_receipt_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
        [InlineKeyboardButton(text="❓ Поддержка", url=f"https://t.me/{SUPPORT_CONTACT[1:]}")]])

def admin_review_kb(pid, uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve:{pid}:{uid}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pid}:{uid}")]])

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="🎁 Выдать Premium", callback_data="adm:grant")],
        [InlineKeyboardButton(text="❌ Снять Premium", callback_data="adm:revoke")],
        [InlineKeyboardButton(text="👤 Найти юзера", callback_data="adm:find")],
        [InlineKeyboardButton(text="📋 Список Premium", callback_data="adm:premium_list")],
        [InlineKeyboardButton(text="📤 Экспорт (CSV)", callback_data="adm:export")],
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="adm:promos")],
        [InlineKeyboardButton(text="⏳ Заявки", callback_data="adm:pending")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]])
# ============================== СТАРТ ==============================
@router.callback_query(F.data == "check_sub")
async def check_sub_handler(cb: CallbackQuery):
    if await check_subscription(cb.from_user.id):
        await cb.answer("✅ Подписка подтверждена!")
        await cb.message.edit_text(
            "✅ <b>Спасибо за подписку!</b>\n\nНажмите «🚀 Начать».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Начать", callback_data="menu")]]))
    else:
        await cb.answer("❌ Вы ещё не подписались!", show_alert=True)

@router.callback_query(F.data.startswith("captcha_"))
async def captcha_answer(cb: CallbackQuery):
    _, chosen, correct = cb.data.split("_")
    if chosen == correct:
        set_captcha_passed(cb.from_user.id)
        await cb.answer("✅ Верно!")
        await cb.message.edit_text(
            "✅ <b>Проверка пройдена!</b>\n\nНажмите «🚀 Начать».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Начать", callback_data="menu")]]))
    else:
        await cb.answer("❌ Неверно", show_alert=True)
        await send_captcha(cb)

@router.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    args = msg.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_id = int(args[1][4:])
            if ref_id != uid and not get_user(uid)["referrer_id"]:
                set_referrer(uid, ref_id)
                set_premium(uid, 3)
                try:
                    await bot.send_message(ref_id,
                        "🎉 По вашей ссылке пришёл друг!\nКогда оплатит — 10% вам.",
                        parse_mode="HTML")
                except Exception: pass
        except Exception: pass
    if len(args) > 1 and args[1].startswith("gift_"):
        code = args[1][5:]
        ok, days, text = use_gift(code, uid)
        if ok:
            set_premium(uid, days)
            await msg.answer(f"🎉 Подарок активирован! Premium на {days} дней.")
    u = get_user(uid)
    if u.get("is_pro"): status = "💎 Pro"
    elif u["is_premium"]: status = "⭐ Premium"
    else: status = "🆓 Free"
    until = f" до {u['premium_until']}" if u["is_premium"] else ""
    await msg.answer(
        f"👋 <b>Kthronix</b> — твой медиа-бот\n\n"
        f"Статус: <b>{status}</b>{until}\n\n"
        "• Кидай ссылку — предложу качество\n"
        "• Текст → .txt файлом\n"
        "• Конвертер: PDF, DOCX, OCR, QR, фон\n"
        "• Скачивание без watermark\n\n"
        "Выберите действие:",
        parse_mode="HTML", reply_markup=main_menu_kb(uid))

@router.callback_query(F.data == "menu")
async def back_to_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    u = get_user(cb.from_user.id)
    if u.get("is_pro"): status = "💎 Pro"
    elif u["is_premium"]: status = "⭐ Premium"
    else: status = "🆓 Free"
    until = f" до {u['premium_until']}" if u["is_premium"] else ""
    text = f"👋 <b>Kthronix</b>\n\nСтатус: <b>{status}</b>{until}\n\nВыберите:"
    try:
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=main_menu_kb(cb.from_user.id))
    except Exception:
        await cb.message.answer(text, parse_mode="HTML",
                                reply_markup=main_menu_kb(cb.from_user.id))
    await cb.answer()

# ---------- Профиль ----------
@router.callback_query(F.data == "profile")
async def profile(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    if u.get("is_pro"): prem = "💎 Pro"
    elif u["is_premium"]: prem = "⭐ Premium"
    else: prem = "🆓 Free"
    until = u["premium_until"] or "—"
    await cb.message.edit_text(
        f"👤 <b>Профиль</b>\n\n"
        f"ID: <code>{cb.from_user.id}</code>\n"
        f"Статус: <b>{prem}</b>\nPremium до: {until}\n"
        f"Скачано: {u['used_today']} / {FREE_DAILY_LIMIT}\n"
        f"Бонусных: {u['bonus_downloads']}\n"
        f"Приглашено: {u['ref_count']}\n"
        f"Баланс: <b>{u['partner_balance']} ₽</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Бонус дня", callback_data="daily_bonus")],
            [InlineKeyboardButton(text="💼 Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await cb.answer()

@router.callback_query(F.data == "daily_bonus")
async def daily_bonus(cb: CallbackQuery):
    ok, txt = claim_daily_bonus(cb.from_user.id)
    await cb.answer(txt, show_alert=True)
    if ok: await profile(cb)

# ---------- Рефералка ----------
@router.callback_query(F.data == "referral")
async def referral(cb: CallbackQuery):
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{cb.from_user.id}"
    u = get_user(cb.from_user.id)
    await cb.message.edit_text(
        f"🤝 <b>Пригласи друга — 10%</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"• Друг получает +3 дня Premium\n"
        f"• Когда оплатит — вам 10% на баланс\n\n"
        f"Приглашено: {u['ref_count']}\nБаланс: <b>{u['partner_balance']} ₽</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться",
                                  url=f"https://t.me/share/url?url={link}")],
            [InlineKeyboardButton(text="💼 Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await cb.answer()

# ---------- Баланс ----------
@router.callback_query(F.data == "balance")
async def balance_view(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    bal = u["partner_balance"]
    rows = []
    if bal >= 150:
        rows.append([InlineKeyboardButton(text="💳 Premium 1 мес — 150 ₽", callback_data="balance_buy:1m")])
    if bal >= 400:
        rows.append([InlineKeyboardButton(text="💳 Premium 3 мес — 400 ₽", callback_data="balance_buy:3m")])
    if bal >= 1200:
        rows.append([InlineKeyboardButton(text="💳 Premium 1 год — 1200 ₽", callback_data="balance_buy:12m")])
    rows += [
        [InlineKeyboardButton(text="📤 Перевести", callback_data="balance_transfer")],
        [InlineKeyboardButton(text="📜 История", callback_data="balance_history")],
        [InlineKeyboardButton(text="🤝 Пригласить", callback_data="referral")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]
    await cb.message.edit_text(
        f"💼 <b>Мой баланс</b>\n\nБаланс: <b>{bal} ₽</b>\nПриглашено: {u['ref_count']}\n\n"
        + ("✅ Хватает на Premium" if bal >= 150 else f"⚠️ До 150 ₽: {150 - bal} ₽"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()

@router.callback_query(F.data.startswith("balance_buy:"))
async def balance_buy(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    t = TARIFFS.get(key)
    if not t: await cb.answer("Ошибка", show_alert=True); return
    u = get_user(cb.from_user.id)
    if u["partner_balance"] < t["price"]:
        await cb.answer("Мало средств", show_alert=True); return
    add_partner_balance(cb.from_user.id, -t["price"])
    set_premium(cb.from_user.id, t["days"], t["level"])
    nb = get_user(cb.from_user.id)["partner_balance"]
    await cb.message.edit_text(
        f"✅ <b>{t['title']} активирован!</b>\n\n"
        f"Списано: {t['price']} ₽\nОстаток: <b>{nb} ₽</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await cb.answer("Активирован")

@router.callback_query(F.data == "balance_transfer")
async def balance_transfer_start(cb: CallbackQuery, state: FSMContext):
    u = get_user(cb.from_user.id)
    if u["partner_balance"] <= 0:
        await cb.answer("Баланс пуст", show_alert=True); return
    await state.set_state(TransferFlow.waiting_user)
    await cb.message.edit_text(
        f"📤 <b>Перевод баланса</b>\n\nБаланс: <b>{u['partner_balance']} ₽</b>\n\n"
        f"Отправьте <code>user_id</code> или <code>@username</code>.\n\nОтмена — /cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="balance")]]))
    await cb.answer()

@router.message(TransferFlow.waiting_user, F.text)
async def balance_transfer_user(msg: Message, state: FSMContext):
    q = msg.text.strip().lstrip("@")
    target = None
    if q.lstrip("-").isdigit(): target = int(q)
    else:
        with _con() as con:
            row = con.execute("SELECT user_id FROM users WHERE LOWER(username)=?", (q.lower(),)).fetchone()
            if row: target = row["user_id"]
    if not target: await msg.answer("❌ Не найден. /cancel"); return
    if target == msg.from_user.id: await msg.answer("❌ Нельзя себе"); return
    await state.update_data(target_id=target)
    await state.set_state(TransferFlow.waiting_amount)
    tu = get_user(target)
    uname = f"@{tu['username']}" if tu["username"] else f"ID {target}"
    await msg.answer(
        f"👤 Получатель: <b>{uname}</b>\n\nСколько ₽?\n"
        f"Баланс: <b>{get_user(msg.from_user.id)['partner_balance']} ₽</b>\n\nОтмена — /cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="balance")]]))

@router.message(TransferFlow.waiting_amount, F.text)
async def balance_transfer_amount(msg: Message, state: FSMContext):
    if not msg.text.strip().isdigit():
        await msg.answer("❌ Целое число"); return
    amount = int(msg.text.strip())
    data = await state.get_data()
    target = data["target_id"]
    ok, text = transfer_balance(msg.from_user.id, target, amount)
    await state.clear()
    if not ok:
        await msg.answer(f"❌ {text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ К балансу", callback_data="balance")]]))
        return
    nb = get_user(msg.from_user.id)["partner_balance"]
    await msg.answer(
        f"✅ <b>Перевод!</b>\n\nКому: <code>{target}</code>\n"
        f"Сумма: <b>{amount} ₽</b>\nБаланс: <b>{nb} ₽</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💼 К балансу", callback_data="balance")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    try:
        await bot.send_message(target,
            f"💰 <b>Вам перевели {amount} ₽!</b>\n\n"
            f"От: <code>{msg.from_user.id}</code>\n"
            f"Баланс: <b>{get_user(target)['partner_balance']} ₽</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💼 Баланс", callback_data="balance")]]))
    except Exception: pass

@router.callback_query(F.data == "balance_history")
async def balance_history(cb: CallbackQuery):
    uid = cb.from_user.id
    with _con() as con:
        rows = con.execute("SELECT * FROM balance_transfers WHERE from_user=? OR to_user=? "
                           "ORDER BY id DESC LIMIT 15", (uid, uid)).fetchall()
    if not rows: await cb.answer("Пусто", show_alert=True); return
    text = "📜 <b>История</b>\n\n"
    for r in rows:
        if r["from_user"] == uid:
            text += f"📤 → <code>{r['to_user']}</code> — <b>-{r['amount']} ₽</b>\n"
        else:
            text += f"📥 ← <code>{r['from_user']}</code> — <b>+{r['amount']} ₽</b>\n"
    await cb.message.edit_text(text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К балансу", callback_data="balance")]]))
    await cb.answer()

# ---------- Помощь ----------
@router.callback_query(F.data == "help_download")
async def help_download(cb: CallbackQuery):
    await cb.message.edit_text(
        "📥 <b>Как скачать видео</b>\n\n"
        "Отправьте ссылку: YouTube, TikTok, Instagram, Twitter, VK.\n"
        "Бот предложит варианты качества.\n\n"
        "🎬 Все видео — <b>без водяных знаков</b>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await cb.answer()

@router.callback_query(F.data == "help_txt")
async def help_txt(cb: CallbackQuery):
    await cb.message.edit_text(
        "📝 <b>Текст → TXT</b>\n\nОтправьте текст — получите .txt.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await cb.answer()

# ---------- Подписка ----------
@router.callback_query(F.data == "buy")
async def buy(cb: CallbackQuery):
    discount, code = get_user_discount(cb.from_user.id)
    dtext = f"\n\n🎟 <b>{code}</b> — скидка <b>{discount}%</b>" if discount else ""
    text = (f"⭐ <b>Тарифы</b>\n\n"
            f"⭐ <b>Premium</b> — 720p, 1080p, mp3, лимиты\n"
            f"💎 <b>Pro</b> — всё безлимит\n"
            f"👨‍👩‍👧 <b>Family</b> — Premium себе + 2 кода друзьям{dtext}\n\nВыберите:")
    try:
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=tariff_kb(cb.from_user.id))
    except Exception:
        await cb.message.answer(text, parse_mode="HTML",
                                reply_markup=tariff_kb(cb.from_user.id))
    await cb.answer()

@router.callback_query(F.data == "premium_info")
async def premium_info(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    auto = "✅ Вкл" if u["auto_renew"] else "❌ Выкл"
    lvl = "💎 Pro" if u.get("is_pro") else "⭐ Premium"
    await cb.message.edit_text(
        f"{lvl} <b>активен</b>\n\nДо: <b>{u['premium_until']}</b>\nАвто: {auto}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Продлить", callback_data="buy")],
            [InlineKeyboardButton(text=f"⚙️ Авто: {'выкл' if u['auto_renew'] else 'вкл'}",
                                  callback_data="toggle_auto")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await cb.answer()

@router.callback_query(F.data == "toggle_auto")
async def toggle_auto(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    new = 0 if u["auto_renew"] else 1
    set_auto_renew(cb.from_user.id, new)
    await cb.answer("✅" if new else "Выкл")
    await premium_info(cb)

@router.callback_query(F.data == "trial")
async def trial(cb: CallbackQuery):
    u = get_user(cb.from_user.id)
    if u["trial_used"]: await cb.answer("Использован", show_alert=True); return
    if u["is_premium"]: await cb.answer("Уже есть", show_alert=True); return
    set_premium(cb.from_user.id, TRIAL_DAYS)
    set_trial_used(cb.from_user.id)
    await cb.message.edit_text(
        f"🎁 <b>Пробный Premium на {TRIAL_DAYS} день активирован!</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await cb.answer("Активировано")

# ---------- Промокод ----------
@router.callback_query(F.data == "promo")
async def promo_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoFlow.waiting_code)
    await cb.message.edit_text("🎟 Введите промокод:\n\nОтмена — /cancel",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="buy")]]))
    await cb.answer()

@router.message(PromoFlow.waiting_code, F.text)
async def promo_check(msg: Message, state: FSMContext):
    await state.clear()
    code = msg.text.strip().upper()
    ok, discount, text = apply_promo(code)
    if not ok:
        await msg.answer(f"❌ {text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ К тарифам", callback_data="buy")]]))
        return
    set_user_discount(msg.from_user.id, discount, code)
    await msg.answer(
        f"✅ <b>Промокод {code} активирован!</b>\n\nСкидка: <b>-{discount}%</b>",
        parse_mode="HTML", reply_markup=tariff_kb(msg.from_user.id))

@router.callback_query(F.data == "promo_reset")
async def promo_reset(cb: CallbackQuery):
    clear_user_discount(cb.from_user.id)
    await cb.answer("Сброшено")
    await buy(cb)

# ---------- Активация кода Premium ----------
@router.callback_query(F.data == "gift")
async def gift_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(GiftUseFlow.waiting_code)
    await cb.message.edit_text(
        "🎁 <b>Активация кода Premium</b>\n\n"
        "Введите код, который вы получили.\n"
        "Код состоит из заглавных букв и цифр, например: <code>A3K9P2M7X1</code>\n\n"
        "Отмена — /cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="buy")]]))
    await cb.answer()

@router.message(GiftUseFlow.waiting_code, F.text)
async def gift_use_check(msg: Message, state: FSMContext):
    await state.clear()
    raw = msg.text.strip()
    ok, days, text = use_gift(raw, msg.from_user.id)
    if ok:
        set_premium(msg.from_user.id, days)
        u = get_user(msg.from_user.id)
        await msg.answer(
            f"🎉 <b>Код активирован!</b>\n\n"
            f"Вам начислено <b>{days} дней Premium</b>.\n"
            f"Действует до: <b>{u['premium_until']}</b>\n\n"
            f"Теперь доступны 720p, 1080p, mp3 и безлимит.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(msg.from_user.id))
    else:
        await msg.answer(
            f"❌ <b>{text}</b>\n\n"
            f"Вы ввели: <code>{raw[:30]}</code>\n\n"
            f"Проверьте, что код скопирован точно — без пробелов.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎁 Ввести ещё раз", callback_data="gift")],
                [InlineKeyboardButton(text="⬅️ К тарифам", callback_data="buy")]]))

# ---------- Оплата ----------
@router.callback_query(F.data.startswith("tariff:"))
async def tariff(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    t = TARIFFS.get(key)
    if not t: await cb.answer("Ошибка", show_alert=True); return
    price = calc_price(t["price"], cb.from_user.id)
    discount, code = get_user_discount(cb.from_user.id)
    dline = f"🎟 {code} (-{discount}%)\nБыло {t['price']} → <b>{price} ₽</b>\n\n" if discount else ""
    extra = ""
    if key == "family":
        extra = "\n📌 Вы сразу получите Premium на 30 дней + 2 кода для друзей."
    await cb.message.edit_text(
        f"💳 <b>{t['title']}</b>\n\n{dline}К оплате: <b>{price} ₽</b>{extra}\n\n"
        f"<b>Карта:</b>\n<code>{CARD_NUMBER}</code>\n{CARD_BANK}\n{CARD_HOLDER}\n\n"
        f"⚠️ Комментарий: <code>{cb.from_user.id}</code>\n\nПосле → «📸 Отправить чек»",
        parse_mode="HTML", reply_markup=pay_kb(key))
    await cb.answer()

@router.callback_query(F.data.startswith("receipt:"))
async def ask_receipt(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    await state.set_state(PayFlow.waiting_receipt)
    await state.update_data(tariff=key)
    await cb.message.edit_text("📸 Пришлите <b>фото чека</b>.\n\nОтмена — /cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu")]]))
    await cb.answer()

@router.message(Command("cancel"))
async def cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Отменено.", reply_markup=main_menu_kb(msg.from_user.id))

@router.message(PayFlow.waiting_receipt, F.photo)
async def on_receipt(msg: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("tariff", "1m")
    t = TARIFFS.get(key, TARIFFS["1m"])
    price = calc_price(t["price"], msg.from_user.id)
    discount, code = get_user_discount(msg.from_user.id)
    file_id = msg.photo[-1].file_id
    uid = msg.from_user.id
    pid = create_payment(uid, price, t["days"], file_id, t["level"])
    await state.clear()
    uname = f"@{msg.from_user.username}" if msg.from_user.username else "нет"
    dinfo = f"\n🎟 {code} (-{discount}%)" if discount else ""
    for admin in ADMIN_IDS:
        try:
            await bot.send_photo(admin, photo=file_id,
                caption=(f"💰 <b>Заявка</b>\n\n"
                         f"👤 {msg.from_user.full_name} ({uname})\n"
                         f"🆔 <code>{uid}</code>\n"
                         f"💵 <b>{price} ₽</b> — {t['title']}{dinfo}\n🧾 #{pid}"),
                parse_mode="HTML", reply_markup=admin_review_kb(pid, uid))
        except Exception: pass
    await msg.answer("✅ Чек отправлен!\n\nОбычно 5–30 минут.\n\n"
                     f"Вопросы — {SUPPORT_CONTACT}", reply_markup=after_receipt_kb())

@router.message(PayFlow.waiting_receipt)
async def wrong_receipt(msg: Message):
    await msg.answer("Пришлите <b>фото</b> чека.", parse_mode="HTML")

# ---------- Подтверждение ----------
@router.callback_query(F.data.startswith("approve:"))
async def approve(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет", show_alert=True); return
    _, pid, uid = cb.data.split(":")
    pid, uid = int(pid), int(uid)
    p = get_payment(pid)
    if not p or p["status"] != "pending":
        await cb.answer("Обработано", show_alert=True); return

    level = p.get("level") or "premium"
    is_family = (p["days"] == 30 and p["amount"] == 300 and level == "premium")

    if is_family:
        set_premium(uid, 30, "premium")
        codes = create_multiple_gifts(uid, 30, 2)
        set_payment_status(pid, "approved")
        clear_user_discount(uid)

        u = get_user(uid)
        codes_text = "\n".join(f"<code>{c}</code>" for c in codes)
        try:
            await bot.send_message(
                uid,
                f"👨‍👩‍👧 <b>Family активирован!</b>\n\n"
                f"✅ Вам начислен Premium на 30 дней\n"
                f"📅 Действует до: <b>{u['premium_until']}</b>\n\n"
                f"🎁 <b>У вас 2 кода для друзей:</b>\n\n{codes_text}\n\n"
                f"<b>Как использовать:</b>\n"
                f"• Отправьте код другу\n"
                f"• Друг вводит: <b>⭐ Premium → 🎁 Активировать код</b>\n"
                f"• Он получает Premium на 30 дней\n\n"
                f"⚠️ Каждый код — одноразовый.",
                parse_mode="HTML", reply_markup=main_menu_kb(uid))
        except Exception: pass
    else:
        set_premium(uid, p["days"], level)
        set_payment_status(pid, "approved")
        clear_user_discount(uid)
        try:
            await bot.send_message(uid, f"⭐ <b>Подписка на {p['days']} дней!</b>",
                                   parse_mode="HTML", reply_markup=main_menu_kb(uid))
        except Exception: pass

    u = get_user(uid)
    if u["referrer_id"]:
        bonus = int(p["amount"] * 0.10)
        add_partner_balance(u["referrer_id"], bonus)
        ref_u = get_user(u["referrer_id"])
        try:
            await bot.send_message(u["referrer_id"],
                f"💰 <b>Партнёрское</b>\n\nДруг оплатил {p['amount']} ₽.\n"
                f"Начислено: <b>+{bonus} ₽</b>\nБаланс: <b>{ref_u['partner_balance']} ₽</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💼 Баланс", callback_data="balance")]]))
        except Exception: pass

    try:
        await cb.message.edit_caption((cb.message.caption or "") + "\n\n✅ Подтверждено",
                                      parse_mode="HTML")
    except Exception: pass
    await cb.answer("ОК")

@router.callback_query(F.data.startswith("reject:"))
async def reject(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет", show_alert=True); return
    _, pid, uid = cb.data.split(":")
    pid, uid = int(pid), int(uid)
    p = get_payment(pid)
    if not p or p["status"] != "pending":
        await cb.answer("Обработано", show_alert=True); return
    set_payment_status(pid, "rejected")
    try:
        await cb.message.edit_caption((cb.message.caption or "") + "\n\n❌ Отклонено",
                                      parse_mode="HTML")
    except Exception: pass
    try:
        await bot.send_message(uid, f"❌ Оплата не найдена. Связь: {SUPPORT_CONTACT}",
                               reply_markup=main_menu_kb(uid))
    except Exception: pass
    await cb.answer("Отклонено")

# ---------- Админка ----------
@router.callback_query(F.data == "admin")
async def admin_panel(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer("Нет", show_alert=True); return
    await cb.message.edit_text("🛠 <b>Админ-панель</b>\n\nВыберите:",
                               parse_mode="HTML", reply_markup=admin_panel_kb())
    await cb.answer()

@router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    today = str(date.today())
    with _con() as con:
        users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        prem = con.execute("SELECT COUNT(*) c FROM users WHERE is_premium=1").fetchone()["c"]
        pro = con.execute("SELECT COUNT(*) c FROM users WHERE is_pro=1").fetchone()["c"]
        income = con.execute("SELECT COALESCE(SUM(amount),0) s FROM payments "
                             "WHERE status='approved' AND date(created_at)=?", (today,)).fetchone()["s"]
        pend = con.execute("SELECT COUNT(*) c FROM payments WHERE status='pending'").fetchone()["c"]
    await cb.message.edit_text(
        f"📊 <b>Статистика</b>\n\n👥 Юзеров: {users}\n⭐ Premium: {prem}\n💎 Pro: {pro}\n"
        f"🧾 Ожидают: {pend}\n💰 Доход: {income} ₽",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin")]]))
    await cb.answer()

@router.callback_query(F.data == "adm:grant")
async def adm_grant(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    await state.set_state(GrantFlow.waiting_data)
    await cb.message.edit_text("🎁 <code>user_id дни [premium|pro]</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin")]]))
    await cb.answer()

@router.message(GrantFlow.waiting_data, F.text)
async def adm_grant_save(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    parts = msg.text.split()
    if not parts or not parts[0].lstrip("-").isdigit():
        await msg.answer("❌ user_id дни [premium|pro]"); return
    uid = int(parts[0])
    days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else PREMIUM_DAYS
    level = parts[2].lower() if len(parts) > 2 and parts[2].lower() in ("premium", "pro") else "premium"
    get_user(uid)
    set_premium(uid, days, level)
    await state.clear()
    try:
        await bot.send_message(uid, f"🎁 <b>Подписка на {days} дней ({level})!</b>",
                               parse_mode="HTML", reply_markup=main_menu_kb(uid))
    except Exception: pass
    await msg.answer(f"✅ {uid} — {days} дней, {level}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Панель", callback_data="admin")]]))

@router.callback_query(F.data == "adm:revoke")
async def adm_revoke(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    await state.set_state(RevokeFlow.waiting_id)
    await cb.message.edit_text("❌ <code>user_id</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin")]]))
    await cb.answer()

@router.message(RevokeFlow.waiting_id, F.text)
async def adm_revoke_save(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    parts = msg.text.split()
    if not parts or not parts[0].lstrip("-").isdigit():
        await msg.answer("❌ user_id"); return
    uid = int(parts[0])
    revoke_premium(uid)
    await state.clear()
    try:
        await bot.send_message(uid, "❌ Подписка снята.", reply_markup=main_menu_kb(uid))
    except Exception: pass
    await msg.answer(f"✅ Снят {uid}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Панель", callback_data="admin")]]))

@router.callback_query(F.data == "adm:find")
async def adm_find(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    await state.set_state(FindFlow.waiting_id)
    await cb.message.edit_text("👤 <code>user_id</code> или <code>@username</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin")]]))
    await cb.answer()

@router.message(FindFlow.waiting_id, F.text)
async def adm_find_show(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    q = msg.text.strip().lstrip("@")
    uid = None
    if q.lstrip("-").isdigit(): uid = int(q)
    else:
        with _con() as con:
            row = con.execute("SELECT user_id FROM users WHERE LOWER(username)=?", (q.lower(),)).fetchone()
            if row: uid = row["user_id"]
    if not uid:
        await msg.answer("❌ <b>Не найден</b>\n\nВозможно, не нажимал /start.",
                         parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [InlineKeyboardButton(text="👤 Поиск", callback_data="adm:find")],
                             [InlineKeyboardButton(text="⬅️ Панель", callback_data="admin")]]))
        return
    await state.clear()
    u = get_user(uid)
    if u.get("is_pro"): prem = "💎 Pro"
    elif u["is_premium"]: prem = "⭐ Premium"
    else: prem = "🆓 Free"
    with _con() as con:
        pm = con.execute("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM payments "
                         "WHERE user_id=? AND status='approved'", (uid,)).fetchone()
    text = (f"👤 <b>Карточка</b>\n\nID: <code>{uid}</code>\n"
            f"@{u['username'] or '—'}\nСтатус: <b>{prem}</b>\n"
            f"До: {u['premium_until'] or '—'}\nБаланс: {u['partner_balance']} ₽\n"
            f"Платежей: {pm['c']} на {pm['s']} ₽")
    rows = []
    if u["is_premium"]:
        rows.append([InlineKeyboardButton(text="❌ Снять", callback_data=f"quick_revoke:{uid}")])
    else:
        rows.append([InlineKeyboardButton(text="🎁 30 дней Premium", callback_data=f"quick_grant:{uid}:30:premium")])
    rows.append([InlineKeyboardButton(text="⬅️ Панель", callback_data="admin")])
    await msg.answer(text, parse_mode="HTML",
                     reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("quick_grant:"))
async def quick_grant(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    parts = cb.data.split(":")
    uid, days = int(parts[1]), int(parts[2])
    level = parts[3] if len(parts) > 3 else "premium"
    set_premium(uid, days, level)
    try:
        await bot.send_message(uid, f"🎁 <b>Подписка на {days} дней ({level})!</b>",
                               parse_mode="HTML", reply_markup=main_menu_kb(uid))
    except Exception: pass
    await cb.answer(f"✅ +{days} {level}", show_alert=True)

@router.callback_query(F.data.startswith("quick_revoke:"))
async def quick_revoke(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    uid = int(cb.data.split(":")[1])
    revoke_premium(uid)
    try:
        await bot.send_message(uid, "❌ Подписка снята.", reply_markup=main_menu_kb(uid))
    except Exception: pass
    await cb.answer("✅ Снят", show_alert=True)

@router.callback_query(F.data == "adm:premium_list")
async def adm_premium_list(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    with _con() as con:
        rows = con.execute("SELECT user_id, username, premium_until, is_pro FROM users "
                           "WHERE is_premium=1 ORDER BY premium_until LIMIT 30").fetchall()
    if not rows: await cb.answer("Нет", show_alert=True); return
    text = "📋 <b>Активные подписки:</b>\n\n"
    for r in rows:
        icon = "💎" if r["is_pro"] else "⭐"
        text += f"{icon} <code>{r['user_id']}</code> @{r['username'] or '—'} — до {r['premium_until']}\n"
    await cb.message.edit_text(text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin")]]))
    await cb.answer()

@router.callback_query(F.data == "adm:pending")
async def adm_pending(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    with _con() as con:
        rows = con.execute("SELECT * FROM payments WHERE status='pending' "
                           "ORDER BY id DESC LIMIT 10").fetchall()
    if not rows: await cb.answer("Нет заявок", show_alert=True); return
    text = "⏳ <b>Заявки:</b>\n\n"
    for r in rows:
        lvl = r["level"] or "premium"
        text += f"#{r['id']} — <code>{r['user_id']}</code> — {r['amount']} ₽ ({lvl})\n"
    await cb.message.edit_text(text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin")]]))
    await cb.answer()

@router.callback_query(F.data == "adm:export")
async def adm_export(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    with _con() as con:
        rows = con.execute("SELECT * FROM payments ORDER BY id DESC").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "user_id", "amount", "days", "level", "status", "created_at"])
    for r in rows:
        w.writerow([r["id"], r["user_id"], r["amount"], r["days"],
                    r["level"], r["status"], r["created_at"]])
    await cb.message.answer_document(
        BufferedInputFile(out.getvalue().encode("utf-8"), filename="payments.csv"))
    await cb.answer()

# ---------- Промокоды ----------
@router.callback_query(F.data == "adm:promos")
async def adm_promos(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    promos = list_promos()
    text = "🎟 <b>Промокоды</b>\n\n"
    if not promos: text += "Пока нет."
    else:
        for p in promos:
            st = "🟢" if p["active"] else "🔴"
            text += f"{st} <code>{p['code']}</code> — -{p['discount']}% · {p['uses_left']}\n"
    rows = [[InlineKeyboardButton(text="➕ Создать", callback_data="adm:promo_new")]]
    for p in promos:
        tt = "⏸" if p["active"] else "▶️"
        rows.append([
            InlineKeyboardButton(text=f"{tt} {p['code']}",
                                 callback_data=f"promo_toggle:{p['code']}:{0 if p['active'] else 1}"),
            InlineKeyboardButton(text="🗑", callback_data=f"promo_del:{p['code']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin")])
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()

@router.callback_query(F.data.startswith("promo_del:"))
async def promo_del(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    code = cb.data.split(":")[1]
    delete_promo(code)
    await cb.answer(f"🗑 {code}")
    await adm_promos(cb)

@router.callback_query(F.data.startswith("promo_toggle:"))
async def promo_toggle(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    _, code, active = cb.data.split(":")
    toggle_promo(code, int(active))
    await cb.answer("✅")
    await adm_promos(cb)

@router.callback_query(F.data == "adm:promo_new")
async def adm_promo_new(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    await state.set_state(PromoNewFlow.waiting_data)
    await cb.message.edit_text(
        "🎟 <code>КОД СКИДКА КОЛИЧЕСТВО</code>\n\nПример: <code>NEWYEAR 20 100</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="adm:promos")]]))
    await cb.answer()

@router.message(PromoNewFlow.waiting_data, F.text)
async def adm_promo_save(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    parts = msg.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await msg.answer("❌ КОД СКИДКА КОЛИЧЕСТВО"); return
    add_promo(parts[0], int(parts[1]), int(parts[2]))
    await state.clear()
    await msg.answer(f"✅ {parts[0].upper()} создан.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎟 К промокодам", callback_data="adm:promos")]]))

# ---------- Конвертер ----------
@router.callback_query(F.data == "converter")
async def converter(cb: CallbackQuery):
    await cb.message.edit_text("🔄 <b>Конвертер</b>", parse_mode="HTML", reply_markup=converter_kb())
    await cb.answer()

@router.callback_query(F.data == "cv:txt_to_pdf")
async def txt_to_pdf_start(cb: CallbackQuery, state: FSMContext):
    ok, reason = check_feature_limit(cb.from_user.id, "txt_to_pdf")
    if not ok: await cb.answer(reason, show_alert=True); return
    await state.set_state(TxtConvertFlow.waiting_text)
    await state.update_data(target="pdf", feature="txt_to_pdf")
    await cb.message.edit_text(
        "📄 <b>TXT → PDF</b>\n\nОтправьте текст или .txt файл.\n\n/cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
    await cb.answer()

@router.callback_query(F.data == "cv:txt_to_docx")
async def txt_to_docx_start(cb: CallbackQuery, state: FSMContext):
    ok, reason = check_feature_limit(cb.from_user.id, "txt_to_docx")
    if not ok: await cb.answer(reason, show_alert=True); return
    await state.set_state(TxtConvertFlow.waiting_text)
    await state.update_data(target="docx", feature="txt_to_docx")
    await cb.message.edit_text(
        "📝 <b>TXT → DOCX</b>\n\nОтправьте текст или .txt файл.\n\n/cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
    await cb.answer()

@router.message(TxtConvertFlow.waiting_text, F.text)
async def txt_convert_text(msg: Message, state: FSMContext):
    data = await state.get_data()
    target = data.get("target", "pdf")
    feature = data.get("feature", "txt_to_pdf")
    await state.clear()
    text = msg.text.strip()
    if len(text) < 2: await msg.answer("❌ Коротко"); return
    await msg.answer("⏳ Конвертирую...")
    title = "Документ"
    first = text.split("\n", 1)[0].strip()
    if 0 < len(first) <= 80: title = first
    try:
        with tempfile.TemporaryDirectory() as tmp:
            if target == "pdf":
                path = await asyncio.to_thread(txt_to_pdf, text, tmp, title)
                fname = f"{title[:40]}.pdf"
            else:
                path = await asyncio.to_thread(txt_to_docx, text, tmp, title)
                fname = f"{title[:40]}.docx"
            use_feature(msg.from_user.id, feature)
            await msg.answer_document(
                FSInputFile(path, filename=fname),
                caption=f"✅ <b>{fname}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Конвертер", callback_data="converter")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    except Exception as e: await msg.answer(f"❌ {e}")

@router.message(TxtConvertFlow.waiting_text, F.document)
async def txt_convert_file(msg: Message, state: FSMContext):
    if not msg.document.file_name.lower().endswith(".txt"):
        await msg.answer("❌ Нужен .txt"); return
    data = await state.get_data()
    target = data.get("target", "pdf")
    feature = data.get("feature", "txt_to_pdf")
    await state.clear()
    await msg.answer("⏳ Конвертирую...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = await bot.get_file(msg.document.file_id)
            local = os.path.join(tmp, "input.txt")
            await bot.download_file(f.file_path, local)
            with open(local, "r", encoding="utf-8", errors="ignore") as fp: text = fp.read()
            if len(text.strip()) < 2: await msg.answer("❌ Пусто"); return
            title = os.path.splitext(msg.document.file_name)[0][:40] or "Документ"
            if target == "pdf":
                path = await asyncio.to_thread(txt_to_pdf, text, tmp, title)
                fname = f"{title}.pdf"
            else:
                path = await asyncio.to_thread(txt_to_docx, text, tmp, title)
                fname = f"{title}.docx"
            use_feature(msg.from_user.id, feature)
            await msg.answer_document(
                FSInputFile(path, filename=fname),
                caption=f"✅ <b>{fname}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Конвертер", callback_data="converter")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    except Exception as e: await msg.answer(f"❌ {e}")

@router.callback_query(F.data.startswith("cv:"))
async def cv_choose(cb: CallbackQuery, state: FSMContext):
    t = cb.data.split(":")[1]
    feature_map = {"pdf": "pdf_to_txt", "docx": "docx_to_txt", "ocr": "ocr",
                   "audio": "audio_to_text", "yt_tr": "yt_transcript",
                   "gif": "video_to_gif", "compress": "compress", "playlist": "playlist",
                   "photo_pdf": "photo_pdf"}
    feature = feature_map.get(t, t)
    if t == "pdf_merge":
        ok, reason = check_feature_limit(cb.from_user.id, "pdf_merge")
        if not ok: await cb.answer(reason, show_alert=True); return
        await state.set_state(PDFMergeFlow.collecting)
        await state.update_data(files=[])
        await cb.message.edit_text("📎 Отправьте PDF по одному. Потом «Готово».",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Готово", callback_data="pdf_merge_done")],
                [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
        await cb.answer(); return
    if t == "photo_pdf":
        ok, reason = check_feature_limit(cb.from_user.id, "photo_pdf")
        if not ok: await cb.answer(reason, show_alert=True); return
        await state.set_state(PhotoPDFFlow.collecting)
        await state.update_data(files=[])
        await cb.message.edit_text(
            "📸 Отправляйте фото по одному. Потом «Готово».",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Готово", callback_data="photo_pdf_done")],
                [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
        await cb.answer(); return
    ok, reason = check_feature_limit(cb.from_user.id, feature)
    if not ok: await cb.answer(reason, show_alert=True); return
    if t in ("yt_tr", "playlist"):
        await cb.message.edit_text("📚 Отправьте ссылку. /cancel",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
    else:
        prompts = {"pdf": "📄 PDF", "docx": "📝 DOCX", "ocr": "🖼 Фото",
                   "audio": "🎙 Голос/аудио", "gif": "🎬 Видео", "compress": "📦 Видео"}
        await cb.message.edit_text(f"{prompts.get(t, 'Файл')}. /cancel",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
    await state.set_state(ConvertFlow.waiting_file)
    await state.update_data(cv_type=t, feature=feature)
    await cb.answer()

@router.message(ConvertFlow.waiting_file)
async def cv_process(msg: Message, state: FSMContext):
    data = await state.get_data()
    t = data.get("cv_type")
    feature = data.get("feature", t)
    if t in ("yt_tr", "playlist"):
        m = URL_RE.search(msg.text or "")
        if not m: await msg.answer("❌ Нужна ссылка"); return
        url = m.group(0)
        await state.clear()
        if t == "yt_tr":
            await msg.answer("⏳ Достаю транскрипт...")
            try:
                text = await asyncio.to_thread(youtube_transcript, url)
                with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                    f.write(text); path = f.name
                use_feature(msg.from_user.id, feature)
                await msg.answer_document(FSInputFile(path, filename="transcript.txt"))
                os.unlink(path)
            except Exception as e: await msg.answer(f"❌ {e}")
        else:
            await msg.answer("⏳ Качаю плейлист...")
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    zp = await asyncio.to_thread(download_playlist, url, "360", tmp)
                    use_feature(msg.from_user.id, feature)
                    await msg.answer_document(FSInputFile(zp, filename="playlist.zip"))
            except Exception as e: await msg.answer(f"❌ {e}")
        return
    file_id, fname = None, "file"
    if msg.document: file_id, fname = msg.document.file_id, msg.document.file_name or "file"
    elif msg.photo: file_id, fname = msg.photo[-1].file_id, "photo.jpg"
    elif msg.voice: file_id, fname = msg.voice.file_id, "voice.ogg"
    elif msg.audio: file_id, fname = msg.audio.file_id, msg.audio.file_name or "audio.mp3"
    elif msg.video: file_id, fname = msg.video.file_id, msg.video.file_name or "video.mp4"
    if not file_id: await msg.answer("❌ Файл не получен"); return
    await state.clear()
    await msg.answer("⏳ Обрабатываю...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = await bot.get_file(file_id)
            local = os.path.join(tmp, fname)
            await bot.download_file(f.file_path, local)
            if t == "pdf": text = await asyncio.to_thread(pdf_to_text, local)
            elif t == "docx": text = await asyncio.to_thread(docx_to_text, local)
            elif t == "ocr": text = await asyncio.to_thread(image_to_text, local)
            elif t == "audio": text = await asyncio.to_thread(audio_to_text, local)
            elif t == "gif":
                g = await asyncio.to_thread(video_to_gif, local, tmp)
                use_feature(msg.from_user.id, feature)
                await msg.answer_animation(FSInputFile(g)); return
            elif t == "compress":
                o = await asyncio.to_thread(compress_video, local, tmp)
                use_feature(msg.from_user.id, feature)
                await msg.answer_video(FSInputFile(o)); return
            else: await msg.answer("❌ Тип"); return
            if not text.strip(): await msg.answer("❌ Не распознано"); return
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                f.write(text); op = f.name
            use_feature(msg.from_user.id, feature)
            await msg.answer_document(FSInputFile(op, filename="result.txt"))
            os.unlink(op)
    except Exception as e: await msg.answer(f"❌ {e}")

@router.message(PDFMergeFlow.collecting, F.document)
async def pdf_merge_add(msg: Message, state: FSMContext):
    if not msg.document.file_name.lower().endswith(".pdf"):
        await msg.answer("❌ PDF"); return
    data = await state.get_data()
    files = data.get("files", [])
    files.append(msg.document.file_id)
    await state.update_data(files=files)
    await msg.answer(f"✅ {len(files)}. Ещё или «Готово».")

@router.callback_query(F.data == "pdf_merge_done")
async def pdf_merge_done(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    files = data.get("files", [])
    await state.clear()
    if len(files) < 2: await cb.answer("Минимум 2", show_alert=True); return
    await cb.message.edit_text("⏳ Объединяю...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, fid in enumerate(files):
                f = await bot.get_file(fid)
                p = os.path.join(tmp, f"{i}.pdf")
                await bot.download_file(f.file_path, p)
                paths.append(p)
            out = await asyncio.to_thread(merge_pdfs, paths, tmp)
            use_feature(cb.from_user.id, "pdf_merge")
            await cb.message.answer_document(FSInputFile(out, filename="merged.pdf"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    except Exception as e: await cb.message.answer(f"❌ {e}")

@router.message(PhotoPDFFlow.collecting, F.photo)
async def photo_pdf_add(msg: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("files", [])
    files.append(msg.photo[-1].file_id)
    await state.update_data(files=files)
    await msg.answer(f"✅ {len(files)}. Ещё или «Готово».")

@router.callback_query(F.data == "photo_pdf_done")
async def photo_pdf_done(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    files = data.get("files", [])
    await state.clear()
    if len(files) < 1: await cb.answer("Хотя бы 1 фото", show_alert=True); return
    await cb.message.edit_text("⏳ Собираю PDF...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, fid in enumerate(files):
                f = await bot.get_file(fid)
                p = os.path.join(tmp, f"{i}.jpg")
                await bot.download_file(f.file_path, p)
                paths.append(p)
            out = await asyncio.to_thread(photos_to_pdf, paths, tmp)
            use_feature(cb.from_user.id, "photo_pdf")
            await cb.message.answer_document(FSInputFile(out, filename="photos.pdf"),
                caption=f"📸 <b>PDF готов</b> — {len(files)} фото",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📸 Ещё", callback_data="cv:photo_pdf")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    except Exception as e: await cb.message.answer(f"❌ {e}")

# ---------- QR ----------
@router.callback_query(F.data == "qr")
async def qr_start(cb: CallbackQuery, state: FSMContext):
    ok, reason = check_feature_limit(cb.from_user.id, "qr")
    if not ok: await cb.answer(reason, show_alert=True); return
    await state.set_state(QRFlow.waiting_text)
    await cb.message.edit_text(
        "🔲 <b>QR-код</b>\n\nОтправьте текст или ссылку.\n\n/cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
    await cb.answer()

@router.message(QRFlow.waiting_text, F.text)
async def qr_make(msg: Message, state: FSMContext):
    await state.clear()
    text = msg.text.strip()
    if len(text) < 1: await msg.answer("❌ Пусто"); return
    if len(text) > 1000: await msg.answer("❌ Макс 1000"); return
    await msg.answer("⏳ Генерирую QR...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = await asyncio.to_thread(make_qr, text, tmp)
            use_feature(msg.from_user.id, "qr")
            await msg.answer_photo(FSInputFile(path, filename="qr.png"),
                caption=f"🔲 <b>QR готов</b>\n\n<code>{text[:100]}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔲 Ещё", callback_data="qr")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    except Exception as e: await msg.answer(f"❌ {e}")

# ---------- Убрать фон ----------
@router.callback_query(F.data == "remove_bg")
async def remove_bg_start(cb: CallbackQuery, state: FSMContext):
    ok, reason = check_feature_limit(cb.from_user.id, "remove_bg")
    if not ok: await cb.answer(reason, show_alert=True); return
    await state.set_state(RemoveBGFlow.waiting_photo)
    await cb.message.edit_text(
        "🎨 <b>Убрать фон</b>\n\nОтправьте фото — верну PNG с прозрачностью.\n\n"
        "⚠️ Первый раз ~1 мин.\n\n/cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
    await cb.answer()

@router.message(RemoveBGFlow.waiting_photo, F.photo)
async def remove_bg_process(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("⏳ Убираю фон...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = await bot.get_file(msg.photo[-1].file_id)
            local = os.path.join(tmp, "input.jpg")
            await bot.download_file(f.file_path, local)
            out = await asyncio.to_thread(remove_bg, local, tmp)
            use_feature(msg.from_user.id, "remove_bg")
            await msg.answer_document(FSInputFile(out, filename="no_bg.png"),
                caption="🎨 <b>Готово!</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎨 Ещё", callback_data="remove_bg")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    except Exception as e: await msg.answer(f"❌ {e}")

@router.message(RemoveBGFlow.waiting_photo)
async def remove_bg_wrong(msg: Message):
    await msg.answer("❌ Нужно <b>фото</b>.", parse_mode="HTML")

# ---------- Размер фото ----------
@router.callback_query(F.data == "resize_photo")
async def resize_start(cb: CallbackQuery, state: FSMContext):
    ok, reason = check_feature_limit(cb.from_user.id, "resize_photo")
    if not ok: await cb.answer(reason, show_alert=True); return
    await state.set_state(ResizeFlow.waiting_photo)
    await cb.message.edit_text("🎨 Отправьте фото.\n\n/cancel",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
    await cb.answer()

@router.message(ResizeFlow.waiting_photo, F.photo)
async def resize_get_photo(msg: Message, state: FSMContext):
    await state.update_data(file_id=msg.photo[-1].file_id)
    await state.set_state(ResizeFlow.waiting_size)
    await msg.answer(
        "📐 До какого размера уменьшить?\n\nВведите число или выберите:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="512 (аватар)", callback_data="rs:512")],
            [InlineKeyboardButton(text="1080 (сторис)", callback_data="rs:1080")],
            [InlineKeyboardButton(text="1920 (HD)", callback_data="rs:1920")],
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))

@router.callback_query(F.data.startswith("rs:"))
async def resize_process(cb: CallbackQuery, state: FSMContext):
    size = int(cb.data.split(":")[1])
    data = await state.get_data()
    file_id = data.get("file_id")
    await state.clear()
    if not file_id: await cb.answer("Ошибка", show_alert=True); return
    await cb.message.edit_text(f"⏳ Уменьшаю до {size}px...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = await bot.get_file(file_id)
            local = os.path.join(tmp, "input.jpg")
            await bot.download_file(f.file_path, local)
            out = await asyncio.to_thread(resize_photo, local, tmp, size)
            use_feature(cb.from_user.id, "resize_photo")
            await cb.message.answer_document(
                FSInputFile(out, filename=f"resized_{size}.jpg"),
                caption=f"🎨 <b>Готово!</b> До {size}px",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎨 Ещё", callback_data="resize_photo")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    except Exception as e: await cb.message.answer(f"❌ {e}")

@router.message(ResizeFlow.waiting_size, F.text)
async def resize_manual(cb_msg: Message, state: FSMContext):
    if not cb_msg.text.strip().isdigit():
        await cb_msg.answer("❌ Введите число"); return
    size = int(cb_msg.text.strip())
    if size < 50 or size > 4000:
        await cb_msg.answer("❌ От 50 до 4000"); return
    data = await state.get_data()
    file_id = data.get("file_id")
    await state.clear()
    if not file_id: await cb_msg.answer("Ошибка"); return
    await cb_msg.answer(f"⏳ Уменьшаю до {size}px...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = await bot.get_file(file_id)
            local = os.path.join(tmp, "input.jpg")
            await bot.download_file(f.file_path, local)
            out = await asyncio.to_thread(resize_photo, local, tmp, size)
            use_feature(cb_msg.from_user.id, "resize_photo")
            await cb_msg.answer_document(
                FSInputFile(out, filename=f"resized_{size}.jpg"),
                caption="🎨 <b>Готово!</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎨 Ещё", callback_data="resize_photo")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    except Exception as e: await cb_msg.answer(f"❌ {e}")

# ---------- Суммаризация ----------
@router.callback_query(F.data == "summarize")
async def summarize_start(cb: CallbackQuery, state: FSMContext):
    ok, reason = check_feature_limit(cb.from_user.id, "summarize")
    if not ok: await cb.answer(reason, show_alert=True); return
    await state.set_state(SummarizeFlow.waiting_text)
    await cb.message.edit_text(
        "📝 <b>Суммаризация (AI)</b>\n\nОтправьте текст (100+ символов).\n\n"
        "⚠️ Доступно Premium.\n\n/cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="converter")]]))
    await cb.answer()

@router.message(SummarizeFlow.waiting_text, F.text)
async def summarize_process(msg: Message, state: FSMContext):
    await state.clear()
    text = msg.text.strip()
    if len(text) < 100: await msg.answer("❌ Минимум 100 символов"); return
    await msg.answer("🤖 Анализирую...")
    try:
        result = await summarize_text(text)
        use_feature(msg.from_user.id, "summarize")
        chunks = [result[i:i+4000] for i in range(0, len(result), 4000)]
        for i, chunk in enumerate(chunks):
            await msg.answer(
                f"📝 <b>Краткое содержание:</b>\n\n{chunk}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Ещё", callback_data="summarize")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]
                ) if i == len(chunks) - 1 else None)
    except Exception as e: await msg.answer(f"❌ {e}")

# ---------- TTS ----------
@router.callback_query(F.data == "tts")
async def tts_start(cb: CallbackQuery, state: FSMContext):
    ok, reason = check_feature_limit(cb.from_user.id, "tts")
    if not ok: await cb.answer(reason, show_alert=True); return
    await state.set_state(TTSFlow.waiting_text)
    await cb.message.edit_text("🔊 Отправьте текст до 3000 символов. /cancel",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu")]]))
    await cb.answer()

@router.message(TTSFlow.waiting_text, F.text)
async def tts_process(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🎙 Озвучиваю...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            p = await text_to_speech(msg.text, tmp)
            use_feature(msg.from_user.id, "tts")
            await msg.answer_voice(FSInputFile(p))
    except Exception as e: await msg.answer(f"❌ {e}")

# ---------- Текст / ссылка ----------
@router.message(F.text)
async def on_text(msg: Message, state: FSMContext):
    if await state.get_state(): return
    text = msg.text.strip()
    urls = URL_RE.findall(text)
    if not urls:
        if len(text) < 2: await msg.answer("Коротко"); return
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(text); path = f.name
        await msg.answer_document(FSInputFile(path, filename="text.txt"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
        os.unlink(path)
        return
    url = urls[0]
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        title = (info.get("title") or "видео")[:60]
        dur = info.get("duration") or 0
        minutes = f"{dur // 60}:{dur % 60:02d}" if dur else "?"
    except Exception as e:
        await msg.answer(f"❌ {e}"); return
    ok, reason = can_download(msg.from_user.id, "360")
    if not ok:
        await msg.answer(reason, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Premium", callback_data="buy")]]))
        return
    prem = is_premium(msg.from_user.id)
    await msg.answer(f"🎬 <b>{title}</b>\n⏱ {minutes}\n\nКачество:",
                     reply_markup=quality_kb(prem, url), parse_mode="HTML")

@router.callback_query(F.data == "locked")
async def locked(cb: CallbackQuery):
    await cb.answer("🔒 Premium", show_alert=True)

@router.callback_query(F.data.startswith("q:"))
async def on_quality(cb: CallbackQuery):
    _, q, short_url = cb.data.split(":", 2)
    ok, reason = can_download(cb.from_user.id, q)
    if not ok: await cb.answer(reason, show_alert=True); return
    await cb.message.edit_text("⏳ Скачиваю...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = await asyncio.to_thread(smart_download, short_url, q, tmp)
            if os.path.getsize(path) > 50 * 1024 * 1024:
                await cb.message.edit_text("❌ > 50 МБ"); return
            inc_usage(cb.from_user.id)
            await cb.message.answer_document(FSInputFile(path),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
            try: await cb.message.delete()
            except Exception: pass
    except Exception as e:
        await cb.message.edit_text(f"❌ {e}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))

# ---------- Напоминание ----------
async def premium_reminder():
    while True:
        try:
            today = date.today()
            with _con() as con:
                rows = con.execute("SELECT user_id, premium_until, notify_sent "
                                   "FROM users WHERE is_premium=1").fetchall()
            for r in rows:
                if not r["premium_until"]: continue
                until = date.fromisoformat(r["premium_until"])
                d = (until - today).days
                if d in (3, 1, 0):
                    key = f"{d}_{r['premium_until']}"
                    if r["notify_sent"] == key: continue
                    txt = {3: "⏳ Premium через 3 дня", 1: "⚠️ Завтра закончится",
                           0: "❌ Premium закончился"}[d]
                    try:
                        await bot.send_message(r["user_id"], f"{txt}\n\nПродлить?",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🔄 Продлить", callback_data="buy")]]))
                        with _con() as con:
                            con.execute("UPDATE users SET notify_sent=? WHERE user_id=?",
                                        (key, r["user_id"]))
                            con.commit()
                    except Exception: pass
        except Exception as e: print(f"[reminder] {e}")
        await asyncio.sleep(3600)

# ---------- Запуск ----------
async def main():
    init_db()
    dp = Dispatcher()
    dp.include_router(router)
    mw = SubscriptionMiddleware()
    dp.message.middleware(mw)
    dp.callback_query.middleware(mw)
    asyncio.create_task(premium_reminder())
    print("Kthronix v7.0 запущен (без зеркал)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
