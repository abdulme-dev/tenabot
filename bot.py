import os
import logging
import asyncio
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters, 
    CallbackQueryHandler, CommandHandler
)
from PIL import Image
import pytesseract
from googletrans import Translator
import requests
import speech_recognition as sr
from pydub import AudioSegment

# ===== ENV VARIABLES =====
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# ===== LOGGING =====
logging.basicConfig(level=logging.INFO)

# ===== USER REGISTRATION =====
USER_DB_FILE = "users.txt"

def load_users():
    """Load registered users from file"""
    if os.path.exists(USER_DB_FILE):
        with open(USER_DB_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_users(users):
    """Save users to file"""
    with open(USER_DB_FILE, "w") as f:
        for uid in users:
            f.write(f"{uid}\n")

# Initialize users set
registered_users = load_users()

def register_user(user_id):
    """Register a new user"""
    user_id = str(user_id)
    if user_id not in registered_users:
        registered_users.add(user_id)
        save_users(registered_users)
        logging.info(f"✅ New user registered: {user_id}")
        return True
    return False

# ===== TRANSLATION CACHE =====
translation_cache = {}

# ===== AI CALL FUNCTION =====
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
    user_id = update.effective_user.id
    is_new = register_user(user_id)
    
    welcome_text = "👋 እንኳን ደህና መጡ! ጥያቄ ያስቀምጡ (ጽሑፍ፣ ፎቶ ወይም ድምጽ) አሁን በአማርኛ የAI ምላሽ ለማግኘት።"
    if is_new:
        welcome_text += "\n\n✅ እንደ አዲስ ተጠቃሚ ተመዝግበዋል!"
    
    await update.message.reply_text(welcome_text)

# ===== LIST USERS (ADMIN) =====
async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አልተፈቀደልዎትም።")
        return
    
    if registered_users:
        user_list = "📋 የተመዘገቡ ተጠቃሚዎች:\n\n"
        for i, user_id in enumerate(registered_users, 1):
            user_list += f"{i}. {user_id}\n"
        
        # Split if message is too long
        if len(user_list) > 4000:
            user_list = user_list[:4000] + "\n\n... (more users)"
            
        await update.message.reply_text(user_list)
    else:
        await update.message.reply_text("📋 ምንም የተመዘገቡ ተጠቃሚዎች አልተገኙም።")

# ===== GENERIC AI RESPONSE FUNCTION =====
async def generate_response(prompt, update):
    await update.message.chat.send_action(action=ChatAction.TYPING)
    
    # Get AI response in English
    reply_en = await asyncio.to_thread(get_ai_reply, prompt)
    
    # Translate to Amharic
    reply_am = await asyncio.to_thread(translate_to_amharic, reply_en)
    
    # Send Amharic response first
    sent_msg = await update.message.reply_text(reply_am)
    
    # Store both versions in cache
    translation_cache[str(sent_msg.message_id)] = {
        "am": reply_am, 
        "en": reply_en, 
        "current": "am"  # Currently showing Amharic
    }
    
    # Add translate button to show English version
    keyboard = [
        [InlineKeyboardButton("🌐 ወደ እንግሊዘኛ ተርጉም", callback_data=f"translate|{sent_msg.message_id}")]
    ]
    await update.message.reply_text("ምርጫዎች:", reply_markup=InlineKeyboardMarkup(keyboard))

# ===== HANDLE TEXT =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    prompt = update.message.text
    await generate_response(prompt, update)

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
                await update.message.reply_text("⚠️ ጽሑፍ ማንበብ አልቻልኩም። እባክዎ ጥያቄዎን ይተይቡ።")
                return
            update.message.text = text
            await generate_response(text, update)
        os.remove(tmp.name)
    except Exception as e:
        logging.error("Photo handler error: %s", e)
        await update.message.reply_text("⚠️ የምስስ ማቀናበር አልተሳካም።")

# ===== HANDLE VOICE =====
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    try:
        voice = update.message.voice
        file = await voice.get_file()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp_ogg:
            await file.download_to_drive(custom_path=tmp_ogg.name)
            tmp_wav_path = tmp_ogg.name.replace(".ogg", ".wav")
            AudioSegment.from_ogg(tmp_ogg.name).export(tmp_wav_path, format="wav")
            
            recognizer = sr.Recognizer()
            with sr.AudioFile(tmp_wav_path) as source:
                audio = recognizer.record(source)
                text = recognizer.recognize_google(audio)
            
            update.message.text = text
            await generate_response(text, update)
        
        os.remove(tmp_ogg.name)
        os.remove(tmp_wav_path)
    except Exception as e:
        logging.error("Voice handler error: %s", e)
        await update.message.reply_text("⚠️ ድምጽ ማወቅ አልተሳካም።")

# ===== BUTTON HANDLER =====
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if query.data.startswith("translate"):
            msg_id = query.data.split("|")[1]
            data = translation_cache.get(msg_id)
            if not data:
                await query.message.reply_text("⚠️ መልዕክት አልተገኘም።")
                return
            
            # Toggle between Amharic and English
            if data["current"] == "am":
                # Switch to English (original AI response)
                new_text = data["en"]
                new_button_text = "🌐 ወደ አማርኛ ተርጉም"
                data["current"] = "en"
            else:
                # Switch back to Amharic
                new_text = data["am"]
                new_button_text = "🌐 ወደ እንግሊዘኛ ተርጉም"
                data["current"] = "am"
            
            # Update the message text
            await query.message.edit_text(new_text)
            
            # Update the button
            keyboard = [
                [InlineKeyboardButton(new_button_text, callback_data=f"translate|{msg_id}")]
            ]
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            
    except Exception as e:
        logging.error("Button error: %s", e)
        await query.message.reply_text("⚠️ አዝራሩ አልሰራም።")

# ===== BROADCAST MESSAGE (ADMIN) =====
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አልተፈቀደልዎትም።")
        return
    
    if not context.args:
        await update.message.reply_text("📢 አጠቃቀም: /broadcast <message>")
        return
    
    message = " ".join(context.args)
    success_count = 0
    fail_count = 0
    
    await update.message.reply_text(f"📢 ለ {len(registered_users)} ተጠቃሚዎች መልዕክት በማስተላለፍ ላይ...")
    
    for user_id in registered_users:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            success_count += 1
            await asyncio.sleep(0.1)  # Rate limiting
        except Exception as e:
            logging.error(f"Failed to send to {user_id}: {e}")
            fail_count += 1
    
    await update.message.reply_text(
        f"✅ የተላለፈ: {success_count}\n"
        f"❌ አልተላለፈም: {fail_count}"
    )

# ===== STATS COMMAND (ADMIN) =====
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አልተፈቀደልዎትም።")
        return
    
    stats_text = (
        f"📊 የቦቱ ስታትስቲክስ:\n\n"
        f"👥 አጠቃላይ ተጠቃሚዎች: {len(registered_users)}\n"
        f"💬 የተመኘ ትርጉም: {len(translation_cache)}\n"
        f"🆔 የአስተዳዳሪ ID: {ADMIN_ID}"
    )
    await update.message.reply_text(stats_text)

# ===== SETUP BOT =====
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

# Add handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("allusers", all_users))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(CallbackQueryHandler(handle_button))

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Exception while handling an update: {context.error}")
    
app.add_error_handler(error_handler)

print("🚀 MiniBot is live...")

if __name__ == "__main__":
    # Create users file if it doesn't exist
    if not os.path.exists(USER_DB_FILE):
        save_users(set())
    
    asyncio.run(app.run_polling())
