import logging
import sqlite3
from urllib.parse import quote_plus
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from telegram.error import BadRequest

# ---------------------------- CONFIGURATION ----------------------------
TOKEN = "8056782510:AAE3LXIKiAHBevVt6jHGpzrXOGgErfVfpOE"  # Token du bot
CHANNEL_ID = "@NETFLIXSERIE2"  # Nom du canal (avec @)
CHANNEL_LINK = CHANNEL_ID.replace('@', '')  # Lien correct sans '@'
REQUIRED_REFERRALS = 10       # Nombre d'invitations nécessaires
PHOTO_ID = "AgACAgQAAxkBAAM3Z_q4jHpOferv__bAl7GUDkLUXG4AAk7HMRtg1NhTp7sdBvO5nHEBAAMCAAN5AAM2BA"  # ID de l'image d'accueil
# -------------------------------------------------------------------------

# Initialisation de la BDD SQLite (mode synchrone pour simplifier)
conn = sqlite3.connect('users.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                (user_id INTEGER PRIMARY KEY, referrals INTEGER DEFAULT 0, has_joined BOOLEAN DEFAULT FALSE)''')
conn.commit()

# Configuration des logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

def get_main_menu_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    """
    Renvoie le clavier principal avec :
      - Bouton pour vérifier l'adhésion (callback)
      - Bouton pour consulter les statistiques (callback)
      - Bouton pour partager le lien qui ouvre l'interface de partage
    """
    # Encode le lien et le texte pour le partage
    encoded_url = quote_plus(referral_link)
    share_text = quote_plus("Voici mon lien de parrainage !")
    share_url = f"https://t.me/share/url?url={encoded_url}&text={share_text}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Vérifier mon adhésion", callback_data="check_joined")],
        [InlineKeyboardButton("📊 Statistiques", callback_data="stats")],
        [InlineKeyboardButton("📤 Partager le lien", url=share_url)]
    ])

def get_back_keyboard() -> InlineKeyboardMarkup:
    """Retourne un clavier avec un bouton 'Retour au menu'."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Retour au menu", callback_data="back_to_menu")]
    ])

async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Vérifie si l'utilisateur a rejoint le canal."""
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'owner', 'creator']
    except Exception as e:
        logger.error(f"Erreur de vérification : {e}")
        return False

async def check_rewards(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Vérifie si l'utilisateur remplit les conditions pour la récompense."""
    cursor.execute("SELECT referrals, has_joined FROM users WHERE user_id = ?", (user_id,))
    data = cursor.fetchone()
    if data and data[0] >= REQUIRED_REFERRALS and data[1]:
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 Félicitations ! Accès VIP activé.\n"
                 "🔑 Identifiants : user_12345 | pass_12345\n\n"
                 "⚠️ Usage strictement personnel."
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Commande /start :
      - Enregistre l'utilisateur et gère le parrainage s'il existe.
      - Construit le lien de parrainage sous la forme https://t.me/<bot_username>?start=ref_<user_id>
      - Envoie l'image d'accueil accompagnée d'un menu principal
    """
    user = update.effective_user
    referral_code = f"ref_{user.id}"
    referral_link = f"https://t.me/{context.bot.username}?start={referral_code}"
    
    # Enregistrement de l'utilisateur (INSERT OR IGNORE)
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user.id,))
    conn.commit()
    
    # Gestion du parrainage
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0].split("_")[1])
            if referrer_id != user.id:
                cursor.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id = ?", (referrer_id,))
                conn.commit()
                await check_rewards(referrer_id, context)
        except Exception as e:
            logger.error(f"Erreur lors du traitement du parrainage : {e}")
    
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=PHOTO_ID,
        caption=f"📺 *Bienvenue {user.first_name} !* 📺\n\n"
                "Obtenez un accès VIP à +5000 chaînes en HD/4K 🌍\n\n"
                f"🎁 *Conditions* :\n"
                f"1️⃣ Rejoignez notre chaîne ➜ [Lien du canal](https://t.me/{CHANNEL_LINK})\n"
                f"2️⃣ Parrainez *{REQUIRED_REFERRALS} amis* avec votre lien\n\n"
                f"🔗 *Votre lien* : `t.me/{context.bot.username}?start={referral_code}`\n\n"
                "⚠️ Respectez les lois de votre pays.",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(referral_link)
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche les statistiques de parrainage avec un bouton de retour."""
    user = update.effective_user
    cursor.execute("SELECT referrals FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    referrals = row[0] if row else 0
    stats_text = (
        f"📊 *Statistiques*\n\n"
        f"➤ Invitations validées : {referrals}/{REQUIRED_REFERRALS}\n"
        f"➤ Progression : {'🟩' * (referrals // 5)}{'⬜️' * (5 - (referrals // 5))}"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=stats_text,
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche un message d'aide avec un bouton de retour."""
    help_text = (
        "Les commandes disponibles sont :\n"
        "/start - Menu principal\n"
        "/stats - Statistiques de parrainage\n"
        "/help - Aide et conditions"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        reply_markup=get_back_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les interactions via les boutons inline et supprime le message actuel lors du retour au menu."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id

    if query.data == "check_joined":
        if await check_channel_membership(user_id, context):
            cursor.execute("UPDATE users SET has_joined = TRUE WHERE user_id = ?", (user_id,))
            conn.commit()
            if query.message.caption:
                await query.edit_message_caption(
                    "✅ Vérification réussie ! Vous avez rejoint le canal.",
                    reply_markup=get_back_keyboard()
                )
            else:
                await query.edit_message_text(
                    "✅ Vérification réussie ! Vous avez rejoint le canal.",
                    reply_markup=get_back_keyboard()
                )
            await check_rewards(user_id, context)
        else:
            if query.message.caption:
                await query.edit_message_caption(
                    f"❌ Vous devez d'abord rejoindre le canal : https://t.me/{CHANNEL_LINK}",
                    reply_markup=get_back_keyboard()
                )
            else:
                await query.edit_message_text(
                    f"❌ Vous devez d'abord rejoindre le canal : https://t.me/{CHANNEL_LINK}",
                    reply_markup=get_back_keyboard()
                )
    elif query.data == "stats":
        # Affiche les statistiques dans un nouveau message sans toucher au menu principal
        cursor.execute("SELECT referrals FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        referrals = row[0] if row else 0
        stats_text = (
            f"📊 *Statistiques*\n\n"
            f"➤ Invitations validées : {referrals}/{REQUIRED_REFERRALS}\n"
            f"➤ Progression : {'🟩' * (referrals // 5)}{'⬜️' * (5 - (referrals // 5))}"
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=stats_text,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
    elif query.data == "back_to_menu":
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du message : {e}")
        await start(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les erreurs."""
    logger.error(f"Erreur : {context.error}")

def main() -> None:
    """Lancement du bot."""
    application = Application.builder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('stats', stats))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.Regex(r'^/start ref_'), start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_error_handler(error_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
