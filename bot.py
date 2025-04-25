# -*- coding: utf-8 -*-
import os
import sqlite3
import time
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.helpers import escape_markdown

# ————— CONFIGURATION —————
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("La variable d'environnement BOT_TOKEN n'est pas définie")
SUPER_ADMIN_ID = 5295071762

DATA_DIR = "data"
DB_FILE = "main.db"

# Durées et longueurs
ADMIN_EXPIRY_DAYS    = 30    # durée de validité d'un accès admin
MIN_SEARCH_CHARS     = 3     # nb min de caractères pour /search
MAX_CAPTION_LENGTH   = 50    # nb max de caractères pour la légende

# Extensions autorisées
ALLOWED_EXT = (
    '.avi','.mkv','.mp4','.mov','.flv','.wmv',
    '.exe','.zip','.rar','.7z','.iso'
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# — Helpers de validation & sécurité —
def clean_text(s: str) -> str:
    return re.sub(r'[^0-9A-Za-z \|]+', '', s).strip()

def validate_caption(c: str) -> bool:
    # désormais uniquement la longueur ≤ MAX_CAPTION_LENGTH et non vide
    return 0 < len(c) <= MAX_CAPTION_LENGTH

def sanitize_query(q: str) -> str:
    return re.sub(r'[^0-9A-Za-z ]+', ' ', q).strip().lower()

async def ensure_in_channel(user_id: int, bot, channel: str) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return m.status in ('member','administrator','creator')
    except:
        return False

def safe_handler(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except Exception:
            logger.exception("Erreur dans %s", func.__name__)
            await update.effective_message.reply_text(
                "⚠️ Une erreur est survenue, veuillez réessayer plus tard."
            )
    return wrapper

# — Base principale & par admin —
os.makedirs(DATA_DIR, exist_ok=True)
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cur = conn.cursor()
cur.executescript("""
CREATE TABLE IF NOT EXISTS admins(
    user_id INTEGER PRIMARY KEY,
    added_at TEXT,
    expires_at TEXT,
    channel_link TEXT,
    active INTEGER DEFAULT 0,
    is_superadmin INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_requests(
    user_id INTEGER PRIMARY KEY,
    requested_at TEXT
);
CREATE TABLE IF NOT EXISTS user_access(
    user_id INTEGER,
    admin_id INTEGER,
    PRIMARY KEY(user_id, admin_id)
);
""")
conn.commit()

now = datetime.now(timezone.utc).isoformat()
cur.execute(
    "INSERT OR IGNORE INTO admins(user_id,added_at,expires_at,active,is_superadmin) VALUES(?,?,?,?,1)",
    (SUPER_ADMIN_ID, now, (datetime.now(timezone.utc) + timedelta(days=ADMIN_EXPIRY_DAYS*12)).isoformat(), 1)
)
conn.commit()

def get_admin_db(aid: int):
    path = os.path.join(DATA_DIR, f"{aid}.db")
    init = not os.path.exists(path)
    db = sqlite3.connect(path, check_same_thread=False)
    if init:
        db.executescript("""
        CREATE TABLE media(
            rowid       INTEGER PRIMARY KEY,
            file_id     TEXT UNIQUE,
            description TEXT,
            saison      TEXT,
            added_at    TEXT
        );
        CREATE VIRTUAL TABLE media_fts USING fts5(
            description, saison,
            content='media', content_rowid='rowid',
            tokenize="unicode61 remove_diacritics 2"
        );
        """)
        db.commit()
    return db

# — Décorateurs rôles —
def superadmin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != SUPER_ADMIN_ID:
            await update.effective_message.reply_text("❌ Vous n'êtes pas le Super-Admin.")
            return
        return await func(update, context)
    return wrapper

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        row = cur.execute(
            "SELECT expires_at, active FROM admins WHERE user_id=?", (uid,)
        ).fetchone()
        if not row:
            await update.effective_message.reply_text("❌ Vous n'êtes pas administrateur.")
            return
        expires_at, active = row
        exp_dt = datetime.fromisoformat(expires_at).replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp_dt:
            cur.execute("UPDATE admins SET active=0 WHERE user_id=?", (uid,))
            conn.commit()
            await update.effective_message.reply_text("❌ Votre accès admin a expiré.")
            return
        if not active:
            await update.effective_message.reply_text(
                "❌ Votre accès admin est désactivé. /setchannel <@canal>"
            )
            return
        return await func(update, context)
    return wrapper

# — Handlers Public —
@safe_handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0].startswith('access_'):
        aid = int(args[0].split('_',1)[1])
        cur.execute(
            "INSERT OR IGNORE INTO user_access(user_id,admin_id) VALUES(?,?)",
            (update.effective_user.id, aid)
        )
        conn.commit()
        await update.effective_message.reply_text(f"✅ Accès admin {aid} activé !")
        return

    user = update.effective_user
    row = cur.execute(
        "SELECT active FROM admins WHERE user_id=?", (user.id,)
    ).fetchone()
    is_admin = bool(row and row[0])
    is_super = (user.id == SUPER_ADMIN_ID)

    lines = [
        f"👋 Bienvenue, {user.first_name}! sur la plus grande base de donnees de telegram ! Vous êtes *"
        + ("Super-Admin" if is_super else "Admin" if is_admin else "Utilisateur")
        + "*.",
        "🔹 Public :",
        f"• /search <mot> — (min {MIN_SEARCH_CHARS})",
        "• /devenir_admin —  Demander rôle admin: devenire administrateur te permet de stocker tes donnees dans le bot pour contourner les restrictions sur les droit d'auteur et eviter la fermeture de ton canal de plus tu peux restrindre l'acces de tons contenue uniquemet a tes abonneès et ainsi assure la croissance du canal fichiers pries en charge : MP4; AVI; MKV; MOV; FLV; WMV; EXE; ZIP; RAR; 7z; ISO",
        "• /whoami — voir rôle",
        "• /help — aide"
    ]
    if is_admin:
        lines += [
            "🔹 Admin :",
            f"• Envoyez fichier avec caption ≤{MAX_CAPTION_LENGTH} car.",
            "• /setchannel <@canal>",
            "• /mon_canal — voir canal",
            "• /ma_base — nb médias",
            "• /renewadmin — renouveler accès"
        ]
    if is_super:
        lines += [
            "🔹 Super-Admin :",
            "• /list_requests",
            "• /accepter_admin <id>",
            "• /refuser_admin <id>",
            "• /listadmins",
            "• /addadmin <id>",
            "• /revokeadmin <id>",
            "• /renewadmin <id>"
        ]

    text = escape_markdown("\n".join(lines), version=2)
    await update.effective_message.reply_text(text, parse_mode='MarkdownV2')

@safe_handler
async def help_command(update, context):
    await start(update, context)

@safe_handler
async def whoami(update, context):
    uid = update.effective_user.id
    if uid == SUPER_ADMIN_ID:
        role = 'Super-Admin'
    else:
        row = cur.execute(
            "SELECT active FROM admins WHERE user_id=?", (uid,)
        ).fetchone()
        role = 'Admin' if (row and row[0]) else 'Utilisateur'
    await update.effective_message.reply_text(f"Vous êtes : {role} (ID: {uid})")

@safe_handler
async def devenir_admin(update, context):
    uid = update.effective_user.id
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT OR IGNORE INTO admin_requests(user_id,requested_at) VALUES(?,?)",
        (uid, now_iso)
    )
    conn.commit()
    await update.effective_message.reply_text(
        "✅ Votre demande a été envoyée au Super Administrateur l'accés aux droits administrateur n'est pas gratuit mais vous pouvez demander une periode d'essai de 7 jours prix de l'abonnement 1500f contacte @LELOUCH0X "
    )
    await context.bot.send_message(
        SUPER_ADMIN_ID,
        f"Nouvelle demande d'admin de {uid}"
    )

