import os, logging, asyncio, tempfile, base64, re, requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    MessageHandler, filters,
    CallbackQueryHandler, CommandHandler
)
from pydub import AudioSegment

# === Load env ===
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "mistralai/mistral-7b-instruct"

assert re.match(r"^\d+:[\w-]{30,}$", TELEGRAM_BOT_TOKEN or ""), "❌ Invalid or missing TELEGRAM_BOT_TOKEN"

translation_cache = {}
logging.basicConfig(level=logging.INFO)

# === OpenRouter AI chat ===
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
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("Chat error:", e)
        return "⚠️ Couldn't generate a reply."

# === Translation ===
def translate_to_amharic(text):
    return get_ai_reply(f"Translate this to Amharic:\n{text}")

# === Voice to text using Whisper ===
def transcribe_voice(audio_path):
    try:
        mp3_path = tempfile.mktemp(suffix=".mp3")
        sound = AudioSegment.from_ogg(audio_path)
        sound.export(mp3_path, format="mp3")

        with open(mp3_path, "rb") as audio_file:
            audio_bytes = audio_file.read()
            encoded = base64.b64encode(audio_bytes).decode()

        payload = {
            "model": "openai/whisper",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe this voice note:"},
                        {
                            "type": "audio_url",
                            "audio_url": {
                                "url": "data:audio/mp3;base64," + encoded
                            }
                        }
                    ]
                }
            ]
        }

        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://yourdomain.com"
            },
            json=payload
        )

        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("Voice error:", e)
        return "⚠️ Failed to transcribe voice."

# === Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎤 Send voice or text to TenaBot.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)

    reply = await asyncio.to_thread(get_ai_reply, prompt)
    sent_msg = await update.message.reply_text(reply)

    translation_cache[str(sent_msg.message_id)] = reply
    keyboard = [[InlineKeyboardButton("🌐 Translate to Amharic", callback_data=f"t|{sent_msg.message_id}")]]
    await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        voice = await update.message.voice.get_file()
        ogg_path = tempfile.mktemp(suffix=".ogg")
        await voice.download_to_drive(ogg_path)

        transcription = await asyncio.to_thread(transcribe_voice, ogg_path)
        reply = await asyncio.to_thread(get_ai_reply, transcription)

        sent_msg = await update.message.reply_text(reply)
        translation_cache[str(sent_msg.message_id)] = reply

        keyboard = [[InlineKeyboardButton("🌐 Translate to Amharic", callback_data=f"t|{sent_msg.message_id}")]]
        await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

        os.remove(ogg_path)
    except Exception as e:
        print("Voice processing error:", e)
        await update.message.reply_text("⚠️ Couldn't process your voice note.")

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
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(CallbackQueryHandler(handle_button))

    print("🚀 TenaBot is live.")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
