# ===== SUBJECT BUTTONS KEYBOARD =====
def subject_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Math", callback_data="subject|Math"),
            InlineKeyboardButton("Physics", callback_data="subject|Physics"),
            InlineKeyboardButton("Chemistry", callback_data="subject|Chemistry"),
        ]
    ])

# ===== START HANDLER =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text(
        "👋 Welcome! Choose a subject first:", 
        reply_markup=subject_keyboard()
    )

# ===== MODIFY TEXT HANDLER =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    subject = context.user_data.get("subject")
    if not subject:
        await update.message.reply_text(
            "⚠️ Please select a subject first:", 
            reply_markup=subject_keyboard()
        )
        return

    prompt = f"[Subject: {subject}] {update.message.text}"
    await update.message.chat.send_action(action=ChatAction.TYPING)

    reply_en, reply_am = await asyncio.to_thread(get_ai_reply, prompt)
    sent_msg = await update.message.reply_text(reply_am)

    translation_cache[str(sent_msg.message_id)] = {"am": reply_am, "en": reply_en, "current": "am"}

    # Add persistent buttons: Translate + Change Subject
    keyboard = [
        [InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")],
        [InlineKeyboardButton("🔄 Change Subject", callback_data="change_subject")]
    ]
    await update.message.reply_text("Options:", reply_markup=InlineKeyboardMarkup(keyboard))

# ===== MODIFY PHOTO HANDLER =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    subject = context.user_data.get("subject")
    if not subject:
        await update.message.reply_text(
            "⚠️ Please select a subject first:", 
            reply_markup=subject_keyboard()
        )
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

            prompt = f"[Subject: {subject}] Extracted question:\n{text}"
            reply_en, reply_am = await asyncio.to_thread(get_ai_reply, prompt)

        sent_msg = await update.message.reply_text(reply_am)
        translation_cache[str(sent_msg.message_id)] = {"am": reply_am, "en": reply_en, "current": "am"}

        # Persistent buttons: Translate + Change Subject
        keyboard = [
            [InlineKeyboardButton("🌐 Translate to English", callback_data=f"translate|{sent_msg.message_id}")],
            [InlineKeyboardButton("🔄 Change Subject", callback_data="change_subject")]
        ]
        await update.message.reply_text("Options:", reply_markup=InlineKeyboardMarkup(keyboard))
        os.remove(tmp.name)

    except Exception as e:
        logging.error("Photo handler error: %s", e)
        await update.message.reply_text("⚠️ Image processing failed.")

# ===== MODIFY BUTTON CALLBACK =====
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if query.data == "change_subject":
            await query.message.reply_text("Select a new subject:", reply_markup=subject_keyboard())
            return

        action, data = query.data.split("|", 1)

        if action == "translate":
            msg_id = data
            data = translation_cache.get(msg_id)
            if not data:
                await query.message.reply_text("⚠️ Message not found.")
                return

            if data["current"] == "am":
                await query.message.reply_text(f"🔁 English:\n\n{data['en']}")
                data["current"] = "en"
            else:
                await query.message.reply_text(f"🔁 አማርኛ:\n\n{data['am']}")
                data["current"] = "am"

        elif action == "subject":
            await handle_subject(update, context)
        elif action == "task":
            await handle_task(update, context)

    except Exception as e:
        logging.error("Button Error: %s", e)
        await query.message.reply_text("⚠️ Button failed.")