@safe_handler
async def search(update, context):
    uid = update.effective_user.id
    raw = ' '.join(context.args)
    clean = sanitize_query(raw)
    if len(clean) < MIN_SEARCH_CHARS:
        await update.effective_message.reply_text(
            f"🔍 {MIN_SEARCH_CHARS}+ caractères requis."
        )
        return

    rows = cur.execute(
        "SELECT admin_id FROM user_access WHERE user_id=?", (uid,)
    ).fetchall()
    if not rows:
        await update.effective_message.reply_text("❌ Aucun accès.")
        return

    found = False
    for (aid,) in rows:
        ch = cur.execute(
            "SELECT channel_link FROM admins WHERE user_id=?", (aid,)
        ).fetchone()[0]
        if ch and not await ensure_in_channel(uid, context.bot, ch):
            await update.effective_message.reply_text(
                f"👥 Rejoignez d’abord @{ch}."
            )
            continue

        db = get_admin_db(aid)
        try:
            cur2 = db.execute(
                "SELECT m.file_id,m.description,m.saison "
                "FROM media m JOIN media_fts ON m.rowid=media_fts.rowid "
                "WHERE media_fts MATCH ?",
                (f"{clean}*",)
            )
        except sqlite3.OperationalError:
            pattern = f"%{clean.replace(' ','%')}%"
            cur2 = db.execute(
                "SELECT file_id,description,saison FROM media "
                "WHERE description LIKE ?",
                (pattern,)
            )

        for fid, desc, s in cur2:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=fid,
                caption=f"{desc}{f' (Saison {s})' if s else ''}"
            )
            found = True

        db.close()

    if not found:
        await update.effective_message.reply_text("🔍 Rien trouvé.")

