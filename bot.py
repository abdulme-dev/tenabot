import os, logging, asyncio
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

# === Load environment variables ===
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "mistralai/mistral-7b-instruct"

translation_cache = {}
logging.basicConfig(level=logging.INFO)

# === Get AI reply from OpenRouter ===
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
        return GoogleTranslator(source="auto", target="am").translate(res.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print("Chat error:", e)
        return "⚠️ Couldn't generate a reply."

# === Translate text to Amharic ===
def translate_to_amharic(text):
    try:
        return GoogleTranslator(source="auto", target="en").translate(text)
    except Exception as e:
        print("Translation error:", e)
        return "⚠️ Translation failed."

# === Bot Command: /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 Send me a message and I'll reply!")

# === Handle user text input ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)

    reply = await asyncio.to_thread(get_ai_reply, prompt)
    sent_msg = await update.message.reply_text(reply)

    translation_cache[str(sent_msg.message_id)] = reply
    keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"t|{sent_msg.message_id}")]]
    await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

# === Handle inline button click for translation ===
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
        print("Button error:", e)

# === Run the bot ===
def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_button))

    print("🚀 TenaBot is live.")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
