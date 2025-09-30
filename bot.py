import os
import logging
import asyncio
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CommandHandler
from PIL import Image
import pytesseract
import requests

# ===== ENV VARIABLES =====
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
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

# ===== SUBJECT BUTTONS =====
def subject_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Math", callback_data="subject|Math"),
            InlineKeyboardButton("Physics", callback_data="subject|Physics"),
            InlineKeyboardButton("Chemistry", callback_data="subject|Chemistry"),
        ]
    ])

# ===== TASK BUTTONS =====
def task_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Worksheet", callback_data="task|worksheet")],
        [InlineKeyboardButton("🏠 Homework", callback_data="task|homework")],
        [InlineKeyboardButton("📄 Assignment", callback_data="task|assignment")],
    ])

# ===== START HANDLER =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text(
        "👋 Welcome! Choose a subject first:",
        reply_markup=subject_keyboard()
    )

# ===== LIST ALL USERS (ADMIN) =====
async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    if registered_users:
        await update.message.reply_text("📋 Registered Users:\n" + "\n".join(registered_users))
    else:
        await update.message.reply_text("📋 No registered users found.")

# ===== OPENROUTER API CALL =====
def openrouter_api_call(prompt, subject=None, image_path=None):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": "deepseek/deepseek-r1:free",
        "messages": [{"role": "user", "content": prompt}],
        "image": image_path,
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()
    else:
        logging.error(f"OpenRouter API Error: {response.status_code} - {response.text}")
        return None

# ===== SUBJECT HANDLER =====
async def handle_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, subject = query.data.split("|", 1)
    context.user_data["subject"] = subject
    await query.message.reply_text(f"✅ Subject set to {subject}. Choose a task type:", reply_markup=task_keyboard())

# ===== TASK HANDLER =====
async def handle_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, task_type = query.data.split("|", 1)
    subject = context.user_data.get("subject")
    if not subject:
        await query.message.reply_text("⚠️ Please select a subject first.", reply_markup=subject_keyboard())
        return

    prompt = f"Create a {task_type} for {subject} with multiple questions and answers."
    await query.message.chat.send_action(action=ChatAction.TYPING)

    response = openrouter_api_call(prompt, subject)
    if response:
        reply = response.get("choices", [{}])[0].get("message", {}).get("content", "No response")
        await query.message.reply_text(reply)
    else:
        await query.message.reply_text("⚠️ Failed to generate content.")

# ===== TEXT MESSAGE HANDLER =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    subject = context.user_data.get("subject")
    if not subject:
        await update.message.reply_text("⚠️ Please select a subject first:", reply_markup=subject_keyboard())
        return

    prompt = f"[{subject}] {update.message.text}"
    await update.message.chat.send_action(action=ChatAction.TYPING)

    response = openrouter_api_call(prompt, subject)
    if response:
        reply = response.get("choices", [{}])[0].get("message", {}).get("content", "No response")
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text("⚠️ Failed to generate content.")

# ===== PHOTO HANDLER =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    subject = context.user_data.get("subject")
    if not subject:
        await update.message.reply_text("⚠️ Please select a subject first:", reply_markup=subject_keyboard())
        return

    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            await file.download_to_drive(custom_path=tmp.name)
            img = Image.open(tmp.name)
            text = pytesseract.image_to_string(img).strip()
            if not text:
                await update.message.reply_text("⚠️ Couldn't read any text from the image. Please type your question.")
                return

            prompt = f"[{subject}] Extracted question:\n{text}"
            await update.message.chat.send_action(action=ChatAction.TYPING)

            response = openrouter_api_call(prompt, subject, image_path=tmp.name)
            if response:
                reply = response.get("choices", [{}])[0].get("message", {}).get("content", "No response")
                await update.message.reply_text(reply)
            else:
                await update.message.reply_text("⚠️ Failed to generate content.")
            os.remove(tmp.name)

    except Exception as e:
        logging.error("Photo handler error: %s", e)
        await update.message.reply_text("⚠️ Image processing failed.")

# ===== BUTTON HANDLER =====
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if query.data == "change_subject":
            await query.message.reply_text("Select a new subject:", reply_markup=subject_keyboard())
            return

        action, data = query.data.split("|", 1)

        if action == "subject":
            await handle_subject(update, context)
        elif action == "task":
            await handle_task(update, context)

    except Exception as e:
        logging.error("Button Error: %s", e)
        await query.message.reply_text("⚠️ Button failed.")

# ===== SETUP BOT =====
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("allusers", all_users))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CallbackQueryHandler(handle_button))

print("🚀 TenaBot is live...")

if __name__ == "__main__":
    asyncio.run(app.run_polling())