# — Handlers Admin —
@admin_only
@safe_handler
async def setchannel(update, context):
    link = context.args[0].replace('https://t.me/','') if context.args else None
    cur.execute(
        "UPDATE admins SET channel_link=?,active=1 WHERE user_id=?",
        (link, update.effective_user.id)
    )
    conn.commit()
    await update.effective_message.reply_text(f"✅ Canal @{link} défini.")

@admin_only
@safe_handler
async def mon_canal(update, context):
    row = cur.execute(
        "SELECT channel_link FROM admins WHERE user_id=?", (update.effective_user.id,)
    ).fetchone()
    await update.effective_message.reply_text(
        f"Canal : @{row[0]}" if row and row[0] else "Aucun canal défini."
    )

@admin_only
@safe_handler
async def ma_base(update, context):
    db = get_admin_db(update.effective_user.id)
    count = db.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    await update.effective_message.reply_text(f"📂 {count} médias enregistrés.")

@admin_only
@safe_handler
async def handle_video(update, context):
    file = update.message.video
    desc = clean_text(update.message.caption or '')
    if not file or not validate_caption(desc):
        await update.effective_message.reply_text(
            f"❌ Caption invalide ou trop longue (max {MAX_CAPTION_LENGTH})."
        )
        return
    fid = file.file_id
    db = get_admin_db(update.effective_user.id)
    if db.execute("SELECT 1 FROM media WHERE file_id=?", (fid,)).fetchone():
        await update.effective_message.reply_text("❌ Vidéo déjà ajoutée.")
        return
    t, s = (desc.split('|',1)+[''])[:2]
    db.execute(
        "INSERT INTO media(file_id,description,saison,added_at) VALUES(?,?,?,?)",
        (fid, t.strip(), s.strip(), datetime.now(timezone.utc).isoformat())
    )
    db.execute(
        "INSERT INTO media_fts(rowid,description,saison) "
        "VALUES((SELECT rowid FROM media ORDER BY rowid DESC LIMIT 1),?,?)",
        (t.strip(), s.strip())
    )
    db.commit()
    await update.effective_message.reply_text("✅ Vidéo ajoutée.")

@admin_only
@safe_handler
async def handle_document_video(update, context):
    doc = update.message.document
    fname = (doc.file_name or '').lower()
    if not fname.endswith(ALLOWED_EXT):
        await update.effective_message.reply_text(
            f"❌ Formats autorisés : {', '.join(ALLOWED_EXT)}"
        )
        return
    desc = clean_text(update.message.caption or '')
    if not validate_caption(desc):
        await update.effective_message.reply_text(
            f"❌ Caption invalide ou trop longue (max {MAX_CAPTION_LENGTH})."
        )
        return
    fid = doc.file_id
    db = get_admin_db(update.effective_user.id)
    if db.execute("SELECT 1 FROM media WHERE file_id=?", (fid,)).fetchone():
        await update.effective_message.reply_text("❌ Fichier déjà ajouté.")
        return
    t, s = (desc.split('|',1)+[''])[:2]
    db.execute(
        "INSERT INTO media(file_id,description,saison,added_at) VALUES(?,?,?,?)",
        (fid, t.strip(), s.strip(), datetime.now(timezone.utc).isoformat())
    )
    db.execute(
        "INSERT INTO media_fts(rowid,description,saison) "
        "VALUES((SELECT rowid FROM media ORDER BY rowid DESC LIMIT 1),?,?)",
        (t.strip(), s.strip())
    )
    db.commit()
    await update.effective_message.reply_text("✅ Fichier ajouté.")

