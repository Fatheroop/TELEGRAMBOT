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

# Patch the event loop (useful in cloud environments)
nest_asyncio.apply()

# ----- Global Data Storage -----
user_sessions = {}  # Stores session state by chat_id
bot_links = {}      # Stores bot hyperlinks (key: hyperlink string, value: info dict)
groups = {}         # Stores managed group names (key: group name, value: info string)

ADMIN_PASSWORD = "12345"  # Initial admin password

# ----- Main Menu Handler -----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📤 Upload File", callback_data="upload")],
        [InlineKeyboardButton("📥 Fetch File", callback_data="fetch")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("✉️ Send to Group", callback_data="send_to_group")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Main Menu – select an option:", reply_markup=reply_markup)

# ----- CallbackQuery Handler -----

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "upload":
        await upload_file(query, context)
    elif data == "fetch":
        await fetch_file(query, context)
    elif data == "settings":
        # Ask for admin password
        await query.message.reply_text("Enter admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_password"}
    elif data == "send_to_group":
        await query.message.reply_text("Enter the group name to send your call message to:")
        user_sessions[chat_id] = {"step": "waiting_for_group_for_call"}
    elif data == "add_bot":
        await query.message.reply_text("Enter bot hyperlink (e.g., https://t.me/foxtune_bot):")
        user_sessions[chat_id] = {"step": "waiting_for_new_bot"}
    elif data == "remove_bot":
        await query.message.reply_text("Enter bot hyperlink to remove:")
        user_sessions[chat_id] = {"step": "waiting_for_remove_bot"}
    elif data == "manage_groups":
        keyboard = [
            [InlineKeyboardButton("➕ Add Group", callback_data="add_group")],
            [InlineKeyboardButton("➖ Remove Group", callback_data="remove_group")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Manage Groups Menu:", reply_markup=reply_markup)
    elif data == "change_password":
        await query.message.reply_text("Enter new admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_new_password"}
    elif data == "add_group":
        await query.message.reply_text("Enter new group name:")
        user_sessions[chat_id]["step"] = "waiting_for_new_group"
    elif data == "remove_group":
        await query.message.reply_text("Enter group name to remove:")
        user_sessions[chat_id]["step"] = "waiting_for_remove_group"
    else:
        await query.message.reply_text("Unknown option.")

# ----- File Upload / Fetch Functions -----

async def upload_file(query, context: ContextTypes.DEFAULT_TYPE):
    await query.message.reply_text("Send the file you want to upload.")
    user_sessions[query.message.chat_id] = {"step": "waiting_for_file"}

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if session.get("step") != "waiting_for_file":
        return

    file_obj = update.message.document
    if not file_obj and update.message.photo:
        file_obj = update.message.photo[-1]
    if not file_obj:
        await update.message.reply_text("No valid file detected. Please send a document or photo.")
        return

    session["step"] = "waiting_for_group"
    session["file"] = file_obj

    if groups:
        keyboard = []
        for group in groups.keys():
            keyboard.append([InlineKeyboardButton(group, callback_data=f"select_group_{group}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select a group to upload your file to:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("No groups available. Please add groups in settings.")

async def fetch_file(query, context: ContextTypes.DEFAULT_TYPE):
    if groups:
        keyboard = []
        for group in groups.keys():
            keyboard.append([InlineKeyboardButton(group, callback_data=f"fetch_{group}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Select a group to fetch files from:", reply_markup=reply_markup)
    else:
        await query.message.reply_text("No groups available.")

# ----- Admin & Settings Text Handler -----

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_PASSWORD
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if not session or "step" not in session:
        return

    step = session["step"]

    if step == "waiting_for_password":
        if update.message.text.strip() == ADMIN_PASSWORD:
            keyboard = [
                [InlineKeyboardButton("Add Bot Link", callback_data="add_bot")],
                [InlineKeyboardButton("Remove Bot Link", callback_data="remove_bot")],
                [InlineKeyboardButton("Manage Groups", callback_data="manage_groups")],
                [InlineKeyboardButton("Change Password", callback_data="change_password")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
        session["step"] = None

    elif step == "waiting_for_new_bot":
        bot_link = update.message.text.strip()
        # Optionally add validation for a URL format.
        bot_links[bot_link] = {"link": bot_link}
        await update.message.reply_text(f"Bot link '{bot_link}' added successfully!")
        session["step"] = None

    elif step == "waiting_for_remove_bot":
        bot_link = update.message.text.strip()
        if bot_link in bot_links:
            bot_links.pop(bot_link)
            await update.message.reply_text(f"Bot link '{bot_link}' removed successfully!")
        else:
            await update.message.reply_text("Bot link not found!")
        session["step"] = None

    elif step == "waiting_for_new_password":
        session["new_password"] = update.message.text.strip()
        session["step"] = "waiting_for_password_confirmation"
        await update.message.reply_text("Please re-enter new password for confirmation:")

    elif step == "waiting_for_password_confirmation":
        new_pass = session.get("new_password")
        if update.message.text.strip() == new_pass:
            ADMIN_PASSWORD = new_pass
            await update.message.reply_text("Admin password changed successfully!")
        else:
            await update.message.reply_text("Passwords do not match. Password not changed.")
        session["step"] = None

    elif step == "waiting_for_new_group":
        group_name = update.message.text.strip()
        if group_name in groups:
            await update.message.reply_text("Group already exists.")
        else:
            groups[group_name] = f"Info for {group_name}"
            await update.message.reply_text(f"Group '{group_name}' added successfully!")
        session["step"] = None

    elif step == "waiting_for_remove_group":
        group_name = update.message.text.strip()
        if group_name in groups:
            groups.pop(group_name)
            await update.message.reply_text(f"Group '{group_name}' removed successfully!")
        else:
            await update.message.reply_text("Group not found.")
        session["step"] = None

    elif step == "waiting_for_group_for_call":
        group_name = update.message.text.strip()
        if group_name in groups:
            # For demonstration, we simply echo the action.
            await update.message.reply_text(f"Simulating a call message sent to group '{group_name}'.")
        else:
            await update.message.reply_text("Group not found in managed groups.")
        session["step"] = None

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

    # Register command and message handlers.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("send_to_group", lambda u, c: send_to_group(u, c)))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, receive_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Set the webhook endpoint.
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

# (Optional) Helper command to simulate sending a call message to a group.
async def send_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please enter the group name to send your call message to:")
    user_sessions[update.message.chat_id] = {"step": "waiting_for_group_for_call"}

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
