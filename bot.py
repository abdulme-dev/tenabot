import os, logging, asyncio, base64, tempfile, requests, re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CommandHandler

# === Load environment variables ===
load_dotenv()  # works locally
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "mistralai/mistral-7b-instruct"

# === Validate token format early ===
assert re.match(r"^\d+:[\w-]{30,}$", TELEGRAM_BOT_TOKEN or ""), "❌ Invalid or missing TELEGRAM_BOT_TOKEN"

translation_cache = {}
logging.basicConfig(level=logging.INFO)

# === AI Chat via OpenRouter ===
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
            },
        )
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("Chat error:", e)
        return "⚠️ Couldn't generate a reply."

# === Translate to Amharic ===
def translate_to_amharic(text):
    return get_ai_reply(f"Translate this to Amharic:\n{text}")

# === Image Captioning using OpenRouter LLaVA ===
def generate_image_caption(image_path):
    try:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()

        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://yourdomain.com"
            },
            json={
                "model": "nousresearch/llava-v1.5-7b",
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text": "Describe this image."},
                        {"type": "image_url", "image_url": {
                            "url": "data:image/jpeg;base64," + encoded
                        }}
                    ]}
                ]
            }
        )
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("Image captioning error:", e)
        return "⚠️ Failed to analyze the image."

# === Bot Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to TenaBot! Send me a message or an image.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)

    reply = await asyncio.to_thread(get_ai_reply, prompt)
    sent_msg = await update.message.reply_text(reply)

    # Add translation button
    translation_cache[str(sent_msg.message_id)] = reply
    keyboard = [[InlineKeyboardButton("🌐 Translate to Amharic", callback_data=f"t|{sent_msg.message_id}")]]
    await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        photo = await update.message.photo[-1].get_file()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        await photo.download_to_drive(tmp.name)

        caption = await asyncio.to_thread(generate_image_caption, tmp.name)
        reply = await asyncio.to_thread(get_ai_reply, caption)
        os.remove(tmp.name)

        sent_msg = await update.message.reply_text(reply)
        translation_cache[str(sent_msg.message_id)] = reply

        keyboard = [[InlineKeyboardButton("🌐 Translate to Amharic", callback_data=f"t|{sent_msg.message_id}")]]
        await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        print("Image error:", e)
        await update.message.reply_text("⚠️ Couldn't process the image.")

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

# === Build and Run the Bot ===
def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(CallbackQueryHandler(handle_button))

    print("🚀 TenaBot is live.")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
