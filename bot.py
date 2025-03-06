import os
import asyncio
import nest_asyncio
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Patch the event loop (helpful in many cloud environments)
nest_asyncio.apply()

# ----- Global Storage (for Demo Purposes) -----
user_sessions = {}   # Key: chat_id, Value: dict holding state and data

# These dictionaries store channels that are added via forwarding a channel message.
# Keys are channel IDs (as strings), values are channel titles.
video_channels = {}      # For where the actual movie file is uploaded.
hyperlink_channels = {}  # For where the movie details (hyperlink) are posted.

# Bot hyperlinks (if you want to add shortcuts for other bots)
bot_links = {}  # (Not used further in this demo, but can be expanded)

ADMIN_PASSWORD = "12345"  # initial admin password

# ----- Reply Keyboards -----
def main_menu_keyboard():
    return ReplyKeyboardMarkup([["Upload Movie", "Settings"]], resize_keyboard=True, one_time_keyboard=True)

def settings_menu_keyboard():
    return ReplyKeyboardMarkup(
        [["Add Video Channel", "Remove Video Channel"],
         ["Add Hyperlink Channel", "Remove Hyperlink Channel"],
         ["Change Password", "Back to Main"]],
        resize_keyboard=True, one_time_keyboard=True
    )

def back_to_main_keyboard():
    return ReplyKeyboardMarkup([["Back to Main"]], resize_keyboard=True, one_time_keyboard=True)

def channel_removal_keyboard(channels):
    # channels: list of channel titles
    return ReplyKeyboardMarkup([channels + ["Back to Settings"]], resize_keyboard=True, one_time_keyboard=True)

# ----- /start Command Handler -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Main Menu – select an option:", reply_markup=main_menu_keyboard())
    user_sessions[update.message.chat_id] = {"step": "main_menu"}

# ----- File Upload Flow -----
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if session.get("step") != "waiting_for_file":
        return
    # Accept document or video.
    file_obj = update.message.document or update.message.video
    if not file_obj:
        await update.message.reply_text("No valid file detected. Please send a video or document.")
        return
    session["file"] = file_obj
    session["step"] = "waiting_for_video_channel"
    # Present available video channels.
    valid = []
    for ch_id, title in video_channels.items():
        if await is_bot_admin(ch_id, context.bot):
            valid.append(title)
    if valid:
        await update.message.reply_text("Select the video channel (type exactly):",
                                        reply_markup=ReplyKeyboardMarkup([valid + ["Back to Main"]], resize_keyboard=True, one_time_keyboard=True))
    else:
        await update.message.reply_text("No valid video channels available. Operation cancelled.", reply_markup=main_menu_keyboard())
        session["step"] = "main_menu"

