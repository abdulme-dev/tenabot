import os
import logging
import asyncio
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CommandHandler
from PIL import Image
import pytesseract
from googletrans import Translator
import requests

# ===== ENV VARIABLES =====
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")  # Free OpenRouter API key

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

# ===== AI CALL FUNCTION =====
def get_ai_reply(prompt):
    """
    Use OpenRouter free API (DeepSeek) to generate English response
    """
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-r1:free",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500
        }
        r = requests.post(url, headers=headers, json=data, timeout=20)
        r.raise_for_status()
        response = r.json()
        reply_en = response['choices'][0]['message']['content']
        return reply_en
    except Exception as e:
        logging.error("AI API error: %s", e)
        return "⚠️ AI API Error. Try again later."

# ===== GOOGLE TRANSLATE =====
translator = Translator()
def translate_to_amharic(text):
    try:
        return translator.translate(text, dest='am').text
    except Exception as e:
        logging.error("Translation error: %s", e)
        return "⚠️ Translation failed."

# ===== START HANDLER =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("👋 Welcome! Send a question (text or photo) to generate AI response in Amharic.")

# ===== LIST USERS (ADMIN) =====
async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    if registered_users:
        await update.message.reply_text("📋 Registered Users:\n" + "\n".join(registered_users))
    else:
        await update.message.reply_text("📋 No registered users found.")

# ===== HANDLE TEXT =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)
    
    reply_en = await asyncio.to_thread(get_ai_reply, prompt)
    reply_am = await asyncio.to_thread(translate_to_amharic, reply_en)
    
    sent_msg = await update.message.reply_text(reply_am)
    translation_cache[str(sent_msg.message_id)] = {"am": reply_am, "en": reply_en, "current": "am"}
    
    keyboard = [
        [InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]
    ]
    await update.message.reply_text("Options:", reply_markup=InlineKeyboardMarkup(keyboard))

# ===== HANDLE PHOTO =====
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
                await update.message.reply_text("⚠️ Couldn't read text. Please type your question.")
                return
            
            await update.message.chat.send_action(action=ChatAction.TYPING)
            reply_en = await asyncio.to_thread(get_ai_reply, text)
            reply_am = await asyncio.to_thread(translate_to_amharic, reply_en)
        
        sent_msg = await update.message.reply_text(reply_am)
        translation_cache[str(sent_msg.message_id)] = {"am": reply_am, "en": reply_en, "current": "am"}

        keyboard = [
            [InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]
        ]
        await update.message.reply_text("Options:", reply_markup=InlineKeyboardMarkup(keyboard))
        os.remove(tmp.name)
    except Exception as e:
        logging.error("Photo handler error: %s", e)
        await update.message.reply_text("⚠️ Image processing failed.")

# ===== BUTTON HANDLER =====
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if query.data.startswith("translate"):
            msg_id = query.data.split("|")[1]
            data = translation_cache.get(msg_id)
            if not data:
                await query.message.reply_text("⚠️ Message not found.")
                return
            
            new_text = data["en"] if data["current"] == "am" else data["am"]
            data["current"] = "en" if data["current"] == "am" else "am"
            await query.message.edit_text(new_text)
    except Exception as e:
        logging.error("Button error: %s", e)
        await query.message.reply_text("⚠️ Button failed.")

# ===== SETUP BOT =====
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("allusers", all_users))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CallbackQueryHandler(handle_button))

print("🚀 MiniBot is live...")

if __name__ == "__main__":
    asyncio.run(app.run_polling())