# — Handlers Super-Admin —
@superadmin_only
@safe_handler
async def list_requests(update, context):
    rows = cur.execute("SELECT user_id,requested_at FROM admin_requests").fetchall()
    text = "\n".join(f"- {u} à {t}" for u,t in rows) or "Aucune demande"
    await update.effective_message.reply_text(text)

@superadmin_only
@safe_handler
async def accepter_admin(update, context):
    uid = int(context.args[0])
    cur.execute("DELETE FROM admin_requests WHERE user_id=?", (uid,))
    now_iso = datetime.now(timezone.utc).isoformat()
    exp_iso = (
        datetime.now(timezone.utc) + timedelta(days=ADMIN_EXPIRY_DAYS)
    ).isoformat()
    cur.execute(
        "INSERT OR REPLACE INTO admins(user_id,added_at,expires_at,active) VALUES(?,?,?,1)",
        (uid, now_iso, exp_iso)
    )
    conn.commit()
    await update.effective_message.reply_text(f"Admin {uid} accepté.")

@superadmin_only
@safe_handler
async def refuser_admin(update, context):
    uid = int(context.args[0])
    cur.execute("DELETE FROM admin_requests WHERE user_id=?", (uid,))
    conn.commit()
    await update.effective_message.reply_text(f"Demande {uid} refusée.")

@superadmin_only
@safe_handler
async def list_admins(update, context):
    rows = cur.execute(
        "SELECT user_id,expires_at,active FROM admins WHERE is_superadmin=0"
    ).fetchall()
    text = "\n".join(f"- {u}: exp {e}, act={a}" for u,e,a in rows) or "Aucun admin"
    await update.effective_message.reply_text(text)

@superadmin_only
@safe_handler
async def addadmin(update, context):
    uid = int(context.args[0])
    now_iso = datetime.now(timezone.utc).isoformat()
    exp_iso = (
        datetime.now(timezone.utc) + timedelta(days=ADMIN_EXPIRY_DAYS)
    ).isoformat()
    cur.execute(
        "INSERT OR REPLACE INTO admins(user_id,added_at,expires_at,active) VALUES(?,?,?,1)",
        (uid, now_iso, exp_iso)
    )
    conn.commit()
    await update.effective_message.reply_text(f"Admin {uid} ajouté.")

@superadmin_only
@safe_handler
async def revokeadmin(update, context):
    uid = int(context.args[0])
    cur.execute("UPDATE admins SET active=0 WHERE user_id=?", (uid,))
    conn.commit()
    await update.effective_message.reply_text(f"Admin {uid} révoqué.")

@superadmin_only
@safe_handler
async def renewadmin(update, context):
    uid = int(context.args[0])
    newexp = (
        datetime.now(timezone.utc) + timedelta(days=ADMIN_EXPIRY_DAYS)
    ).isoformat()
    cur.execute(
        "UPDATE admins SET expires_at=?,active=1 WHERE user_id=?",
        (newexp, uid)
    )
    conn.commit()
    await update.effective_message.reply_text(
        f"Admin {uid} renouvelé jusqu'au {newexp}."
    )

# — Main loop polling robuste —
def main():
    while True:
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            app = Application.builder().token(TOKEN).build()
            # Public
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("help", help_command))
            app.add_handler(CommandHandler("whoami", whoami))
            app.add_handler(CommandHandler("devenir_admin", devenir_admin))
            app.add_handler(CommandHandler("search", search))
            # Admin
            app.add_handler(CommandHandler("setchannel", setchannel))
            app.add_handler(CommandHandler("mon_canal", mon_canal))
            app.add_handler(CommandHandler("ma_base", ma_base))
            app.add_handler(MessageHandler(filters.Document.ALL, handle_document_video))
            app.add_handler(MessageHandler(filters.VIDEO, handle_video))
            app.add_handler(CommandHandler("renewadmin", renewadmin))
            # Super-Admin
            app.add_handler(CommandHandler("list_requests", list_requests))
            app.add_handler(CommandHandler("accepter_admin", accepter_admin))
            app.add_handler(CommandHandler("refuser_admin", refuser_admin))
            app.add_handler(CommandHandler("listadmins", list_admins))
            app.add_handler(CommandHandler("addadmin", addadmin))
            app.add_handler(CommandHandler("revokeadmin", revokeadmin))
            app.add_handler(CommandHandler("renewadmin", renewadmin))

            logger.info("🤖 Bot démarré (polling)…")
            app.run_polling()
        except Exception:
            logger.exception("❌ crash détecté, redémarrage dans 5s…")
            time.sleep(5)

if __name__ == '__main__':
    main()
