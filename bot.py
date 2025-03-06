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

# Patch the event loop (useful in many cloud environments)
nest_asyncio.apply()

# ----- Global Data Storage (Demo Version) -----
user_sessions = {}  # Stores session data by chat_id

# Bot hyperlinks (shortcuts) managed via settings
bot_links = {}  # key: hyperlink string (e.g. "https://t.me/foxtune_bot")

ADMIN_PASSWORD = "12345"  # initial admin password

# ----- Candidate Channels from Environment Variables -----
# These are comma-separated values; no management via the bot.
# They must be channel usernames (or IDs) where your bot is admin.
VIDEO_CHANNELS = []
HYPERLINK_CHANNELS = []

def load_candidate_channels():
    global VIDEO_CHANNELS, HYPERLINK_CHANNELS
    video = os.getenv("VIDEO_CHANNELS", "")
    hyper = os.getenv("HYPERLINK_CHANNELS", "")
    VIDEO_CHANNELS = [x.strip() for x in video.split(",") if x.strip()]
    HYPERLINK_CHANNELS = [x.strip() for x in hyper.split(",") if x.strip()]

# ----- Helper Function -----
async def is_bot_admin(channel: str, bot) -> bool:
    try:
        member = await bot.get_chat_member(channel, bot.id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False

# ----- Main Menu -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📤 Upload File", callback_data="upload")],
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

    # ----- Upload Flow -----
    if data == "upload":
        await query.message.reply_text("Send the file you want to upload.", reply_markup=ReplyKeyboardRemove())
        user_sessions[chat_id] = {"step": "waiting_for_file"}
    # ----- Video Channel Selection -----
    elif data.startswith("select_video_"):
        # data: "select_video_<channel>"
        channel = data.replace("select_video_", "")
        user_sessions[chat_id]["video_channel"] = channel
        user_sessions[chat_id]["step"] = "waiting_for_prefix"
        await query.message.reply_text("Enter a prefix for the hyperlink message (default is file name):")
    # ----- Bot Link Selection (Optional) -----
    elif data.startswith("choose_botlink_"):
        # data: "choose_botlink_<link>" OR "skip_botlink"
        if data == "skip_botlink":
            user_sessions[chat_id]["bot_link"] = ""
        else:
            link = data.replace("choose_botlink_", "")
            user_sessions[chat_id]["bot_link"] = link
        user_sessions[chat_id]["step"] = "waiting_for_hyperlink_channel"
        await present_hyperlink_channels(query, context, chat_id)
    # ----- Hyperlink Channel Selection -----
    elif data.startswith("select_hyperlink_"):
        channel = data.replace("select_hyperlink_", "")
        user_sessions[chat_id]["hyperlink_channel"] = channel
        # Now compose and post the messages.
        await process_upload(chat_id, context)
    elif data == "back_to_main":
        await start(update, context)
    else:
        await query.message.reply_text("Unknown option.")

# ----- Present Video Channels from Candidate List (Filtered by Admin) -----
async def present_video_channels(message_obj, context, chat_id):
    valid = []
    for ch in VIDEO_CHANNELS:
        if await is_bot_admin(ch, context.bot):
            valid.append(ch)
    if valid:
        keyboard = [[InlineKeyboardButton(ch, callback_data=f"select_video_{ch}")]
                    for ch in valid]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message_obj.reply_text("Select the channel to upload the file to:", reply_markup=reply_markup)
    else:
        await message_obj.reply_text("No valid video channels available. Operation cancelled.")
        user_sessions.pop(chat_id, None)

# ----- Present Hyperlink Channels from Candidate List (Filtered by Admin) -----
async def present_hyperlink_channels(message_obj, context, chat_id):
    valid = []
    for ch in HYPERLINK_CHANNELS:
        if await is_bot_admin(ch, context.bot):
            valid.append(ch)
    if valid:
        keyboard = [[InlineKeyboardButton(ch, callback_data=f"select_hyperlink_{ch}")]
                    for ch in valid]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message_obj.reply_text("Select the channel to post the hyperlink message to:", reply_markup=reply_markup)
    else:
        await message_obj.reply_text("No valid hyperlink channels available. Operation cancelled.")
        user_sessions.pop(chat_id, None)

# ----- File Handler: When a File Is Received -----
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

# ----- Process Text Input Steps -----
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_PASSWORD
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if not session or "step" not in session:
        return
    step = session["step"]

    # --- Step: Enter Admin Password (Settings) ---
    if step == "waiting_for_password":
        if update.message.text.strip() == ADMIN_PASSWORD:
            # Show settings menu for managing bot hyperlinks only.
            keyboard = [
                [InlineKeyboardButton("Add Bot Link", callback_data="add_bot_link")],
                [InlineKeyboardButton("Remove Bot Link", callback_data="remove_bot_link")],
                [InlineKeyboardButton("List Bot Links", callback_data="list_bot_links")],
                [InlineKeyboardButton("← Back", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
        session["step"] = None

    # --- Step: Enter Prefix for Hyperlink Message ---
    elif step == "waiting_for_prefix":
        prefix = update.message.text.strip()
        # If empty, default to file name if available.
        if not prefix and hasattr(session.get("file"), "file_name"):
            prefix = session.get("file").file_name
        session["prefix"] = prefix
        # If there are bot links, ask whether to append one.
        if bot_links:
            keyboard = []
            for link in bot_links.keys():
                keyboard.append([InlineKeyboardButton(link, callback_data=f"choose_botlink_{link}")])
            keyboard.append([InlineKeyboardButton("Skip", callback_data="choose_botlink_skip")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            session["step"] = "waiting_for_botlink_selection"
            await update.message.reply_text("Select a bot link to append (or choose Skip):", reply_markup=reply_markup)
        else:
            # No bot links, move on.
            session["bot_link"] = ""
            session["step"] = "waiting_for_hyperlink_channel"
            await present_hyperlink_channels(update.message, context, chat_id)

    # --- Settings: Adding/Removing Bot Links ---
    elif step == "waiting_for_new_bot_link":
        link = update.message.text.strip()
        # Optionally, add validation for URL.
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
        await update.message.reply_text("Please use the provided inline menu options.")

# ----- Process the Upload Once All Selections Are Made -----
async def process_upload(chat_id, context: ContextTypes.DEFAULT_TYPE):
    session = user_sessions.get(chat_id, {})
    if not session:
        return
    file_obj = session.get("file")
    video_ch = session.get("video_channel")
    hyper_ch = session.get("hyperlink_channel")
    prefix = session.get("prefix", "")
    bot_link = session.get("bot_link", "")
    # Automatically generate suffix with file details.
    suffix = "\n"
    if hasattr(file_obj, "file_name"):
        suffix += f"File: {file_obj.file_name}\n"
    if hasattr(file_obj, "file_size") and file_obj.file_size:
        suffix += f"Size: {file_obj.file_size} bytes\n"
    if hasattr(file_obj, "mime_type"):
        suffix += f"Type: {file_obj.mime_type}\n"
    # Compose final message.
    message_text = prefix + suffix
    if bot_link:
        message_text += f"\nLink: {bot_link}"
    # Post file to video channel.
    try:
        await context.bot.copy_message(
            chat_id=video_ch,
            from_chat_id=chat_id,
            message_id=file_obj.message_id
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error posting file: {e}")
        return
    # Post hyperlink message to hyperlink channel.
    try:
        await context.bot.send_message(chat_id=hyper_ch, text=message_text)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error posting details: {e}")
        return
    await context.bot.send_message(chat_id=chat_id, text="Upload and hyperlink created successfully!")
    user_sessions.pop(chat_id, None)

# ----- Present Hyperlink Channels (Upload Flow) -----
async def present_hyperlink_channels(message_obj, context, chat_id):
    valid = []
    for ch in HYPERLINK_CHANNELS:
        if await is_bot_admin(ch, context.bot):
            valid.append(ch)
    if valid:
        keyboard = [[InlineKeyboardButton(ch, callback_data=f"select_hyperlink_{ch}")]
                    for ch in valid]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message_obj.reply_text("Select the channel to post the hyperlink message to:", reply_markup=reply_markup)
    else:
        await message_obj.reply_text("No valid hyperlink channels available. Operation cancelled.")
        user_sessions.pop(chat_id, None)

# ----- SETTINGS: Callback Handler for Managing Bot Links Only -----
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
        await query.message.reply_text("Enter bot hyperlink (e.g., https://t.me/foxtune_bot):",
                                         reply_markup=ReplyKeyboardRemove())
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
    elif data == "change_password":
        await query.message.reply_text("Enter new admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_new_password"}
    elif data == "back_to_main":
        await start(update, context)
    else:
        await query.message.reply_text("Unknown settings option.")

# ----- TEXT HANDLER for Settings (password, bot links, etc.) -----
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
        await update.message.reply_text(f"Bot link '{link}' added successfully!")
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
    load_candidate_channels()
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
