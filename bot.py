import os
import logging
import asyncio
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CommandHandler
from PIL import Image
import pytesseract

# ===== ENV VARIABLES =====
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# ===== LOGGING =====
logging.basicConfig(level=logging.INFO)

# ===== USER REGISTRATION =====
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

# ===== TRANSLATION CACHE =====
translation_cache = {}

# ===== AI REPLY FUNCTION =====
def get_ai_reply(prompt, subject=None):
    """ Replace with real AI call (OpenRouter/DeepSeek). """
    # Simulated Ethiopian-tailored responses
    reply_en = f"🇬🇧 English Answer for {subject or 'General'}:\nThis is a detailed explanation for: {prompt}"
    reply_am = f"🇪🇹 አማርኛ መልስ ለ {subject or 'አጠቃላይ'}:\nይህ በተለይ ለኢትዮጵያውያን ተማሪዎች የተዘጋጀ መልስ ነው።\n\n{prompt}"
    return reply_en, reply_am

# ===== START HANDLER =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("👋 እንኳን ደህና መጡ። ጥያቄዎን በአማርኛ ወይም በእንግሊዝኛ ይጻፉ።")

# ===== TEXT HANDLER =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)

    reply_en, reply_am = await asyncio.to_thread(get_ai_reply, prompt)
    sent_msg = await update.message.reply_text(reply_am)

    translation_cache[str(sent_msg.message_id)] = {
        "am": reply_am, "en": reply_en, "current": "am"
    }

    keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]]
    await update.message.reply_text("👉 ትርጉም ይፈልጋሉ?", reply_markup=InlineKeyboardMarkup(keyboard))

# ===== PHOTO HANDLER =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            await file.download_to_drive(custom_path=tmp.name)
            img = Image.open(tmp.name)
            text = pytesseract.image_to_string(img).strip()
            if not text:
                await update.message.reply_text("⚠️ ምንም ጽሁፍ አልተገኘም።")
                return

            prompt = f"Extracted text:\n{text}"
            reply_en, reply_am = await asyncio.to_thread(get_ai_reply, prompt)

        sent_msg = await update.message.reply_text(reply_am)
        translation_cache[str(sent_msg.message_id)] = {
            "am": reply_am, "en": reply_en, "current": "am"
        }

        keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]]
        await update.message.reply_text("👉 ትርጉም ይፈልጋሉ?", reply_markup=InlineKeyboardMarkup(keyboard))
        os.remove(tmp.name)

    except Exception as e:
        logging.error("Photo handler error: %s", e)
        await update.message.reply_text("⚠️ ምስል ማቀናበር አልተሳካም።")

# ===== BUTTON HANDLER =====
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, data = query.data.split("|", 1)
        if action == "translate":
            msg_id = data
            data = translation_cache.get(msg_id)
            if not data:
                await query.message.reply_text("⚠️ Message not found.")
                return

            if data["current"] == "am":
                new_text = data["en"]
                data["current"] = "en"
                new_btn = "Translate to Amharic"
            else:
                new_text = data["am"]
                data["current"] = "am"
                new_btn = "Translate to English"

            await query.message.edit_text(new_text)
            await query.message.reply_markup(
                InlineKeyboardMarkup([[InlineKeyboardButton(f"🌐 {new_btn}", callback_data=f"translate|{msg_id}")]])
            )

    except Exception as e:
        logging.error("Button error: %s", e)
        await query.message.reply_text("⚠️ Translation failed.")

# ===== SETUP BOT =====
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CallbackQueryHandler(handle_button))

print("🚀 Amharic Study Bot is live...")

if __name__ == "__main__":
    asyncio.run(app.run_polling())