# ----- Process Text Input (State Machine) -----
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    session = user_sessions.get(chat_id, {})
    step = session.get("step", "main_menu")

    # ---- Main Menu Options ----
    if step == "main_menu":
        if text.lower() == "upload movie":
            session["step"] = "waiting_for_file"
            await update.message.reply_text("Please send the movie file (video or document):", reply_markup=ReplyKeyboardRemove())
        elif text.lower() == "settings":
            session["step"] = "waiting_for_admin_password"
            await update.message.reply_text("Enter admin password:", reply_markup=ReplyKeyboardRemove())
        else:
            await update.message.reply_text("Invalid option. Please choose from the menu.", reply_markup=main_menu_keyboard())

    # ---- Admin Password for Settings ----
    elif step == "waiting_for_admin_password":
        if text == ADMIN_PASSWORD:
            session["step"] = "admin_menu"
            await update.message.reply_text("Settings Menu:", reply_markup=settings_menu_keyboard())
        else:
            await update.message.reply_text("Incorrect password.", reply_markup=main_menu_keyboard())
            session["step"] = "main_menu"

    # ---- Admin Settings Menu ----
    elif step == "admin_menu":
        if text.lower() == "add video channel":
            session["step"] = "waiting_for_forward_video"
            await update.message.reply_text("Forward a message from the VIDEO channel you want to add.", reply_markup=ReplyKeyboardRemove())
        elif text.lower() == "remove video channel":
            if video_channels:
                session["step"] = "waiting_for_remove_video_channel"
                await update.message.reply_text("Select a video channel to remove (type the exact channel title):",
                                                reply_markup=channel_removal_keyboard(list(video_channels.values())))
            else:
                await update.message.reply_text("No video channels stored.", reply_markup=settings_menu_keyboard())
        elif text.lower() == "add hyperlink channel":
            session["step"] = "waiting_for_forward_hyperlink"
            await update.message.reply_text("Forward a message from the HYPERLINK channel you want to add.", reply_markup=ReplyKeyboardRemove())
        elif text.lower() == "remove hyperlink channel":
            if hyperlink_channels:
                session["step"] = "waiting_for_remove_hyperlink_channel"
                await update.message.reply_text("Select a hyperlink channel to remove (type the exact channel title):",
                                                reply_markup=channel_removal_keyboard(list(hyperlink_channels.values())))
            else:
                await update.message.reply_text("No hyperlink channels stored.", reply_markup=settings_menu_keyboard())
        elif text.lower() == "change password":
            session["step"] = "waiting_for_new_password"
            await update.message.reply_text("Enter new admin password:", reply_markup=ReplyKeyboardRemove())
        elif text.lower() == "back to main":
            session["step"] = "main_menu"
            await update.message.reply_text("Main Menu:", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text("Invalid option. Please choose from the settings menu.", reply_markup=settings_menu_keyboard())

    # ---- Adding Video/Hyperlink Channels via Forwarded Message ----
    elif step == "waiting_for_forward_video" or step == "waiting_for_forward_hyperlink":
        # In this state, admin must forward a channel message.
        await update.message.reply_text("Please forward a message from the channel, not type text.", reply_markup=settings_menu_keyboard())
    # ---- Change Password Flow ----
    elif step == "waiting_for_new_password":
        session["new_password"] = text
        session["step"] = "waiting_for_password_confirmation"
        await update.message.reply_text("Re-enter new password for confirmation:", reply_markup=ReplyKeyboardRemove())
    elif step == "waiting_for_password_confirmation":
        if text == session.get("new_password"):
            ADMIN_PASSWORD = text
            await update.message.reply_text("Admin password changed successfully!", reply_markup=settings_menu_keyboard())
        else:
            await update.message.reply_text("Passwords do not match. Password not changed.", reply_markup=settings_menu_keyboard())
        session["step"] = "admin_menu"

    # ---- Upload Flow: Video Channel Selection ----
    elif step == "waiting_for_video_channel":
        if text.lower() == "back to main":
            session["step"] = "main_menu"
            await update.message.reply_text("Main Menu:", reply_markup=main_menu_keyboard())
        else:
            # Find channel ID by matching title.
            chosen_id = None
            for ch_id, title in video_channels.items():
                if title.lower() == text.lower():
                    chosen_id = ch_id
                    break
            if chosen_id and (await is_bot_admin(chosen_id, context.bot)):
                session["video_channel"] = chosen_id
                session["step"] = "waiting_for_prefix"
                await update.message.reply_text("Enter a prefix for the hyperlink message (default: file name):", reply_markup=ReplyKeyboardRemove())
            else:
                await update.message.reply_text("Channel not recognized or bot is not admin. Please choose again.", reply_markup=main_menu_keyboard())
    # ---- Upload Flow: Prefix Input ----
    elif step == "waiting_for_prefix":
        prefix = text
        if not prefix and hasattr(session.get("file"), "file_name"):
            prefix = session.get("file").file_name
        session["prefix"] = prefix
        session["step"] = "waiting_for_hyperlink_channel"
        await present_hyperlink_channels(update.message, context, chat_id)
    # ---- Upload Flow: Hyperlink Channel Selection ----
    elif step == "waiting_for_hyperlink_channel":
        if text.lower() == "back to main":
            session["step"] = "main_menu"
            await update.message.reply_text("Main Menu:", reply_markup=main_menu_keyboard())
        else:
            chosen_id = None
            for ch_id, title in hyperlink_channels.items():
                if title.lower() == text.lower():
                    chosen_id = ch_id
                    break
            if chosen_id and (await is_bot_admin(chosen_id, context.bot)):
                session["hyperlink_channel"] = chosen_id
                await process_upload(chat_id, context)
            else:
                await update.message.reply_text("Channel not recognized or bot is not admin. Please choose again.", reply_markup=main_menu_keyboard())
    # ---- Removal of Video Channels ----
    elif step == "waiting_for_remove_video_channel":
        # Find channel by title.
        chosen_id = None
        for ch_id, title in video_channels.items():
            if title.lower() == text.lower():
                chosen_id = ch_id
                break
        if chosen_id:
            video_channels.pop(chosen_id)
            await update.message.reply_text(f"Video channel '{text}' removed.", reply_markup=settings_menu_keyboard())
        else:
            await update.message.reply_text("Channel not found.", reply_markup=settings_menu_keyboard())
        session["step"] = "admin_menu"
    # ---- Removal of Hyperlink Channels ----
    elif step == "waiting_for_remove_hyperlink_channel":
        chosen_id = None
        for ch_id, title in hyperlink_channels.items():
            if title.lower() == text.lower():
                chosen_id = ch_id
                break
        if chosen_id:
            hyperlink_channels.pop(chosen_id)
            await update.message.reply_text(f"Hyperlink channel '{text}' removed.", reply_markup=settings_menu_keyboard())
        else:
            await update.message.reply_text("Channel not found.", reply_markup=settings_menu_keyboard())
        session["step"] = "admin_menu"
    else:
        await update.message.reply_text("Please use the provided menu options.", reply_markup=main_menu_keyboard())

# ----- Forwarded Message Handler (for Adding Channels) -----
async def forwarded_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    step = session.get("step")
    fwd = update.message.forward_from_chat
    if step == "waiting_for_forward_video":
        if fwd and fwd.type == "channel":
            channel_id = str(fwd.id)
            video_channels[channel_id] = fwd.title or channel_id
            await update.message.reply_text(f"Video channel '{video_channels[channel_id]}' added!", reply_markup=settings_menu_keyboard())
        else:
            await update.message.reply_text("Forward a valid channel message.", reply_markup=settings_menu_keyboard())
        session["step"] = "admin_menu"
    elif step == "waiting_for_forward_hyperlink":
        if fwd and fwd.type == "channel":
            channel_id = str(fwd.id)
            hyperlink_channels[channel_id] = fwd.title or channel_id
            await update.message.reply_text(f"Hyperlink channel '{hyperlink_channels[channel_id]}' added!", reply_markup=settings_menu_keyboard())
        else:
            await update.message.reply_text("Forward a valid channel message.", reply_markup=settings_menu_keyboard())
        session["step"] = "admin_menu"

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
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO, handle_file))
    app.add_handler(MessageHandler(filters.FORWARDED, forwarded_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

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
