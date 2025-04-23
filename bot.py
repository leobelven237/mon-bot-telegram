# -*- coding: utf-8 -*-
import os
import sqlite3
import time
import logging
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.helpers import escape_markdown

# ---------------- CONFIGURATION ----------------
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("La variable d'environnement BOT_TOKEN n'est pas définie")
SUPER_ADMIN_ID = 5295071762
DATA_DIR = "data"
DB_FILE = "main.db"
EXPIRY_DAYS = 30
MIN_SEARCH_LENGTH = 3
ALLOWED_EXT = ('.avi', '.mkv', '.mp4', '.mov', '.flv', '.wmv', '.exe', '.zip', '.rar', '.7z', '.iso')

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Init DB
os.makedirs(DATA_DIR, exist_ok=True)
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.executescript("""
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    added_at TEXT,
    expires_at TEXT,
    channel_link TEXT,
    active INTEGER DEFAULT 0,
    is_superadmin INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_requests (
    user_id INTEGER PRIMARY KEY,
    requested_at TEXT
);
CREATE TABLE IF NOT EXISTS user_access (
    user_id INTEGER,
    admin_id INTEGER,
    PRIMARY KEY(user_id, admin_id)
);
""")
conn.commit()
# Ensure super-admin
now = datetime.utcnow().isoformat()
cursor.execute(
    "INSERT OR IGNORE INTO admins(user_id,added_at,expires_at,active,is_superadmin) VALUES(?,?,?,?,1)",
    (SUPER_ADMIN_ID, now, (datetime.utcnow()+timedelta(days=EXPIRY_DAYS*12)).isoformat(), 1)
)
conn.commit()

# Decorators

def superadmin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != SUPER_ADMIN_ID:
            await update.message.reply_text("❌ Vous n'êtes pas le Super-Admin.")
            return
        return await func(update, context)
    return wrapper

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        row = cursor.execute("SELECT expires_at,active FROM admins WHERE user_id=?", (uid,)).fetchone()
        if not row:
            await update.message.reply_text("❌ Vous n'êtes pas administrateur.")
            return
        expires, active = row
        if datetime.utcnow() > datetime.fromisoformat(expires):
            cursor.execute("UPDATE admins SET active=0 WHERE user_id=?", (uid,)); conn.commit()
            await update.message.reply_text("❌ Votre accès admin a expiré.")
            return
        if not active:
            await update.message.reply_text("❌ Votre accès admin est désactivé. /setchannel <@canal>")
            return
        return await func(update, context)
    return wrapper

# Admin DB utility
def get_admin_db(admin_id:int):
    path=os.path.join(DATA_DIR,f"{admin_id}.db")
    init=not os.path.exists(path)
    db=sqlite3.connect(path,check_same_thread=False)
    if init:
        db.executescript("""
        CREATE TABLE media(rowid INTEGER PRIMARY KEY, file_id TEXT UNIQUE, description TEXT, saison TEXT, added_at TEXT);
        CREATE VIRTUAL TABLE media_fts USING fts5(description, saison, content='media', content_rowid='rowid');
        """)
        db.commit()
    return db

# Handlers Public
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args=context.args
    if args and args[0].startswith('access_'):
        aid=int(args[0].split('_',1)[1])
        cursor.execute("INSERT OR IGNORE INTO user_access(user_id,admin_id) VALUES(?,?)",(update.effective_user.id,aid));conn.commit()
        await update.message.reply_text(f"✅ Accès admin {aid} activé !")
        return
    user=update.effective_user; is_super=user.id==SUPER_ADMIN_ID
    row=cursor.execute("SELECT active FROM admins WHERE user_id=?",(user.id,)).fetchone()
    is_admin=bool(row and row[0])
    lines=[f"👋 Bienvenue {user.first_name} sur la plus grande base de donnees de telegram ! Vous êtes *{'Super-Admin' if is_super else 'Admin' if is_admin else 'Utilisateur'}*.",
           "🔹 Public:",f"• /search <mot> (min {MIN_SEARCH_LENGTH})","• /devenir_admin Demander rôle admin devenire administrateur te permet de stocker tes donnees dans le bot pour contourner les restrictions sur les droit d'auteur et eviter la fermeture de plus tu peux restrindre l'acces de tons contenue uniquemet a tes abonneès et ainsi assure la croissance du canal fichiers pries en charge : MP4; AVI; MKV; MOV; FLV; WMV; EXE; ZIP; RAR; 7z","• /whoami","• /help"]
    if is_admin: lines += ["🔹 Admin:","Envoyer fichier 'Titre|Saison'","/setchannel <@canal>","/mon_canal","/ma_base","/renewadmin"]
    if is_super: lines += ["🔹 Super-Admin:","/list_requests","/accepter_admin <id>","/refuser_admin <id>","/listadmins","/addadmin <id>","/revokeadmin <id>","/renewadmin <id>"]
    text=escape_markdown("\n".join(lines),version=2)
    await update.message.reply_text(text,parse_mode='MarkdownV2')

