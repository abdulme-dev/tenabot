import os, logging, asyncio, tempfile, requests
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
from dotenv import load_dotenv

load_dotenv()

# === Your API keys directly (no .env for Pydroid)
TELEGRAM_BOT_TOKEN = 7789827415:AAGZsCFQI2e8BFfxs2MCPLSa5EcUFh17phY
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN")
MODEL = os.getenv("MODEL", "mistralai/mistral-7b-instruct")
MODEL = "mistralai/mistral-7b-instruct"

# === Cache AI replies by message_id to avoid long callback_data
translation_cache = {}
logging.basicConfig(level=logging.INFO)

# === Chat AI via OpenRouter ===
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
                    {"role": "system", "content": "You are a helpful assistant For Ethiopians."},
                    {"role": "user", "content": prompt}
                ]
            },
        )
        return GoogleTranslator(source="auto",target='am').translate(text=res.json()["choices"][0]["message"]["content"])
        
    except Exception as e:
        print("AI Error:", e)
        return "⚠️ Couldn't generate a reply."
        
def get_ai_trans(text):
    return GoogleTranslator(source="auto",target='en').translate(text=text)
    
# === Translate to Amharic ===
def translate_to_english(text):
    return get_ai_trans(text)
    
# === Image Captioning with Hugging Face BLIP ===
def generate_image_caption(path):
    try:
        with open(path, "rb") as f:
            res = requests.post(
                "https://api-inference.huggingface.co/models/Salesforce/blip-image-captioning-base",
                headers={"Authorization": f"Bearer {HUGGINGFACE_TOKEN}"},
                files={"inputs": f},
            )
        print("🖼️ Huggingface response:", res.text)
        return res.json().get("generated_text", "❌ Couldn't describe the image.")
    except Exception as e:
        print("Image Captioning Error:", e)
        return "⚠️ Image processing failed."

# === Text Message Handler ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    await update.message.chat.send_action(action=ChatAction.TYPING)

    # Get AI reply
    reply = await asyncio.to_thread(get_ai_reply, prompt)

    # Send AI response
    sent_msg = await update.message.reply_text(reply)

    # Save response for button
    translation_cache[str(sent_msg.message_id)] = reply

    # Show button
    keyboard = [[InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")]]
    await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

# === Image Message Handler ===
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Get the highest quality photo
        photo = update.message.photo[-1]
        file = await photo.get_file()

        # Save the photo temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            await file.download_to_drive(custom_path=tmp.name)

            # Generate caption and AI reply
            caption = await asyncio.to_thread(generate_image_caption, tmp.name)
            ai_reply = await asyncio.to_thread(get_ai_reply, caption)

        # Send reply and button
        sent_msg = await update.message.reply_text(ai_reply)
        translation_cache[str(sent_msg.message_id)] = ai_reply

        keyboard = [[
            InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")
        ]]
        await update.message.reply_text("🌍 Need translation?", reply_markup=InlineKeyboardMarkup(keyboard))

        os.remove(tmp.name)

    except Exception as e:
        print("❌ Image handler error:", e)
        await update.message.reply_text("⚠️ Failed to process the image.")
# === Inline Button Callback Handler ===
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, msg_id = query.data.split("|", 1)
        if action == "translate":
            full_text = translation_cache.get(msg_id)
            if full_text:
                translated = await asyncio.to_thread(translate_to_english, full_text)
                await query.message.reply_text(f"🔁 Translated:\n\n{translated}")
            else:
                await query.message.reply_text("⚠️ Original message not found.")
    except Exception as e:
        print("Button Error:", e)
        await query.message.reply_text("⚠️ Failed to process the button.")

# === Start Command ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to TenaBot!\nSend me a message or an image.")

# === Main App Setup ===
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_image))
app.add_handler(CallbackQueryHandler(handle_button))

print("🚀 TenaBot is live...")

# Pydroid-friendly async loop
loop = asyncio.get_event_loop()
loop.create_task(app.run_polling())
