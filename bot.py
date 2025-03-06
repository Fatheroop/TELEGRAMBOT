import os
import asyncio
import nest_asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Patch the event loop (useful in cloud environments)
nest_asyncio.apply()

# ----- Global Storage (Demo Version) -----
user_sessions = {}  # Session data keyed by chat_id

# These dictionaries will hold channels added via forwarding.
video_channels = {}      # key: channel ID as string, value: channel title
hyperlink_channels = {}  # key: channel ID as string, value: channel title

# For managing bot hyperlinks (shortcuts) if needed.
bot_links = {}  # key: hyperlink string, value: additional info if needed

ADMIN_PASSWORD = "12345"  # initial admin password

# ----- Helper Function -----
async def is_bot_admin(channel_id: str, bot) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, bot.id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False

# ----- Main Menu -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📤 Upload Movie", callback_data="upload")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Main Menu – select an option:", reply_markup=reply_markup)

# ----- Callback Query Handler (Main Menu & Upload Flow) -----
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "upload":
        await query.message.reply_text("Send the movie file you want to upload.",
                                         reply_markup=ReplyKeyboardRemove())
        user_sessions[chat_id] = {"step": "waiting_for_file"}
    elif data.startswith("select_video_"):
        # Data format: "select_video_<channel_id>"
        channel_id = data.replace("select_video_", "")
        user_sessions[chat_id]["video_channel"] = channel_id
        user_sessions[chat_id]["step"] = "waiting_for_prefix"
        await query.message.reply_text("Enter a prefix for the hyperlink message (default: file name):")
    elif data.startswith("select_hyperlink_"):
        # Data format: "select_hyperlink_<channel_id>"
        channel_id = data.replace("select_hyperlink_", "")
        user_sessions[chat_id]["hyperlink_channel"] = channel_id
        await process_upload(chat_id, context)
    elif data == "back_to_main":
        await start(update, context)
    elif data == "back_to_video":
        user_sessions[chat_id]["step"] = "waiting_for_video"
        await present_video_channels(query, context, chat_id)
    else:
        await query.message.reply_text("Unknown option.")

# ----- Present Video Channels (Upload Flow) -----
async def present_video_channels(message_obj, context, chat_id):
    valid = []
    for ch in video_channels.keys():
        if await is_bot_admin(ch, context.bot):
            valid.append(ch)
    if valid:
        keyboard = [[InlineKeyboardButton(video_channels[ch], callback_data=f"select_video_{ch}")]
                    for ch in valid]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message_obj.reply_text("Select the channel to upload your movie to:", reply_markup=reply_markup)
    else:
        await message_obj.reply_text("No valid video channels available.")
        user_sessions.pop(chat_id, None)

# ----- Present Hyperlink Channels (Upload Flow) -----
async def present_hyperlink_channels(message_obj, context, chat_id):
    valid = []
    for ch in hyperlink_channels.keys():
        if await is_bot_admin(ch, context.bot):
            valid.append(ch)
    if valid:
        keyboard = [[InlineKeyboardButton(hyperlink_channels[ch], callback_data=f"select_hyperlink_{ch}")]
                    for ch in valid]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message_obj.reply_text("Select the channel to post movie details to:", reply_markup=reply_markup)
    else:
        await message_obj.reply_text("No valid hyperlink channels available.")
        user_sessions.pop(chat_id, None)

# ----- File Handler -----
async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if session.get("step") != "waiting_for_file":
        return
    file_obj = update.message.document
    if not file_obj and update.message.video:
        file_obj = update.message.video
    if not file_obj:
        await update.message.reply_text("No valid file detected. Please send a video or document.")
        return
    session["file"] = file_obj
    session["step"] = "waiting_for_video"
    await present_video_channels(update.message, context, chat_id)

