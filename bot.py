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

# Patch the event loop (useful for cloud environments)
nest_asyncio.apply()

# ----- Global Data Storage -----
user_sessions = {}         # Stores session state by chat_id
group_data = {}            # Stores groups added by admin; group_name -> group info
# For integrated bots, we use a dict. Additionally, we store the "ECESS BOT" shortcut.
integrated_bots = {}       # bot_username (str) -> info dictionary
ECESS_BOT_SHORTCUT = None  # Will hold the shortcut if a bot with username "@ecessbot" is added

# For groups, you can also assign an admin bot (if desired)
group_admin_bots = {}      # group_name -> bot_username

ADMIN_PASSWORD = "12345"   # Initial admin password

# ----- Main Menu -----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📤 Upload File", callback_data="upload")],
        [InlineKeyboardButton("📥 Fetch File", callback_data="fetch")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("✉️ Send to Integrated Bot", callback_data="send_integration")]
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
        await query.message.reply_text("Enter admin password:")
        user_sessions[chat_id] = {"step": "waiting_for_password"}
    elif data == "send_integration":
        await query.message.reply_text("Enter group name for your cloud call:")
        user_sessions[chat_id] = {"step": "waiting_for_group_for_call"}
    elif data == "integrate_bot":
        await query.message.reply_text("Enter bot username to integrate (e.g., @ecessbot):")
        user_sessions[chat_id] = {"step": "waiting_for_new_integrated_bot"}
    elif data == "remove_integrated_bot":
        await query.message.reply_text("Enter bot username to remove:")
        user_sessions[chat_id] = {"step": "waiting_for_remove_integrated_bot"}
    elif data == "manage_groups":
        keyboard = [
            [InlineKeyboardButton("➕ Add Group", callback_data="add_group")],
            [InlineKeyboardButton("➖ Remove Group", callback_data="remove_group")],
            [InlineKeyboardButton("🛠 Assign Bot to Group", callback_data="assign_bot")]
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
    elif data == "assign_bot":
        await query.message.reply_text("Enter group name to assign a bot to:")
        user_sessions[chat_id]["step"] = "waiting_for_assign_group"
    elif data.startswith("choose_bot_"):
        # Callback data format: "choose_bot__<group>__<bot_username>"
        parts = data.split("__")
        if len(parts) == 3:
            group = parts[1]
            bot_username = parts[2]
            group_admin_bots[group] = bot_username
            await query.message.reply_text(f"Bot {bot_username} assigned to group '{group}'.")
        else:
            await query.message.reply_text("Invalid selection.")
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

    if group_data:
        keyboard = []
        for group in group_data.keys():
            keyboard.append([InlineKeyboardButton(group, callback_data=f"select_group_{group}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select a group to upload your file to:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("No groups available.")

async def fetch_file(query, context: ContextTypes.DEFAULT_TYPE):
    if group_data:
        keyboard = []
        for group in group_data.keys():
            keyboard.append([InlineKeyboardButton(group, callback_data=f"fetch_{group}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Select a group to fetch files from:", reply_markup=reply_markup)
    else:
        await query.message.reply_text("No files found.")

# ----- Admin and Integration Text Handler -----

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_PASSWORD, ECESS_BOT_SHORTCUT
    chat_id = update.message.chat_id
    session = user_sessions.get(chat_id, {})
    if not session or "step" not in session:
        return

    step = session["step"]

    if step == "waiting_for_password":
        if update.message.text.strip() == ADMIN_PASSWORD:
            keyboard = [
                [InlineKeyboardButton("Integrate Bot", callback_data="integrate_bot")],
                [InlineKeyboardButton("Remove Integrated Bot", callback_data="remove_integrated_bot")],
                [InlineKeyboardButton("Manage Groups", callback_data="manage_groups")],
                [InlineKeyboardButton("Change Password", callback_data="change_password")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Settings Menu:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Incorrect password!")
        session["step"] = None

    elif step == "waiting_for_new_integrated_bot":
        bot_username = update.message.text.strip()
        if not bot_username.startswith("@"):
            await update.message.reply_text("Please start the bot username with '@'.")
        else:
            integrated_bots[bot_username.lower()] = {"username": bot_username}
            # If this is the ECESS BOT, set it as the shortcut.
            if bot_username.lower() == "@ecessbot":
                ECESS_BOT_SHORTCUT = bot_username
                await update.message.reply_text(f"Bot {bot_username} integrated as your ECESS BOT shortcut!")
            else:
                await update.message.reply_text(f"Bot {bot_username} integrated successfully!")
        session["step"] = None

    elif step == "waiting_for_remove_integrated_bot":
        bot_username = update.message.text.strip().lower()
        if bot_username in integrated_bots:
            integrated_bots.pop(bot_username)
            if ECESS_BOT_SHORTCUT and ECESS_BOT_SHORTCUT.lower() == bot_username:
                ECESS_BOT_SHORTCUT = None
            await update.message.reply_text(f"Bot {bot_username} removed from integration!")
        else:
            await update.message.reply_text("Bot not found in integrated bots.")
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
            group_data[group_name] = f"Info for {group_name}"
            await update.message.reply_text(f"Group '{group_name}' added successfully!")
        session["step"] = None

    elif step == "waiting_for_remove_group":
        group_name = update.message.text.strip()
        if group_name in group_data:
            group_data.pop(group_name)
            group_admin_bots.pop(group_name, None)
            await update.message.reply_text(f"Group '{group_name}' removed successfully!")
        else:
            await update.message.reply_text("Group not found.")
        session["step"] = None

    elif step == "waiting_for_assign_group":
        group_name = update.message.text.strip()
        if group_name not in group_data:
            await update.message.reply_text("Group not found. Please add the group first.")
            session["step"] = None
        elif not integrated_bots:
            await update.message.reply_text("No integrated bots available. Please integrate one first.")
            session["step"] = None
        else:
            session["assign_group"] = group_name
            session["step"] = "waiting_for_bot_selection_for_group"
            keyboard = []
            for bot in integrated_bots.keys():
                # Format: "choose_bot__<group>__<bot_username>"
                keyboard.append([InlineKeyboardButton(integrated_bots[bot]["username"], callback_data=f"choose_bot__{group_name}__{bot}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Select an integrated bot to assign to this group:", reply_markup=reply_markup)

    elif step == "waiting_for_group_for_call":
        group_name = update.message.text.strip()
        # If a bot is assigned to this group, use it; otherwise, use ECESS_BOT_SHORTCUT if available.
        if group_name in group_admin_bots:
            bot_username = group_admin_bots[group_name]
            await update.message.reply_text(f"Routing your call via the assigned bot: {bot_username}")
        elif ECESS_BOT_SHORTCUT:
            await update.message.reply_text(f"No group-specific bot assigned. Routing your call via ECESS BOT: {ECESS_BOT_SHORTCUT}")
        else:
            await update.message.reply_text("No integrated bot available for routing the call.")
        session["step"] = None

    else:
        await update.message.reply_text("Command not recognized in this context.")

# ----- Demo Command (optional) -----

async def send_to_integration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please enter your group name to send a call message to its integrated bot:")
    user_sessions[update.message.chat_id] = {"step": "waiting_for_group_for_call"}

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
    app.add_handler(CommandHandler("send_to_integration", send_to_integration))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, receive_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Set webhook endpoint.
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
