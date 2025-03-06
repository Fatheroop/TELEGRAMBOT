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

# Patch the event loop (useful in environments like Render)
nest_asyncio.apply()

# ----- Global Data -----
# For tracking user sessions; key: chat_id, value: dictionary with state info.
user_sessions = {}
# Dummy group data – replace with your actual data if needed.
group_data = {"Group1": "This is Group1", "Group2": "This is Group2"}
# For storing added bots (key: token, value: bot name)
bot_list = {}
# Global admin password; initially set to "12345"
ADMIN_PASSWORD = "12345"

# ----- Handlers and Functions -----

# /start command: show main menu with Upload File, Fetch File, and Settings.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📤 Upload File", callback_data="upload")],
        [InlineKeyboardButton("📥 Fetch File", callback_data="fetch")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select an option:", reply_markup=reply_markup)

# CallbackQuery handler: routes callback data to the appropriate function.
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
        # Ask for admin password and update session state.
        await query.message.reply_text("Enter admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_password"}
    elif data == "add_bot":
        await init_add_bot(query, context)
    elif data == "remove_bot":
        await init_remove_bot(query, context)
    elif data == "manage_groups":
        await init_manage_groups(query, context)
    elif data == "change_password":
        await init_change_password(query, context)
    elif data == "add_group":
        await query.message.reply_text("Enter new group name to add:")
        user_sessions[chat_id]["step"] = "waiting_for_new_group"
    elif data == "remove_group":
        await query.message.reply_text("Enter group name to remove:")
        user_sessions[chat_id]["step"] = "waiting_for_remove_group"
    elif data.startswith("select_group_"):
        group_name = data.split("select_group_")[1]
        await query.message.reply_text(f"File has been uploaded to group: {group_name}")
        # Clear the file upload session.
        if chat_id in user_sessions:
            user_sessions.pop(chat_id)
    else:
        await query.message.reply_text("Unknown option.")

# Called when the "Upload File" option is chosen.
async def upload_file(query, context: ContextTypes.DEFAULT_TYPE):
    await query.message.reply_text("Send the file you want to upload.")
    user_sessions[query.message.chat_id] = {"step": "waiting_for_file"}

# Called when a file (document or photo) is received.
async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if session.get("step") != "waiting_for_file":
        return  # Not expecting a file.

    # Try to get a document or, if not present, the last photo.
    file_obj = update.message.document
    if not file_obj and update.message.photo:
        file_obj = update.message.photo[-1]

    if not file_obj:
        await update.message.reply_text("No valid file detected. Please send a document or photo.")
        return

    # Save the file info and prompt for group selection.
    session["step"] = "waiting_for_group"
    session["file"] = file_obj

    if group_data:
        keyboard = []
        for group in group_data.keys():
            keyboard.append([InlineKeyboardButton(group, callback_data=f"select_group_{group}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select a group to upload your file to:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("No groups available to select.")

# Dummy fetch function: display available groups for file fetching.
async def fetch_file(query, context: ContextTypes.DEFAULT_TYPE):
    if group_data:
        keyboard = []
        for group in group_data.keys():
            keyboard.append([InlineKeyboardButton(group, callback_data=f"fetch_{group}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Select a group to fetch files from:", reply_markup=reply_markup)
    else:
        await query.message.reply_text("No files found.")

# ----- Admin Functions for Settings ----

async def init_add_bot(query, context: ContextTypes.DEFAULT_TYPE):
    await query.message.reply_text("Enter new bot token and name separated by a space (e.g., <token> BotName):")
    user_sessions[query.message.chat_id] = {"step": "waiting_for_new_bot"}

async def init_remove_bot(query, context: ContextTypes.DEFAULT_TYPE):
    await query.message.reply_text("Enter bot token to remove:")
    user_sessions[query.message.chat_id] = {"step": "waiting_for_remove_bot"}

async def init_manage_groups(query, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Add Group", callback_data="add_group")],
        [InlineKeyboardButton("➖ Remove Group", callback_data="remove_group")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Manage Groups Menu:", reply_markup=reply_markup)

async def init_change_password(query, context: ContextTypes.DEFAULT_TYPE):
    await query.message.reply_text("Enter new admin password:")
    user_sessions[query.message.chat_id] = {"step": "waiting_for_new_password"}

# ----- Text Message Handler for Admin Steps ----

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
                [InlineKeyboardButton("➕ Add Bot", callback_data="add_bot")],
                [InlineKeyboardButton("➖ Remove Bot", callback_data="remove_bot")],
                [InlineKeyboardButton("📋 Manage Groups", callback_data="manage_groups")],
                [InlineKeyboardButton("🔑 Change Password", callback_data="change_password")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
        session["step"] = None

    elif step == "waiting_for_new_bot":
        parts = update.message.text.split()
        if len(parts) < 2:
            await update.message.reply_text("Invalid input. Please provide token and name separated by space.")
        else:
            token = parts[0]
            name = " ".join(parts[1:])
            bot_list[token] = name
            await update.message.reply_text(f"Bot '{name}' added successfully!")
        session["step"] = None

    elif step == "waiting_for_remove_bot":
        token = update.message.text.strip()
        if token in bot_list:
            removed_name = bot_list.pop(token)
            await update.message.reply_text(f"Bot '{removed_name}' removed successfully!")
        else:
            await update.message.reply_text("Bot token not found!")
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
        if group_name in group_data:
            await update.message.reply_text("Group already exists.")
        else:
            group_data[group_name] = f"This is {group_name}"
            await update.message.reply_text(f"Group '{group_name}' added successfully!")
        session["step"] = None

    elif step == "waiting_for_remove_group":
        group_name = update.message.text.strip()
        if group_name in group_data:
            group_data.pop(group_name)
            await update.message.reply_text(f"Group '{group_name}' removed successfully!")
        else:
            await update.message.reply_text("Group not found.")
        session["step"] = None

    else:
        await update.message.reply_text("Command not recognized in this context.")

# ----- Main function: Webhook setup and running the bot -----

async def main():
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")
    if not TOKEN or not WEBHOOK_URL:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN or RENDER_WEBHOOK_URL in .env file!")

    app = Application.builder().token(TOKEN).build()

    # Register command and message handlers.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, receive_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Set the webhook endpoint.
    webhook_endpoint = f"{WEBHOOK_URL}/{TOKEN}"
    await app.bot.set_webhook(webhook_endpoint)

    # Patch the event loop's close method.
    loop = asyncio.get_event_loop()
    loop.close = lambda: None

    # Run the bot using webhook.
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