# ----- Process Text Input -----
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_PASSWORD
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if not session or "step" not in session:
        return
    step = session["step"]

    if step == "waiting_for_prefix":
        prefix = update.message.text.strip()
        # Default to file name if empty and available.
        if not prefix and hasattr(session.get("file"), "file_name"):
            prefix = session.get("file").file_name
        session["prefix"] = prefix
        session["step"] = "waiting_for_hyperlink_channel"
        await present_hyperlink_channels(update.message, context, chat_id)

    # ----- Admin Password for Settings -----
    elif step == "waiting_for_password":
        if update.message.text.strip() == ADMIN_PASSWORD:
            # Show settings menu.
            keyboard = [
                [InlineKeyboardButton("Add Bot Link", callback_data="add_bot_link")],
                [InlineKeyboardButton("Remove Bot Link", callback_data="remove_bot_link")],
                [InlineKeyboardButton("← Back", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
        session["step"] = None

    # ----- Change Password Flow -----
    elif step == "waiting_for_new_password":
        session["new_password"] = update.message.text.strip()
        session["step"] = "waiting_for_password_confirmation"
        await update.message.reply_text("Re-enter new password for confirmation:")
    elif step == "waiting_for_password_confirmation":
        new_pass = session.get("new_password")
        if update.message.text.strip() == new_pass:
            ADMIN_PASSWORD = new_pass
            await update.message.reply_text("Admin password changed successfully!")
        else:
            await update.message.reply_text("Passwords do not match. Password not changed.")
        session["step"] = None

    # ----- Bot Link (Settings) -----
    elif step == "waiting_for_new_bot_link":
        link = update.message.text.strip()
        bot_links[link] = {"link": link}
        await update.message.reply_text(f"Bot link '{link}' added!")
        session["step"] = None
    else:
        await update.message.reply_text("Please use the inline menu options.")

# ----- Process Upload After All Selections -----
async def process_upload(chat_id, context: ContextTypes.DEFAULT_TYPE):
    session = user_sessions.get(chat_id, {})
    if not session:
        return
    file_obj = session.get("file")
    video_ch = session.get("video_channel")
    hyper_ch = session.get("hyperlink_channel")
    prefix = session.get("prefix", "")
    # Automatically create a suffix with file details.
    suffix = "\n"
    if hasattr(file_obj, "file_name"):
        suffix += f"Name: {file_obj.file_name}\n"
    if hasattr(file_obj, "file_size") and file_obj.file_size:
        suffix += f"Size: {file_obj.file_size} bytes\n"
    if hasattr(file_obj, "mime_type"):
        suffix += f"Type: {file_obj.mime_type}\n"
    # Compose final message.
    message_text = prefix + suffix
    # If any bot link is chosen (if you want to add them later), you can append it.
    # For this demo, we assume no extra selection for bot links.
    try:
        await context.bot.copy_message(
            chat_id=video_ch,
            from_chat_id=chat_id,
            message_id=file_obj.message_id
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error posting file: {e}")
        return
    try:
        await context.bot.send_message(chat_id=hyper_ch, text=message_text)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error posting details: {e}")
        return
    await context.bot.send_message(chat_id=chat_id, text="Movie file and details posted successfully!")
    user_sessions.pop(chat_id, None)

# ----- Present Hyperlink Channels -----
async def present_hyperlink_channels(message_obj, context, chat_id):
    valid = []
    for ch in hyperlink_channels.keys():
        if await is_bot_admin(ch, context.bot):
            valid.append(ch)
    if valid:
        keyboard = [[InlineKeyboardButton(hyperlink_channels[ch], callback_data=f"select_hyperlink_{ch}")]
                    for ch in valid]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message_obj.reply_text("Select the channel to post movie details to:", reply_markup=reply_markup)
    else:
        await message_obj.reply_text("No valid hyperlink channels available. Operation cancelled.")
        user_sessions.pop(chat_id, None)

# ----- Settings Callback Handler (for managing Bot Links) -----
async def settings_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "manage_bot_links":
        keyboard = [
            [InlineKeyboardButton("➕ Add Bot Link", callback_data="add_bot_link")],
            [InlineKeyboardButton("➖ Remove Bot Link", callback_data="remove_bot_link")],
            [InlineKeyboardButton("List Bot Links", callback_data="list_bot_links")],
            [InlineKeyboardButton("← Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Bot Links Settings:", reply_markup=reply_markup)
    elif data == "add_bot_link":
        await query.message.reply_text("Enter bot hyperlink (e.g., https://t.me/foxtune_bot):", reply_markup=ReplyKeyboardRemove())
        user_sessions[chat_id] = {"step": "waiting_for_new_bot_link"}
    elif data == "remove_bot_link":
        if bot_links:
            keyboard = [[InlineKeyboardButton(link, callback_data=f"rm_botlink_{link}")]
                        for link in bot_links.keys()]
            keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_settings")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Select a bot link to remove:", reply_markup=reply_markup)
        else:
            await query.message.reply_text("No bot links stored.")
    elif data.startswith("rm_botlink_"):
        link = data.replace("rm_botlink_", "")
        if link in bot_links:
            bot_links.pop(link)
            await query.message.reply_text("Bot link removed successfully!")
        else:
            await query.message.reply_text("Bot link not found!")
    elif data == "list_bot_links":
        if bot_links:
            text = "Bot Links:\n" + "\n".join(bot_links.keys())
            await query.message.reply_text(text)
        else:
            await query.message.reply_text("No bot links stored!")
    elif data == "back_to_settings":
        keyboard = [
            [InlineKeyboardButton("Manage Bot Links", callback_data="manage_bot_links")],
            [InlineKeyboardButton("Change Password", callback_data="change_password")],
            [InlineKeyboardButton("← Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Settings Menu:", reply_markup=reply_markup)
    elif data == "back_to_main":
        await start(update, context)
    elif data == "change_password":
        await query.message.reply_text("Enter new admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_new_password"}
    else:
        await query.message.reply_text("Unknown settings option.")

# ----- Settings Text Handler (for password, bot links, etc.) -----
async def settings_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_PASSWORD
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if not session or "step" not in session:
        return
    step = session["step"]

    if step == "waiting_for_password":
        if update.message.text.strip() == ADMIN_PASSWORD:
            keyboard = [
                [InlineKeyboardButton("Manage Bot Links", callback_data="manage_bot_links")],
                [InlineKeyboardButton("Change Password", callback_data="change_password")],
                [InlineKeyboardButton("← Back", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
        session["step"] = None
    elif step == "waiting_for_new_bot_link":
        link = update.message.text.strip()
        bot_links[link] = {"link": link}
        await update.message.reply_text(f"Bot link '{link}' added!")
        session["step"] = None
    elif step == "waiting_for_new_password":
        session["new_password"] = update.message.text.strip()
        session["step"] = "waiting_for_password_confirmation"
        await update.message.reply_text("Re-enter new password for confirmation:")
    elif step == "waiting_for_password_confirmation":
        new_pass = session.get("new_password")
        if update.message.text.strip() == new_pass:
            ADMIN_PASSWORD = new_pass
            await update.message.reply_text("Admin password changed successfully!")
        else:
            await update.message.reply_text("Passwords do not match. Password not changed.")
        session["step"] = None
    else:
        await update.message.reply_text("Please use the inline menu options.")

# ----- Main Function -----
async def main():
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")
    if not TOKEN or not WEBHOOK_URL:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN or RENDER_WEBHOOK_URL in .env file!")
    
    app = Application.builder().token(TOKEN).build()

    # Register handlers.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(settings_callback_handler, pattern="^(manage_bot_links|add_bot_link|remove_bot_link|list_bot_links|rm_botlink_.*|back_to_settings|back_to_main|change_password)$"))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO, receive_file))
    app.add_handler(MessageHandler(filters.FORWARDED, lambda u, c: settings_text_handler(u, c)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: settings_text_handler(u, c)))

    # Set webhook.
    webhook_endpoint = f"{WEBHOOK_URL}/{TOKEN}"
    await app.bot.set_webhook(webhook_endpoint)

    # Patch event loop close.
    loop = asyncio.get_event_loop()
    loop.close = lambda: None

    await app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        url_path=TOKEN,
        webhook_url=webhook_endpoint
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "already running" in str(e):
            loop = asyncio.get_event_loop()
            loop.create_task(main())
            loop.run_forever()
        else:
            raise