async def help_command(update,context): await start(update,context)

async def whoami(update,context):
    uid=update.effective_user.id
    if uid==SUPER_ADMIN_ID: role='Super-Admin'
    else:
        row=cursor.execute("SELECT active FROM admins WHERE user_id=?",(uid,)).fetchone()
        role='Admin' if row and row[0] else 'Utilisateur'
    await update.message.reply_text(f"Vous êtes : {role} (ID {uid})")

async def devenir_admin(update,context):
    uid=update.effective_user.id; now=datetime.utcnow().isoformat()
    cursor.execute("INSERT OR IGNORE INTO admin_requests(user_id,requested_at) VALUES(?,?)",(uid,now));conn.commit()
    await update.message.reply_text("✅ Demande envoyée au Super-Admin Votre demande a été envoyée au Super Administrateur l'accés aux droits administrateur n'est pas gratuit mais vous pouvez demander une periode d'essai de 7 jours prix de l'abonnement 1500f contacte @LELOUCH0X .")
    await context.bot.send_message(SUPER_ADMIN_ID,f"Demande admin de {uid}")

async def search(update,context):
    uid=update.effective_user.id; q=' '.join(context.args).strip().lower()
    if len(q)<MIN_SEARCH_LENGTH: return await update.message.reply_text(f"🔍 {MIN_SEARCH_LENGTH}+ caractères requis.")
    rows=cursor.execute("SELECT admin_id FROM user_access WHERE user_id=?",(uid,)).fetchall()
    if not rows: return await update.message.reply_text("❌ Aucun accès.")
    found=False
    for (aid,) in rows:
        ch=cursor.execute("SELECT channel_link FROM admins WHERE user_id=?",(aid,)).fetchone()[0]
        if ch:
            try:
                mem=await context.bot.get_chat_member(chat_id=ch,user_id=uid)
                if mem.status not in('member','administrator','creator'): await update.message.reply_text(f"👥 Rejoignez @{ch}"); continue
            except: pass
        db=get_admin_db(aid)
        for fid,desc,s in db.execute("SELECT m.file_id,m.description,m.saison FROM media m JOIN media_fts ON m.rowid=media_fts.rowid WHERE media_fts MATCH ?",(f"{q}*",)):
            await context.bot.send_document(update.effective_chat.id,fid,caption=f"{desc}{f' (S{s})' if s else ''}"); found=True
        db.close()
    if not found: await update.message.reply_text("🔍 Rien trouvé.")

# Handlers Admin
@admin_only
async def setchannel(update,context):
    link=context.args[0].replace('https://t.me/','') if context.args else None
    cursor.execute("UPDATE admins SET channel_link=?,active=1 WHERE user_id=?",(link,update.effective_user.id));conn.commit()
    await update.message.reply_text(f"✅ Canal @{link} défini.")

@admin_only
async def mon_canal(update,context):
    row=cursor.execute("SELECT channel_link FROM admins WHERE user_id=?",(update.effective_user.id,)).fetchone()
    await update.message.reply_text(f"Canal : @{row[0]}" if row and row[0] else "Aucun canal défini.")

@admin_only
async def ma_base(update,context):
    db=get_admin_db(update.effective_user.id)
    cnt=db.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    await update.message.reply_text(f"📂 {cnt} médias enregistrés.")

@admin_only
async def handle_video(update,context):
    file=update.message.video
    desc=update.message.caption or ''
    if not file or not desc.strip(): return await update.message.reply_text("❌ Envoyez vidéo avec description 'Titre|Saison'.")
    fid=file.file_id; db=get_admin_db(update.effective_user.id)
    if db.execute("SELECT 1 FROM media WHERE file_id=?",(fid,)).fetchone(): return await update.message.reply_text("❌ Vidéo déjà ajoutée.")
    t,s=(desc.split('|',1)+[''])[:2]
    db.execute("INSERT INTO media(file_id,description,saison,added_at) VALUES(?,?,?,?)",(fid,t.strip(),s.strip(),datetime.utcnow().isoformat()))
    db.execute("INSERT INTO media_fts(rowid,description,saison) VALUES((SELECT rowid FROM media ORDER BY rowid DESC LIMIT 1),?,?)",(t.strip(),s.strip())); db.commit()
    await update.message.reply_text("✅ Vidéo ajoutée.")

