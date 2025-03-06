import os
import asyncio
import nest_asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Patch event loop (useful for cloud environments)
nest_asyncio.apply()

# ----- Global Data Storage -----
user_sessions = {}  # session data keyed by chat_id

# Dictionaries to store channels (keys are channel usernames, e.g. "@moviesvideo")
video_channels = {}      # channels where the actual video will be posted
hyperlink_channels = {}  # channels where the movie details/hyperlinks will be posted

# Dictionary for storing bot hyperlinks (shortcuts to other bots)
bot_links = {}  # key: bot hyperlink (e.g. "https://t.me/foxtune_bot"), value: info (if any)

ADMIN_PASSWORD = "12345"  # initial admin password

# ----- Utility Function -----
async def is_bot_admin(channel: str, bot) -> bool:
    try:
        member = await bot.get_chat_member(channel, bot.id)
        if member.status in ["administrator", "creator"]:
            return True
    except Exception:
        pass
    return False

# ----- Main Menu Command Handler -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📤 Upload File", callback_data="upload")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("✉️ Send to Channel", callback_data="send_file")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Main Menu – select an option:", reply_markup=reply_markup)

# ----- CallbackQuery Handler -----
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # File upload flow:
    if data == "upload":
        await query.message.reply_text("Send the video/movie file you want to upload.")
        user_sessions[chat_id] = {"step": "waiting_for_file"}
    # Settings flow:
    elif data == "settings":
        await query.message.reply_text("Enter admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_password"}
    # Send file flow:
    elif data == "send_file":
        await query.message.reply_text("Enter the channel (from your stored video channels) to send a test call message:")
        user_sessions[chat_id] = {"step": "waiting_for_send_channel"}
    # ----- Settings Options -----
    elif data == "add_video_channel":
        await query.message.reply_text("Enter video channel username (e.g., @moviesvideo):")
        user_sessions[chat_id] = {"step": "waiting_for_new_video_channel"}
    elif data == "remove_video_channel":
        await query.message.reply_text("Enter video channel username to remove:")
        user_sessions[chat_id] = {"step": "waiting_for_remove_video_channel"}
    elif data == "add_hyperlink_channel":
        await query.message.reply_text("Enter hyperlink channel username (e.g., @movieslinks):")
        user_sessions[chat_id] = {"step": "waiting_for_new_hyperlink_channel"}
    elif data == "remove_hyperlink_channel":
        await query.message.reply_text("Enter hyperlink channel username to remove:")
        user_sessions[chat_id] = {"step": "waiting_for_remove_hyperlink_channel"}
    elif data == "list_bot_links":
        if bot_links:
            text = "Integrated Bot Links:\n" + "\n".join(bot_links.keys())
            await query.message.reply_text(text)
        else:
            await query.message.reply_text("No bot links added yet.")
    elif data == "change_password":
        await query.message.reply_text("Enter new admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_new_password"}
    # ----- Channel selection for file upload -----
    elif data.startswith("select_video_channel_"):
        # Data format: "select_video_channel_<channel>"
        channel = data.replace("select_video_channel_", "")
        if chat_id in user_sessions:
            user_sessions[chat_id]["video_channel"] = channel
            user_sessions[chat_id]["step"] = "waiting_for_hyperlink_channel"
            # Now show hyperlink channels list (only those where bot is admin)
            valid_hyper_channels = []
            for ch in hyperlink_channels.keys():
                if await is_bot_admin(ch, context.bot):
                    valid_hyper_channels.append(ch)
            if valid_hyper_channels:
                keyboard = [[InlineKeyboardButton(ch, callback_data=f"select_hyperlink_channel_{ch}")]
                            for ch in valid_hyper_channels]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("Select the channel to post the movie hyperlink:", reply_markup=reply_markup)
            else:
                await query.message.reply_text("No valid hyperlink channels available.")
    elif data.startswith("select_hyperlink_channel_"):
        channel = data.replace("select_hyperlink_channel_", "")
        if chat_id in user_sessions:
            user_sessions[chat_id]["hyperlink_channel"] = channel
            # Now perform posting actions.
            session = user_sessions[chat_id]
            file_obj = session.get("file")
            video_channel = session.get("video_channel")
            hyperlink_channel = session.get("hyperlink_channel")
            if file_obj and video_channel and hyperlink_channel:
                try:
                    # Forward the file to the video channel.
                    await context.bot.copy_message(
                        chat_id=video_channel,
                        from_chat_id=chat_id,
                        message_id=file_obj.message_id
                    )
                except Exception as e:
                    await query.message.reply_text(f"Error posting file to {video_channel}: {e}")
                    return
                # Prepare file details.
                details = "Movie Details:\n"
                if hasattr(file_obj, "file_name"):
                    details += f"Name: {file_obj.file_name}\n"
                if hasattr(file_obj, "file_size") and file_obj.file_size:
                    details += f"Size: {file_obj.file_size} bytes\n"
                if hasattr(file_obj, "mime_type"):
                    details += f"Type: {file_obj.mime_type}\n"
                try:
                    await context.bot.send_message(chat_id=hyperlink_channel, text=details)
                except Exception as e:
                    await query.message.reply_text(f"Error posting details to {hyperlink_channel}: {e}")
                    return
                await query.message.reply_text("File and hyperlink posted successfully!")
                user_sessions.pop(chat_id)
            else:
                await query.message.reply_text("Session incomplete. Please try again.")
    else:
        await query.message.reply_text("Unknown option.")

