# simplified_bot.py - Deploy this first
import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters, 
    CallbackQueryHandler, CommandHandler
)
import requests

# Environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

logging.basicConfig(level=logging.INFO)

# Simple AI response function
def get_ai_reply(prompt):
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
        r = requests.post(url, headers=headers, json=data, timeout=30)
        r.raise_for_status()
        response = r.json()
        return response['choices'][0]['message']['content']
    except Exception as e:
        logging.error(f"AI API error: {e}")
        return "⚠️ AI service is temporarily unavailable. Please try again later."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Send me a message and I'll help you.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action(action=ChatAction.TYPING)
    prompt = update.message.text
    reply = await asyncio.to_thread(get_ai_reply, prompt)
    await update.message.reply_text(reply)

# Setup bot
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

if __name__ == "__main__":
    logging.info("🚀 Bot starting...")
    app.run_polling()
