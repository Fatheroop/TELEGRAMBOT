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

# Patch the event loop (useful in cloud environments)
nest_asyncio.apply()

# ----- Global Storage (Demo Version) -----
# Stores session data keyed by chat_id
user_sessions = {}

# These dictionaries will be populated by forwarding messages from your channels.
# They store channels where the bot is admin.
# Key: channel unique ID (as a string), Value: channel title.
video_channels = {}      # For uploading the actual movie file
hyperlink_channels = {}  # For posting movie details (hyperlinks)

# For managing bot hyperlinks (shortcuts)
bot_links = {}  # Key: bot hyperlink string, Value: additional info (if any)

ADMIN_PASSWORD = "12345"  # Initial admin password

# ----- Helper Function: Check if bot is admin in a channel -----
async def is_bot_admin(channel_id: str, bot) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, bot.id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False

# ----- Reply Keyboards -----
def main_menu_keyboard():
    return ReplyKeyboardMarkup([["Upload Movie", "Settings"]], resize_keyboard=True, one_time_keyboard=True)

def back_to_main_keyboard():
    return ReplyKeyboardMarkup([["Back to Main"]], resize_keyboard=True, one_time_keyboard=True)

# ----- /start Command Handler -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Main Menu – select an option:", reply_markup=main_menu_keyboard())
    user_sessions[update.message.chat_id] = {"step": "main_menu"}