@admin_only
async def handle_document_video(update,context):
    doc=update.message.document; fname=doc.file_name or ''
    if not fname.lower().endswith(ALLOWED_EXT): return await update.message.reply_text(f"❌ Formats autorisés : {', '.join(ALLOWED_EXT)}")
    desc=update.message.caption or ''
    if not desc.strip(): return await update.message.reply_text("❌ Ajoutez une description 'Titre|Saison'.")
    fid=doc.file_id; db=get_admin_db(update.effective_user.id)
    if db.execute("SELECT 1 FROM media WHERE file_id=?",(fid,)).fetchone(): return await update.message.reply_text("❌ Fichier déjà ajouté.")
    t,s=(desc.split('|',1)+[''])[:2]
    db.execute("INSERT INTO media(file_id,description,saison,added_at) VALUES(?,?,?,?)",(fid,t.strip(),s.strip(),datetime.utcnow().isoformat()))
    db.execute("INSERT INTO media_fts(rowid,description,saison) VALUES((SELECT rowid FROM media ORDER BY rowid DESC LIMIT 1),?,?)",(t.strip(),s.strip())); db.commit()
    await update.message.reply_text("✅ Fichier ajouté.")

# Handlers Super-Admin
@superadmin_only
async def list_requests(update,context): rows=cursor.execute("SELECT user_id,requested_at FROM admin_requests").fetchall(); await update.message.reply_text("\n".join(f"- {u} à {t}" for u,t in rows) or "Aucune demande")

@superadmin_only
async def accepter_admin(update,context):
    uid=int(context.args[0]); cursor.execute("DELETE FROM admin_requests WHERE user_id=?",(uid,)); now=datetime.utcnow().isoformat(); exp=(datetime.utcnow()+timedelta(days=EXPIRY_DAYS)).isoformat()
    cursor.execute("INSERT OR REPLACE INTO admins(user_id,added_at,expires_at,active) VALUES(?,?,?,1)",(uid,now,exp)); conn.commit(); await update.message.reply_text(f"Admin {uid} accepté.")

@superadmin_only
async def refuser_admin(update,context): uid=int(context.args[0]); cursor.execute("DELETE FROM admin_requests WHERE user_id=?",(uid,)); conn.commit(); await update.message.reply_text(f"Demande {uid} refusée.")

@superadmin_only
async def list_admins(update,context): rows=cursor.execute("SELECT user_id,expires_at,active FROM admins WHERE is_superadmin=0").fetchall(); await update.message.reply_text("\n".join(f"- {u}: exp {e}, act={a}" for u,e,a in rows) or "Aucun admin")

@superadmin_only
async def addadmin(update,context): uid=int(context.args[0]); now=datetime.utcnow().isoformat(); exp=(datetime.utcnow()+timedelta(days=EXPIRY_DAYS)).isoformat(); cursor.execute("INSERT OR REPLACE INTO admins(user_id,added_at,expires_at,active) VALUES(?,?,?,1)",(uid,now,exp)); conn.commit(); await update.message.reply_text(f"Admin {uid} ajouté.")

@superadmin_only
async def revokeadmin(update,context): uid=int(context.args[0]); cursor.execute("UPDATE admins SET active=0 WHERE user_id=?",(uid,)); conn.commit(); await update.message.reply_text(f"Admin {uid} révoqué.")

@superadmin_only
async def renewadmin(update,context): uid=int(context.args[0]); newexp=(datetime.utcnow()+timedelta(days=EXPIRY_DAYS)).isoformat(); cursor.execute("UPDATE admins SET expires_at=?,active=1 WHERE user_id=?",(newexp,uid)); conn.commit(); await update.message.reply_text(f"Admin {uid} renouvelé jusqu'au {newexp}.")

# Main loop

def main():
    app = Application.builder().token(TOKEN).build()

    # Public handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("devenir_admin", devenir_admin))
    app.add_handler(CommandHandler("search", search))

    # Admin handlers
    app.add_handler(CommandHandler("setchannel", setchannel))
    app.add_handler(CommandHandler("mon_canal", mon_canal))
    app.add_handler(CommandHandler("ma_base", ma_base))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_video))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))

    # Super-Admin handlers
    app.add_handler(CommandHandler("list_requests", list_requests))
    app.add_handler(CommandHandler("accepter_admin", accepter_admin))
    app.add_handler(CommandHandler("refuser_admin", refuser_admin))
    app.add_handler(CommandHandler("listadmins", list_admins))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("revokeadmin", revokeadmin))
    app.add_handler(CommandHandler("renewadmin", renewadmin))

    logger.info("🤖 Bot démarré (polling)...")
    while True:
        try:
            app.run_polling()
        except Exception:
            logger.exception("❌ Plantage détecté, redémarrage dans 5s...")
            time.sleep(5)

if __name__ == '__main__':
    main()
