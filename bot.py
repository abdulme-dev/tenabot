import os
import logging
import asyncio
import tempfile
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    CommandHandler,
)
from deep_translator import GoogleTranslator

# === Load API Keys from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # Replace with your Telegram ID

# === Logging
logging.basicConfig(level=logging.INFO)

# === Users DB
USER_DB_FILE = "users.txt"
if os.path.exists(USER_DB_FILE):
    with open(USER_DB_FILE, "r") as f:
        registered_users = set(line.strip() for line in f if line.strip())
else:
    registered_users = set()

def save_users():
    with open(USER_DB_FILE, "w") as f:
        for uid in registered_users:
            f.write(f"{uid}\n")

def register_user(user_id):
    user_id = str(user_id)
    if user_id not in registered_users:
        registered_users.add(user_id)
        save_users()
        logging.info(f"✅ New user registered: {user_id}")

# === Translation cache
translation_cache = {}

# === Subjects
SUBJECTS = ["Math", "Physics", "Chemistry", "Biology", "English"]

# === OpenRouter AI function
def get_ai_reply(prompt, subject=None):
    try:
        system_msg = f"You are a helpful assistant for {subject or 'general'} topics."
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek/deepseek-chat-v3.1:free",
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=30
        )
        data = res.json()
        content = data["choices"][0]["message"]["content"]
        # Translate to Amharic
        reply_am = GoogleTranslator(source="auto", target="am").translate(content)
        return content, reply_am
    except Exception as e:
        logging.error("AI Error: %s", e)
        return "⚠️ Couldn't generate a reply.", "⚠️ መልስ ማፍጠር አልተሳካም።"

# === Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    keyboard = [
        [InlineKeyboardButton(sub, callback_data=f"subject|{sub}") for sub in SUBJECTS]
    ]
    await update.message.reply_text(
        "👋 Welcome! Choose your subject to start:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# === Command: /allusers (Admin only)
async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ You are not authorized.")
        return
    if registered_users:
        await update.message.reply_text("📋 Registered Users:\n" + "\n".join(registered_users))
    else:
        await update.message.reply_text("📋 No registered users found.")

# === Handle subject selection
async def handle_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, subject = query.data.split("|", 1)
    context.user_data["subject"] = subject
    await query.message.reply_text(f"✅ Subject set to *{subject}*.\nNow send me your question or photo.", parse_mode="Markdown")

# === Handle text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    prompt = update.message.text
    subject = context.user_data.get("subject", None)

    await update.message.chat.send_action(action=ChatAction.TYPING)
    reply_en, reply_am = await asyncio.to_thread(get_ai_reply, prompt, subject)

    sent_msg = await update.message.reply_text(reply_am)
    translation_cache[str(sent_msg.message_id)] = {
        "am": reply_am,
        "en": reply_en,
        "current": "am"
    }

    keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]]
    await update.message.reply_text("🌍 ትርጉም ይፈልጋሉ?", reply_markup=InlineKeyboardMarkup(keyboard))

# === Handle photos
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            await file.download_to_drive(custom_path=tmp.name)
            prompt = f"Describe this image for educational purposes."
            subject = context.user_data.get("subject", None)
            reply_en, reply_am = await asyncio.to_thread(get_ai_reply, prompt, subject)

        sent_msg = await update.message.reply_text(reply_am)
        translation_cache[str(sent_msg.message_id)] = {"am": reply_am, "en": reply_en, "current": "am"}

        keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]]
        await update.message.reply_text("🌍 ትርጉም ይፈልጋሉ?", reply_markup=InlineKeyboardMarkup(keyboard))
        os.remove(tmp.name)

    except Exception as e:
        logging.error("Photo handler error: %s", e)
        await update.message.reply_text("⚠️ ምስል ማቀናበር አልተሳካም።")

# === Handle translate button
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, msg_id = query.data.split("|", 1)
        data = translation_cache.get(msg_id)
        if not data:
            await query.message.reply_text("⚠️ መልዕክት አልተገኘም።")
            return

        if data["current"] == "am":
            await query.message.reply_text(f"🔁 English:\n\n{data['en']}")
            data["current"] = "en"
            keyboard = [[InlineKeyboardButton("🌐 Translate to Amharic", callback_data=f"translate|{msg_id}")]]
            await update.message.reply_text("🌍 Want Amharic?", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.message.reply_text(f"🔁 አማርኛ:\n\n{data['am']}")
            data["current"] = "am"
            keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{msg_id}")]]
            await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logging.error("Button Error: %s", e)
        await query.message.reply_text("⚠️ ቁልፍ ማስኬድ አልተሳካም።")

# === Main application
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("allusers", all_users))
app.add_handler(CallbackQueryHandler(handle_subject, pattern="subject\\|"))
app.add_handler(CallbackQueryHandler(handle_button, pattern="translate\\|"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

logging.info("🚀 TenaBot is live and ready to deploy!")
asyncio.run(app.run_polling())