# ----- File Upload Flow -----
async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if session.get("step") != "waiting_for_file":
        return
    file_obj = update.message.document or update.message.video
    if not file_obj:
        await update.message.reply_text("No valid file. Please send a video or document.")
        return
    session["file"] = file_obj
    session["step"] = "waiting_for_video_channel"
    # Present video channels using reply keyboard:
    valid = []
    for ch_id, title in video_channels.items():
        if await is_bot_admin(ch_id, context.bot):
            valid.append(title)
    if valid:
        keyboard = [valid + ["Back to Main"]]
        await update.message.reply_text("Select the video channel (type the exact channel name):",
                                        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    else:
        await update.message.reply_text("No valid video channels available.", reply_markup=main_menu_keyboard())
        session["step"] = "main_menu"

# ----- Present Hyperlink Channels (Upload Flow) -----
async def present_hyperlink_channels(update_obj, context, chat_id):
    valid = []
    for ch_id, title in hyperlink_channels.items():
        if await is_bot_admin(ch_id, context.bot):
            valid.append(title)
    if valid:
        keyboard = [valid + ["Back to Main"]]
        await update_obj.reply_text("Select the hyperlink channel (type the exact channel name):",
                                     reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    else:
        await update_obj.reply_text("No valid hyperlink channels available.", reply_markup=main_menu_keyboard())
        user_sessions.pop(chat_id, None)

# ----- Process Upload: Forward File & Send Details -----
async def process_upload(chat_id, context: ContextTypes.DEFAULT_TYPE):
    session = user_sessions.get(chat_id, {})
    if not session:
        return
    file_obj = session.get("file")
    video_ch = session.get("video_channel")  # This is the channel ID (string)
    hyper_ch = session.get("hyperlink_channel")  # Channel ID for hyperlink message
    prefix = session.get("prefix", "")
    # Automatically generate file details:
    suffix = "\n"
    if hasattr(file_obj, "file_name"):
        suffix += f"Name: {file_obj.file_name}\n"
    if hasattr(file_obj, "file_size") and file_obj.file_size:
        suffix += f"Size: {file_obj.file_size} bytes\n"
    if hasattr(file_obj, "mime_type"):
        suffix += f"Type: {file_obj.mime_type}\n"
    final_message = prefix + suffix
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
        await context.bot.send_message(chat_id=hyper_ch, text=final_message)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error posting details: {e}")
        return
    await context.bot.send_message(chat_id=chat_id, text="Upload and hyperlink created successfully!", reply_markup=main_menu_keyboard())
    user_sessions.pop(chat_id, None)

# ----- Text Message Handler (State Machine) -----
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    session = user_sessions.get(chat_id, {})
    step = session.get("step", "main_menu")

    # --- Main Menu ---
    if step == "main_menu":
        if text.lower() == "upload movie":
            session["step"] = "waiting_for_file"
            await update.message.reply_text("Please send the movie file (video or document):", reply_markup=ReplyKeyboardRemove())
        elif text.lower() == "settings":
            session["step"] = "waiting_for_admin_password"
            await update.message.reply_text("Enter admin password:", reply_markup=ReplyKeyboardRemove())
        else:
            await update.message.reply_text("Invalid option. Choose from the menu:", reply_markup=main_menu_keyboard())

    # --- Admin Password ---
    elif step == "waiting_for_admin_password":
        if text == ADMIN_PASSWORD:
            session["step"] = "admin_menu"
            # Show a simple settings menu for bot links management
            keyboard = [["Add Bot Link", "Remove Bot Link", "List Bot Links", "Back to Main"]]
            await update.message.reply_text("Settings Menu:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True))
        else:
            await update.message.reply_text("Incorrect password.", reply_markup=main_menu_keyboard())
            session["step"] = "main_menu"

    # --- Admin Menu (Bot Link Management) ---
    elif step == "admin_menu":
        if text.lower() == "add bot link":
            session["step"] = "waiting_for_new_bot_link"
            await update.message.reply_text("Enter bot hyperlink (e.g., https://t.me/foxtune_bot):", reply_markup=ReplyKeyboardRemove())
        elif text.lower() == "remove bot link":
            if bot_links:
                kb = [list(bot_links.keys()) + ["Back to Admin"]]
                session["step"] = "waiting_for_remove_bot_link"
                await update.message.reply_text("Enter the bot link to remove (type exactly):", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True))
            else:
                await update.message.reply_text("No bot links available.", reply_markup=ReplyKeyboardMarkup([["Back to Admin"]], resize_keyboard=True, one_time_keyboard=True))
        elif text.lower() == "list bot links":
            if bot_links:
                links = "\n".join(bot_links.keys())
                await update.message.reply_text("Bot Links:\n" + links, reply_markup=ReplyKeyboardMarkup([["Back to Admin"]], resize_keyboard=True, one_time_keyboard=True))
            else:
                await update.message.reply_text("No bot links available.", reply_markup=ReplyKeyboardMarkup([["Back to Admin"]], resize_keyboard=True, one_time_keyboard=True))
        elif text.lower() in ["back to admin", "back to main"]:
            session["step"] = "main_menu"
            await update.message.reply_text("Main Menu:", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text("Invalid option. Please choose from the menu.", reply_markup=ReplyKeyboardMarkup([["Add Bot Link", "Remove Bot Link", "List Bot Links", "Back to Main"]], resize_keyboard=True, one_time_keyboard=True))

    # --- Add Bot Link ---
    elif step == "waiting_for_new_bot_link":
        bot_links[text] = {"link": text}
        await update.message.reply_text(f"Bot link '{text}' added successfully!", reply_markup=ReplyKeyboardMarkup([["Back to Admin"]], resize_keyboard=True, one_time_keyboard=True))
        session["step"] = "admin_menu"

    # --- Remove Bot Link ---
    elif step == "waiting_for_remove_bot_link":
        if text in bot_links:
            bot_links.pop(text)
            await update.message.reply_text(f"Bot link '{text}' removed successfully!", reply_markup=ReplyKeyboardMarkup([["Back to Admin"]], resize_keyboard=True, one_time_keyboard=True))
        else:
            await update.message.reply_text("Bot link not found.", reply_markup=ReplyKeyboardMarkup([["Back to Admin"]], resize_keyboard=True, one_time_keyboard=True))
        session["step"] = "admin_menu"

    # --- Upload Flow: Video Channel Selection ---
    elif step == "waiting_for_video_channel":
        if text.lower() == "back to main":
            session["step"] = "main_menu"
            await update.message.reply_text("Returning to main menu.", reply_markup=main_menu_keyboard())
        else:
            # Check if entered text matches any channel title in video_channels.
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
    
    # --- Upload Flow: Prefix Input ---
    elif step == "waiting_for_prefix":
        prefix = update.message.text.strip()
        if not prefix and hasattr(session.get("file"), "file_name"):
            prefix = session.get("file").file_name
        session["prefix"] = prefix
        session["step"] = "waiting_for_hyperlink_channel"
        await present_hyperlink_channels(update.message, context, chat_id)
    
    # --- Upload Flow: Hyperlink Channel Selection ---
    elif step == "waiting_for_hyperlink_channel":
        if text.lower() == "back to main":
            session["step"] = "main_menu"
            await update.message.reply_text("Returning to main menu.", reply_markup=main_menu_keyboard())
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
            await update.message.reply_text(f"Video channel '{video_channels[channel_id]}' added!")
        else:
            await update.message.reply_text("Forward a valid channel message.")
        session["step"] = None
    elif step == "waiting_for_forward_hyperlink":
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
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO, file_handler))
    app.add_handler(MessageHandler(filters.FORWARDED, forwarded_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Set webhook.
    webhook_endpoint = f"{WEBHOOK_URL}/{TOKEN}"
    await app.bot.set_webhook(webhook_endpoint)

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
