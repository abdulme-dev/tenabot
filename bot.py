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

# === Load keys from environment variables ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  # default 0 if not set

# HuggingFace free models
HF_TEXT_MODEL = os.getenv("HF_TEXT_MODEL", "google/flan-t5-small")
HF_IMAGE_MODEL = os.getenv("HF_IMAGE_MODEL", "Salesforce/blip-image-captioning-base")

# === Logging & cache ===
logging.basicConfig(level=logging.INFO)
translation_cache = {}
registered_users = set()
USER_DB_FILE = "users.txt"

# === Load registered users ===
if os.path.exists(USER_DB_FILE):
    with open(USER_DB_FILE, "r") as f:
        registered_users = set(line.strip() for line in f if line.strip())

def save_users():
    with open(USER_DB_FILE, "w") as f:
        for uid in registered_users:
            f.write(f"{uid}\n")

def register_user(user_id):
    user_id = str(user_id)
    if user_id not in registered_users:
        registered_users.add(user_id)
        save_users()
        print(f"✅ New user registered: {user_id}")

# === HuggingFace text generation ===
def hf_text_generate(prompt):
    try:
        url = f"https://api-inference.huggingface.co/models/{HF_TEXT_MODEL}"
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        data = {"inputs": prompt}
        res = requests.post(url, headers=headers, json=data, timeout=60)
        output = res.json()
        if isinstance(output, list) and "generated_text" in output[0]:
            return output[0]["generated_text"]
        return "⚠️ Couldn't generate a reply."
    except Exception as e:
        print("HF Text Error:", e)
        return "⚠️ Error generating text."

# === HuggingFace image captioning ===
def hf_image_caption(image_path):
    try:
        url = f"https://api-inference.huggingface.co/models/{HF_IMAGE_MODEL}"
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        with open(image_path, "rb") as f:
            res = requests.post(url, headers=headers, files={"inputs": f}, timeout=60)
        output = res.json()
        if isinstance(output, dict) and "error" in output:
            return "⚠️ Couldn't process the image."
        return output[0].get("generated_text", "❌ Couldn't describe the image.")
    except Exception as e:
        print("HF Image Error:", e)
        return "⚠️ Image processing failed."

# === Translate functions ===
def translate_to_amharic(text):
    return GoogleTranslator(source="auto", target="am").translate(text=text)

def translate_to_english(text):
    return GoogleTranslator(source="auto", target="en").translate(text=text)

# === Helper to add subject to prompt ===
def build_subject_prompt(user_data, prompt):
    subject = user_data.get("subject")
    if subject:
        prompt = f"You are a {subject} assistant. Answer clearly and concisely.\nQuestion: {prompt}"
    return prompt

# === Text Handler ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    register_user(user_id)
    user_data = context.user_data
    prompt = update.message.text

    await update.message.chat.send_action(action=ChatAction.TYPING)
    full_prompt = build_subject_prompt(user_data, prompt)

    reply_en = await asyncio.to_thread(hf_text_generate, full_prompt)
    reply_am = await asyncio.to_thread(translate_to_amharic, reply_en)

    sent_msg = await update.message.reply_text(reply_am)
    translation_cache[str(sent_msg.message_id)] = {"am": reply_am, "en": reply_en, "current": "am"}

    keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]]
    await update.message.reply_text("🌍 ትርጉም ይፈልጋሉ?", reply_markup=InlineKeyboardMarkup(keyboard))

# === Image Handler ===
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    register_user(user_id)
    user_data = context.user_data

    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            await file.download_to_drive(custom_path=tmp.name)
            caption = await asyncio.to_thread(hf_image_caption, tmp.name)
            full_prompt = build_subject_prompt(user_data, caption)

            reply_en = await asyncio.to_thread(hf_text_generate, full_prompt)
            reply_am = await asyncio.to_thread(translate_to_amharic, reply_en)

        sent_msg = await update.message.reply_text(reply_am)
        translation_cache[str(sent_msg.message_id)] = {"am": reply_am, "en": reply_en, "current": "am"}

        keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]]
        await update.message.reply_text("🌍 ትርጉም ይፈልጋሉ?", reply_markup=InlineKeyboardMarkup(keyboard))

        os.remove(tmp.name)

    except Exception as e:
        print("Image handler error:", e)
        await update.message.reply_text("⚠️ ምስል ማቀናበር አልተሳካም።")

# === Inline Button Handler ===
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
            await query.message.edit_text(f"🔁 English:\n\n{data['en']}")
            data["current"] = "en"
            keyboard = [[InlineKeyboardButton("🌐 Translate to Amharic", callback_data=f"translate|{msg_id}")]]
            await query.message.reply_text("🌍 Want Amharic?", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.message.edit_text(f"🔁 አማርኛ:\n\n{data['am']}")
            data["current"] = "am"
            keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{msg_id}")]]
            await query.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        print("Button Error:", e)
        await query.message.reply_text("⚠️ ቁልፍ ማስኬድ አልተሳካም።")

# === Start Command ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    register_user(user_id)
    keyboard = [
        [InlineKeyboardButton("Math", callback_data="subject|math"),
         InlineKeyboardButton("Physics", callback_data="subject|physics"),
         InlineKeyboardButton("English", callback_data="subject|english")]
    ]
    await update.message.reply_text("👋 Welcome! Choose a subject:", reply_markup=InlineKeyboardMarkup(keyboard))

# === Subject selection ===
async def handle_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, subject = query.data.split("|", 1)
    context.user_data["subject"] = subject
    await query.message.reply_text(f"✅ You are now in **{subject.capitalize()} assistant** mode.")

# === Admin command ===
async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ You are not authorized.")
        return
    if registered_users:
        users_list = "\n".join(registered_users)
        await update.message.reply_text(f"📋 Registered Users:\n\n{users_list}")
    else:
        await update.message.reply_text("📋 No registered users.")

# === App setup ===
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("allusers", all_users))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_image))
app.add_handler(CallbackQueryHandler(handle_button, pattern="^translate"))
app.add_handler(CallbackQueryHandler(handle_subject, pattern="^subject"))

print("🚀 Bot is live!")
asyncio.run(app.run_polling())