# ----- File Upload Flow -----

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
    session["step"] = "waiting_for_video_channel"
    session["file"] = file_obj
    # Build inline keyboard from video_channels where bot is admin.
    valid_video_channels = []
    for ch in video_channels.keys():
        if await is_bot_admin(ch, context.bot):
            valid_video_channels.append(ch)
    if valid_video_channels:
        keyboard = [[InlineKeyboardButton(ch, callback_data=f"select_video_channel_{ch}")]
                    for ch in valid_video_channels]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select the channel to upload your video to:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("No valid video channels available. Please add one in settings.")

# ----- Settings Text Handler -----

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_PASSWORD
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if not session or "step" not in session:
        return
    step = session["step"]

    # --- Verify admin password ---
    if step == "waiting_for_password":
        if update.message.text.strip() == ADMIN_PASSWORD:
            keyboard = [
                [InlineKeyboardButton("Add Video Channel", callback_data="add_video_channel")],
                [InlineKeyboardButton("Remove Video Channel", callback_data="remove_video_channel")],
                [InlineKeyboardButton("Add Hyperlink Channel", callback_data="add_hyperlink_channel")],
                [InlineKeyboardButton("Remove Hyperlink Channel", callback_data="remove_hyperlink_channel")],
                [InlineKeyboardButton("List Bot Links", callback_data="list_bot_links")],
                [InlineKeyboardButton("Change Password", callback_data="change_password")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
        session["step"] = None

    # --- Change Password Flow ---
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

    # --- Manage Video Channels: Add/Remove ---
    elif step == "waiting_for_new_video_channel":
        channel = update.message.text.strip()
        video_channels[channel] = f"Info for {channel}"
        await update.message.reply_text(f"Video channel '{channel}' added successfully!")
        session["step"] = None
    elif step == "waiting_for_remove_video_channel":
        channel = update.message.text.strip()
        if channel in video_channels:
            video_channels.pop(channel)
            await update.message.reply_text(f"Video channel '{channel}' removed successfully!")
        else:
            await update.message.reply_text("Video channel not found!")
        session["step"] = None

    # --- Manage Hyperlink Channels: Add/Remove ---
    elif step == "waiting_for_new_hyperlink_channel":
        channel = update.message.text.strip()
        hyperlink_channels[channel] = f"Info for {channel}"
        await update.message.reply_text(f"Hyperlink channel '{channel}' added successfully!")
        session["step"] = None
    elif step == "waiting_for_remove_hyperlink_channel":
        channel = update.message.text.strip()
        if channel in hyperlink_channels:
            hyperlink_channels.pop(channel)
            await update.message.reply_text(f"Hyperlink channel '{channel}' removed successfully!")
        else:
            await update.message.reply_text("Hyperlink channel not found!")
        session["step"] = None

    # --- Send to Channel Demo ---
    elif step == "waiting_for_send_channel":
        channel = update.message.text.strip()
        # Check if channel exists in video_channels and bot is admin.
        if channel in video_channels and await is_bot_admin(channel, context.bot):
            try:
                await context.bot.send_message(chat_id=channel, text="Test call message from bot!")
                await update.message.reply_text(f"Message sent to {channel}.")
            except Exception as e:
                await update.message.reply_text(f"Error sending message to {channel}: {e}")
        else:
            await update.message.reply_text("Channel not found or bot is not admin there.")
        session["step"] = None

    # --- If no known step ---
    else:
        await update.message.reply_text("Command not recognized in this context.")

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
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO, receive_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

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
