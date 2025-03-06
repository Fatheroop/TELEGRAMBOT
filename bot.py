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

# ----- Global Storage -----
user_sessions = {}  # Stores session data by chat_id

# Managed channels (these are your Telegram channels where the bot is admin)
# Keys are channel IDs (or unique identifiers); values are channel titles.
video_channels = {}      # For uploading the actual movie file
hyperlink_channels = {}  # For posting movie details (hyperlinks, size, etc.)

# Managed bot hyperlinks (shortcuts). Keys are the bot link strings.
bot_links = {}

ADMIN_PASSWORD = "12345"  # Initial admin password

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
        [InlineKeyboardButton("📤 Upload Movie", callback_data="upload")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Main Menu – select an option:", reply_markup=reply_markup)

# ----- Callback Query Handler for Main Menu & Upload Flow -----
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # ---- Upload Flow ----
    if data == "upload":
        await query.message.reply_text("Send the video/movie file you want to upload.",
                                         reply_markup=ReplyKeyboardRemove())
        user_sessions[chat_id] = {"step": "waiting_for_file"}
    # ---- Settings Flow ----
    elif data == "settings":
        await query.message.reply_text("Enter admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_password"}
    # ---- In Upload Flow: Select Video Channel ----
    elif data.startswith("select_video_"):
        # Data format: "select_video_<channel_id>"
        channel_id = data.replace("select_video_", "")
        user_sessions[chat_id]["video_channel"] = channel_id
        user_sessions[chat_id]["step"] = "waiting_for_hyperlink"
        # Now show hyperlink channels (only where bot is admin)
        valid = []
        for ch in hyperlink_channels.keys():
            if await is_bot_admin(ch, context.bot):
                valid.append(ch)
        if valid:
            keyboard = [[InlineKeyboardButton(ch, callback_data=f"select_hyperlink_{ch}")]
                        for ch in valid]
            keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_video")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Select the channel for posting movie details:", reply_markup=reply_markup)
        else:
            await query.message.reply_text("No valid hyperlink channels available. Operation cancelled.")
            user_sessions.pop(chat_id, None)
    elif data.startswith("select_hyperlink_"):
        channel_id = data.replace("select_hyperlink_", "")
        user_sessions[chat_id]["hyperlink_channel"] = channel_id
        # Perform posting: forward file to video channel and post details to hyperlink channel.
        session = user_sessions[chat_id]
        file_obj = session.get("file")
        video_ch = session.get("video_channel")
        hyper_ch = session.get("hyperlink_channel")
        if file_obj and video_ch and hyper_ch:
            try:
                await context.bot.copy_message(
                    chat_id=video_ch,
                    from_chat_id=chat_id,
                    message_id=file_obj.message_id
                )
            except Exception as e:
                await query.message.reply_text(f"Error posting file to video channel: {e}")
                return
            details = "Movie Details:\n"
            if hasattr(file_obj, "file_name"):
                details += f"Name: {file_obj.file_name}\n"
            if hasattr(file_obj, "file_size") and file_obj.file_size:
                details += f"Size: {file_obj.file_size} bytes\n"
            if hasattr(file_obj, "mime_type"):
                details += f"Type: {file_obj.mime_type}\n"
            try:
                await context.bot.send_message(chat_id=hyper_ch, text=details)
            except Exception as e:
                await query.message.reply_text(f"Error posting details to hyperlink channel: {e}")
                return
            await query.message.reply_text("Movie file and details posted successfully!")
        else:
            await query.message.reply_text("Session data incomplete. Operation cancelled.")
        user_sessions.pop(chat_id, None)
    # ---- Back Buttons ----
    elif data == "back_to_main":
        await start(update, context)
    elif data == "back_to_video":
        user_sessions[chat_id]["step"] = "waiting_for_video"
        await present_video_channels(query, context, chat_id)
    else:
        await query.message.reply_text("Unknown option.")

# ----- Helper: Present Video Channels (Upload Flow) -----
async def present_video_channels(query, context, chat_id):
    valid = []
    for ch in video_channels.keys():
        if await is_bot_admin(ch, context.bot):
            valid.append(ch)
    if valid:
        keyboard = [[InlineKeyboardButton(ch, callback_data=f"select_video_{ch}")]
                    for ch in valid]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Select the channel to upload your movie file to:", reply_markup=reply_markup)
    else:
        await query.message.reply_text("No valid video channels available. Operation cancelled.")
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

