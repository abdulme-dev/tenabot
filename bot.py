import os
import logging
import asyncio
import tempfile
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CommandHandler
from PIL import Image
import pytesseract

# ===== ENV VARIABLES =====
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

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

# ===== AI CALL (English only) =====
def get_ai_reply(prompt):
    """
    Calls OpenRouter with DeepSeek and returns English text only.
    """
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "deepseek/deepseek-r1:free",
            "messages": [
                {"role": "system", "content": "You are a helpful tutor. Always respond in English."},
                {"role": "user", "content": prompt}
            ]
        }

        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=60)

        if response.status_code == 200:
            reply_text = response.json()["choices"][0]["message"]["content"]
            return reply_text
        else:
            logging.error(f"OpenRouter Error: {response.text}")
            return "⚠️ Failed to generate response."

    except Exception as e:
        logging.error(f"AI Request Error: {e}")
        return "⚠️ AI Error"

# ===== TRANSLATE EN → AM =====
def translate_to_amharic(english_text):
    """
    Simple call to OpenRouter for translation EN → AM
    """
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "deepseek/deepseek-r1:free",
            "messages": [
                {"role": "system", "content": "Translate this text into Amharic. Only return the translation."},
                {"role": "user", "content": english_text}
            ]
        }

        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=60)

        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            logging.error(f"Translation Error: {response.text}")
            return "⚠️ ትርጉም አልተሳካም።"

    except Exception as e:
        logging.error(f"Translation Request Error: {e}")
        return "⚠️ ትርጉም ስህተት"

# ===== START HANDLER =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("👋 እንኳን ደህና መጡ። ጥያቄዎን ይጻፉ ወይም ምስል ይላኩ።")

# ===== TEXT HANDLER =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)

    english = await asyncio.to_thread(get_ai_reply, prompt)
    amharic = await asyncio.to_thread(translate_to_amharic, english)

    sent_msg = await update.message.reply_text(f"🇪🇹 {amharic}")

    translation_cache[str(sent_msg.message_id)] = {"am": f"🇪🇹 {amharic}", "en": f"🇬🇧 {english}", "current": "am"}
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

            english = await asyncio.to_thread(get_ai_reply, text)
            amharic = await asyncio.to_thread(translate_to_amharic, english)

        sent_msg = await update.message.reply_text(f"🇪🇹 {amharic}")
        translation_cache[str(sent_msg.message_id)] = {"am": f"🇪🇹 {amharic}", "en": f"🇬🇧 {english}", "current": "am"}

        keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]]
        await update.message.reply_text("👉 ትርጉም ይፈልጋሉ?", reply_markup=InlineKeyboardMarkup(keyboard))
        os.remove(tmp.name)

    except Exception as e:
        logging.error(f"Photo handler error: {e}")
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

            await query.message.edit_text(new_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🌐 {new_btn}", callback_data=f"translate|{msg_id}")]]))

    except Exception as e:
        logging.error(f"Button Error: {e}")
        await query.message.reply_text("⚠️ Button failed.")

# ===== SETUP BOT =====
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CallbackQueryHandler(handle_button))

print("🚀 Amharic Study Bot (DeepSeek + OpenRouter) is live...")

if __name__ == "__main__":
    asyncio.run(app.run_polling())
