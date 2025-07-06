import os, logging, asyncio, time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    MessageHandler, filters,
    CallbackQueryHandler, CommandHandler
)
import requests
from deep_translator import GoogleTranslator
from collections import defaultdict

# === Load environment variables ===
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "mistralai/mistral-7b-instruct"

# === Logging setup ===
logging.basicConfig(level=logging.INFO)

# === User Tracking and Rate Limiting ===
user_set = set()
ADMIN_IDS = {7448164827}  # Replace with your Telegram ID
RATE_LIMIT = 5  # messages
TIME_WINDOW = 10 * 10  # 1 hour
user_requests = defaultdict(list)

translation_cache = {}

# === Get AI reply ===
def get_ai_reply(prompt):
    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://yourdomain.com"
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ]
            }
        )
        return GoogleTranslator(source="auto", target="en").translate(res.json()["choices"][0]["message"]["content"])
    except Exception as e:
        logging.error(f"Chat error: {e}")
        return "⚠️ Couldn't generate a reply."

# === Translate to Amharic ===
def translate_to_amharic(text):
    try:
        return GoogleTranslator(source="auto", target="en").translate(text)
    except Exception as e:
        logging.error(f"Translation error: {e}")
        return "⚠️ Translation failed."

# === Rate limit logic ===
def is_rate_limited(user_id):
    now = time.time()
    requests = user_requests[user_id]
    user_requests[user_id] = [t for t in requests if now - t < TIME_WINDOW]
    if len(user_requests[user_id]) >= RATE_LIMIT:
        return True
    user_requests[user_id].append(now)
    return False

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_set.add(user.id)
    logging.info(f"/start by {user.id} - @{user.username}")
    await update.message.reply_text("💬 Send me a message and I'll reply!")

# === /users ===
async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text(f"👥 Total unique users: {len(user_set)}")
    else:
        await update.message.reply_text("❌ You're not authorized to view user stats.")

# === Handle text ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_set.add(user.id)
    logging.info(f"Text from {user.id} - @{user.username}: {update.message.text}")

    if is_rate_limited(user.id):
        await update.message.reply_text("⚠️ Rate limit reached. Try again in a while.")
        return

    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)

    reply = await asyncio.to_thread(get_ai_reply, prompt)
    sent_msg = await update.message.reply_text(reply)

    translation_cache[str(sent_msg.message_id)] = reply
    keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"t|{sent_msg.message_id}")]]
    await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

# === Handle button ===
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, msg_id = query.data.split("|", 1)
        if action == "t":
            original = translation_cache.get(msg_id)
            if original:
                translated = await asyncio.to_thread(translate_to_amharic, original)
                await query.message.reply_text(f"🔁 Translated:\n\n{translated}")
    except Exception as e:
        logging.error(f"Button error: {e}")

# === Run bot ===
def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("users", show_users))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_button))

    logging.info("🚀 TenaBot is live.")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