# ----- Settings Text Handler (for admin actions) -----
async def settings_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_PASSWORD
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if not session or "step" not in session:
        return
    step = session["step"]

    if step == "waiting_for_password":
        if update.message.text.strip() == ADMIN_PASSWORD:
            # Show settings menu (all via inline keyboard)
            keyboard = [
                [InlineKeyboardButton("Manage Video Channels", callback_data="manage_video_channels")],
                [InlineKeyboardButton("Manage Hyperlink Channels", callback_data="manage_hyperlink_channels")],
                [InlineKeyboardButton("Manage Bot Links", callback_data="manage_bot_links")],
                [InlineKeyboardButton("Change Password", callback_data="change_password")],
                [InlineKeyboardButton("← Back", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
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

    # For other steps (like channel additions) we expect forwarded messages
    else:
        await update.message.reply_text("Please use the provided inline menu options.")

# ----- Settings Callback Handler for Managing Channels and Bot Links -----
async def settings_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "manage_video_channels":
        keyboard = [
            [InlineKeyboardButton("➕ Add Video Channel", callback_data="add_video_channel")],
            [InlineKeyboardButton("➖ Remove Video Channel", callback_data="remove_video_channel")],
            [InlineKeyboardButton("← Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Video Channels Menu:", reply_markup=reply_markup)
    elif data == "manage_hyperlink_channels":
        keyboard = [
            [InlineKeyboardButton("➕ Add Hyperlink Channel", callback_data="add_hyperlink_channel")],
            [InlineKeyboardButton("➖ Remove Hyperlink Channel", callback_data="remove_hyperlink_channel")],
            [InlineKeyboardButton("← Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Hyperlink Channels Menu:", reply_markup=reply_markup)
    elif data == "manage_bot_links":
        keyboard = [
            [InlineKeyboardButton("➕ Add Bot Link", callback_data="add_bot_link")],
            [InlineKeyboardButton("➖ Remove Bot Link", callback_data="remove_bot_link")],
            [InlineKeyboardButton("List Bot Links", callback_data="list_bot_links")],
            [InlineKeyboardButton("← Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Bot Links Menu:", reply_markup=reply_markup)
    elif data == "change_password":
        await query.message.reply_text("Enter new admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_new_password"}
    elif data == "back_to_main":
        await start(update, context)
    # ----- Settings sub-menu actions -----
    elif data == "add_video_channel":
        await query.message.reply_text("Forward a message from the video channel to add it.",
                                         reply_markup=ReplyKeyboardRemove())
        user_sessions[chat_id] = {"step": "waiting_for_forward_video"}
    elif data == "remove_video_channel":
        if video_channels:
            keyboard = [[InlineKeyboardButton(video_channels[ch], callback_data=f"rm_video_{ch}")]
                        for ch in video_channels.keys()]
            keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_settings")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Select a video channel to remove:", reply_markup=reply_markup)
        else:
            await query.message.reply_text("No video channels stored.")
    elif data == "add_hyperlink_channel":
        await query.message.reply_text("Forward a message from the hyperlink channel to add it.",
                                         reply_markup=ReplyKeyboardRemove())
        user_sessions[chat_id] = {"step": "waiting_for_forward_hyperlink"}
    elif data == "remove_hyperlink_channel":
        if hyperlink_channels:
            keyboard = [[InlineKeyboardButton(hyperlink_channels[ch], callback_data=f"rm_hyper_{ch}")]
                        for ch in hyperlink_channels.keys()]
            keyboard.append([InlineKeyboardButton("← Back", callback_data="back_to_settings")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Select a hyperlink channel to remove:", reply_markup=reply_markup)
        else:
            await query.message.reply_text("No hyperlink channels stored.")
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
    elif data.startswith("rm_video_"):
        ch = data.replace("rm_video_", "")
        if ch in video_channels:
            video_channels.pop(ch)
            await query.message.reply_text("Video channel removed successfully!")
        else:
            await query.message.reply_text("Channel not found!")
    elif data.startswith("rm_hyper_"):
        ch = data.replace("rm_hyper_", "")
        if ch in hyperlink_channels:
            hyperlink_channels.pop(ch)
            await query.message.reply_text("Hyperlink channel removed successfully!")
        else:
            await query.message.reply_text("Channel not found!")
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
            [InlineKeyboardButton("Manage Video Channels", callback_data="manage_video_channels")],
            [InlineKeyboardButton("Manage Hyperlink Channels", callback_data="manage_hyperlink_channels")],
            [InlineKeyboardButton("Manage Bot Links", callback_data="manage_bot_links")],
            [InlineKeyboardButton("Change Password", callback_data="change_password")],
            [InlineKeyboardButton("← Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Settings Menu:", reply_markup=reply_markup)
    else:
        await query.message.reply_text("Unknown settings option.")

# ----- Handler for Forwarded Messages (Adding Channels) -----
async def handle_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    step = session.get("step")
    if step == "waiting_for_forward_video":
        fwd = update.message.forward_from_chat
        if fwd and fwd.type == "channel":
            channel_id = str(fwd.id)
            video_channels[channel_id] = fwd.title or channel_id
            await update.message.reply_text(f"Video channel '{video_channels[channel_id]}' added!")
        else:
            await update.message.reply_text("Forward a valid channel message.")
        session["step"] = None
    elif step == "waiting_for_forward_hyperlink":
        fwd = update.message.forward_from_chat
        if fwd and fwd.type == "channel":
            channel_id = str(fwd.id)
            hyperlink_channels[channel_id] = fwd.title or channel_id
            await update.message.reply_text(f"Hyperlink channel '{hyperlink_channels[channel_id]}' added!")
        else:
            await update.message.reply_text("Forward a valid channel message.")
        session["step"] = None

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
    app.add_handler(CallbackQueryHandler(settings_callback_handler, pattern="^(manage_video_channels|manage_hyperlink_channels|manage_bot_links|change_password|back_to_main|back_to_settings|add_video_channel|remove_video_channel|add_hyperlink_channel|remove_hyperlink_channel|add_bot_link|remove_bot_link|list_bot_links|rm_video_.*|rm_hyper_.*|rm_botlink_.*)$"))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO, receive_file))
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forwarded))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, settings_text_handler))

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
