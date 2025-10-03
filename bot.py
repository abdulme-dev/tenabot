import os
import logging
import asyncio
import tempfile
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler,
    filters, CallbackQueryHandler, CommandHandler
)
from PIL import Image
import pytesseract
from googletrans import Translator
import speech_recognition as sr
from pydub import AudioSegment
from gtts import gTTS

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

# ===== GOOGLE TRANSLATE =====
translator = Translator()

def translate_to_amharic(text: str) -> str:
    try:
        result = translator.translate(text, dest="am")
        return result.text
    except Exception as e:
        logging.error("Translation error: %s", e)
        return "⚠️ Translation failed."

# ===== AI REPLY FUNCTION (English from OpenRouter) =====
def get_ai_reply(prompt):
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }

        data = {
            "model": "deepseek/deepseek-chat-v3.1:free",
            "messages": [
                {"role": "system", "content": "You are a helpful tutor for Ethiopian students. Always explain clearly."},
                {"role": "user", "content": prompt},
            ]
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code != 200:
            err = f"⚠️ OpenRouter Error {response.status_code}: {response.text}"
            return err, err

        res_json = response.json()
        reply_en = res_json["choices"][0]["message"]["content"].strip()

        # Translate into Amharic
        reply_am = translate_to_amharic(reply_en)

        return reply_en, reply_am

    except Exception as e:
        logging.error("AI Error: %s", e)
        return f"⚠️ AI Error: {str(e)}", f"⚠️ AI ስህተት: {str(e)}"

# ===== START HANDLER =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text("👋 እንኳን ደህና መጡ! ጥያቄዎን ይጻፉ፣ ፎቶ ይላኩ ወይም ድምፅ ይናገሩ።")

# ===== AI RESPONSE SENDER (Text + Voice) =====
async def send_ai_response(update, reply_en, reply_am):
    sent_msg = await update.message.reply_text(reply_am)

    # Save for translation toggle
    translation_cache[str(sent_msg.message_id)] = {"am": reply_am, "en": reply_en, "current": "am"}

    # Send Amharic voice reply
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_mp3:
            tts = gTTS(reply_am, lang="am")
            tts.save(tmp_mp3.name)

            ogg_path = tmp_mp3.name.replace(".mp3", ".ogg")
            AudioSegment.from_file(tmp_mp3.name).export(ogg_path, format="ogg")

            await update.message.reply_voice(voice=open(ogg_path, "rb"))
            os.remove(tmp_mp3.name)
            os.remove(ogg_path)
    except Exception as e:
        logging.error("TTS Error: %s", e)

    # Add button
    keyboard = [[InlineKeyboardButton("🌐 Translate", callback_data=f"translate|{sent_msg.message_id}")]]
    await update.message.reply_text("Options:", reply_markup=InlineKeyboardMarkup(keyboard))

# ===== TEXT HANDLER =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)

    reply_en, reply_am = await asyncio.to_thread(get_ai_reply, prompt)
    await send_ai_response(update, reply_en, reply_am)

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
            os.remove(tmp.name)

        if not text:
            await update.message.reply_text("⚠️ በፎቶው ውስጥ ጽሑፍ አልተገኘም።")
            return

        await update.message.chat.send_action(action=ChatAction.TYPING)
        reply_en, reply_am = await asyncio.to_thread(get_ai_reply, text)
        await send_ai_response(update, reply_en, reply_am)

    except Exception as e:
        logging.error("Photo handler error: %s", e)
        await update.message.reply_text(f"⚠️ ፎቶ አልተሰራም። {str(e)}")

# ===== VOICE HANDLER =====
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    try:
        voice = await update.message.voice.get_file()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            await voice.download_to_drive(custom_path=tmp.name)
            ogg_path = tmp.name
            wav_path = ogg_path.replace(".ogg", ".wav")

        # Convert OGG to WAV
        AudioSegment.from_file(ogg_path).export(wav_path, format="wav")
        os.remove(ogg_path)

        # Recognize speech (Amharic)
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="am-ET")

        os.remove(wav_path)

        if not text:
            await update.message.reply_text("⚠️ ድምፅ አልተሰማም።")
            return

        await update.message.chat.send_action(action=ChatAction.TYPING)
        reply_en, reply_am = await asyncio.to_thread(get_ai_reply, text)
        await send_ai_response(update, reply_en, reply_am)

    except Exception as e:
        logging.error("Voice handler error: %s", e)
        await update.message.reply_text(f"⚠️ ድምፅ አልተሰራም። {str(e)}")

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
                await query.message.reply_text("⚠️ መልእክት አልተገኘም።")
                return

            if data["current"] == "am":
                new_text = data["en"]
                data["current"] = "en"
            else:
                new_text = data["am"]
                data["current"] = "am"

            await query.message.edit_text(new_text)

    except Exception as e:
        logging.error("Button Error: %s", e)
        await query.message.reply_text(f"⚠️ Button failed: {str(e)}")

# ===== SETUP BOT =====
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(CallbackQueryHandler(handle_button))

print("🚀 EduBot (Text + OCR + Voice + TTS) is live...")

if __name__ == "__main__":
    asyncio.run(app.run_polling())
